"""Minimal IDS peak camera client for connectivity and acquisition testing."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path


class IDSCamera:
    """Open an IDS uEye+ camera and acquire a single image buffer."""

    def __init__(self, model: str = "U3-3990SE-M-GL", serial_number: str | None = None):
        self.expected_model = model
        self.expected_serial = serial_number
        self._ids_peak = None
        self._ids_peak_ipl_extension = None
        self._device = None
        self._node_map = None
        self._library_initialized = False

    @staticmethod
    def _load_sdk():
        try:
            from ids_peak import ids_peak
            from ids_peak import ids_peak_ipl_extension
        except ImportError as error:
            raise RuntimeError(
                "The IDS peak Python binding is missing. Install the native IDS peak "
                "SDK, then run: python -m pip install ids_peak"
            ) from error
        return ids_peak, ids_peak_ipl_extension

    def connect(self) -> dict[str, str]:
        if self._device is not None:
            return self.device_info()

        self._ids_peak, self._ids_peak_ipl_extension = self._load_sdk()
        self._ids_peak.Library.Initialize()
        self._library_initialized = True

        manager = self._ids_peak.DeviceManager.Instance()
        manager.Update()
        devices = list(manager.Devices())
        if not devices:
            self.close()
            raise RuntimeError(
                "IDS peak found no cameras. Check USB power/cabling and verify the "
                "camera in IDS peak Cockpit."
            )

        available = []
        selected = None
        for descriptor in devices:
            info = self._descriptor_info(descriptor)
            available.append(info)
            model_matches = self._model_matches(info["model"])
            serial_matches = not self.expected_serial or info["serial"] == self.expected_serial
            if selected is None and model_matches and serial_matches:
                selected = descriptor

        if selected is None:
            self.close()
            found = ", ".join(
                f"{item['model']} (serial {item['serial']})" for item in available
            )
            raise RuntimeError(
                f"IDS camera {self.expected_model!r} was not found. Detected: {found}"
            )

        self._device = selected.OpenDevice(self._ids_peak.DeviceAccessType_Control)
        self._node_map = self._device.RemoteDevice().NodeMaps()[0]
        return self.device_info()

    def close(self) -> None:
        self._node_map = None
        self._device = None
        if self._library_initialized and self._ids_peak is not None:
            self._ids_peak.Library.Close()
        self._library_initialized = False

    def __enter__(self) -> "IDSCamera":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def device_info(self) -> dict[str, str]:
        if self._device is None:
            raise RuntimeError("IDS camera is not connected")
        return {
            "model": self._read_string_node("DeviceModelName"),
            "serial": self._read_string_node("DeviceSerialNumber"),
            "vendor": self._read_string_node("DeviceVendorName"),
        }

    def set_exposure_time(self, exposure_time_us: float) -> None:
        self._require_connection()
        # IDS peak Cockpit may leave automatic exposure enabled after it exits.
        # In that mode GenICam intentionally makes ExposureTime read-only.
        exposure_auto = self._node_map.FindNode("ExposureAuto")
        if exposure_auto.CurrentEntry().SymbolicValue() != "Off":
            exposure_auto.SetCurrentEntry("Off")

        exposure_time = self._node_map.FindNode("ExposureTime")
        requested = float(exposure_time_us)
        minimum = float(exposure_time.Minimum())
        maximum = float(exposure_time.Maximum())
        if not minimum <= requested <= maximum:
            raise ValueError(
                f"Exposure time {requested:g} us is outside the camera range "
                f"{minimum:g} to {maximum:g} us"
            )
        exposure_time.SetValue(requested)

    def capture_image(
        self, timeout_ms: int = 5000, output_path: str | Path | None = None
    ) -> dict[str, object]:
        """Acquire one frame and return basic metadata for the smoke test."""
        self._require_connection()
        streams = self._device.DataStreams()
        if streams.empty():
            raise RuntimeError("The IDS camera exposes no data stream")

        data_stream = streams[0].OpenDataStream()
        payload_size = self._node_map.FindNode("PayloadSize").Value()
        for _ in range(data_stream.NumBuffersAnnouncedMinRequired()):
            buffer = data_stream.AllocAndAnnounceBuffer(payload_size)
            data_stream.QueueBuffer(buffer)

        frame = None
        pixel_data = None
        self._node_map.FindNode("TLParamsLocked").SetValue(1)
        try:
            data_stream.StartAcquisition()
            self._node_map.FindNode("AcquisitionStart").Execute()
            self._node_map.FindNode("AcquisitionStart").WaitUntilDone()

            buffer = data_stream.WaitForFinishedBuffer(timeout_ms)
            try:
                image = self._ids_peak_ipl_extension.BufferToImage(buffer)
                pixel_format = image.PixelFormat()
                pixel_data = image.get_numpy_2D().copy()
                frame = {
                    "width": image.Width(),
                    "height": image.Height(),
                    "pixel_format": pixel_format.Name(),
                    "timestamp_ns": buffer.Timestamp_ns(),
                }
            finally:
                data_stream.QueueBuffer(buffer)
        finally:
            try:
                self._node_map.FindNode("AcquisitionStop").Execute()
                self._node_map.FindNode("AcquisitionStop").WaitUntilDone()
            finally:
                data_stream.StopAcquisition(self._ids_peak.AcquisitionStopMode_Default)
                data_stream.Flush(self._ids_peak.DataStreamFlushMode_DiscardAll)
                for buffer in data_stream.AnnouncedBuffers():
                    data_stream.RevokeBuffer(buffer)
                self._node_map.FindNode("TLParamsLocked").SetValue(0)

        if frame is None or pixel_data is None:
            raise RuntimeError("IDS acquisition completed without an image")

        if output_path is not None:
            from PIL import Image

            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(pixel_data).save(destination)
            frame["output_path"] = str(destination.resolve())

        return frame

    def _read_string_node(self, name: str) -> str:
        try:
            return str(self._node_map.FindNode(name).Value())
        except Exception:
            return ""

    @staticmethod
    def _descriptor_info(descriptor) -> dict[str, str]:
        return {
            "model": str(descriptor.ModelName()),
            "serial": str(descriptor.SerialNumber()),
            "display_name": str(descriptor.DisplayName()),
        }

    def _model_matches(self, detected_model: str) -> bool:
        if not self.expected_model:
            return True
        expected = self.expected_model.removesuffix("-GL")
        detected_pattern = detected_model.replace("x", "?")
        return detected_model == self.expected_model or fnmatchcase(
            expected, detected_pattern
        )

    def _require_connection(self) -> None:
        if self._device is None or self._node_map is None:
            raise RuntimeError("IDS camera is not connected")
