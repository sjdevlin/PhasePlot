"""Minimal ctypes interface to the Thorlabs DC4100 IVI driver."""

from __future__ import annotations

import ctypes
import time
from pathlib import Path


class DC4100Error(RuntimeError):
    """Raised when the native DC4100 driver reports an error."""


class ThorlabsDC4100:
    """Small DC4100 interface intended for connectivity testing.

    Public channel numbers are 1--4.  The Thorlabs driver uses 0--3.
    """

    DRIVER_PATH = Path(r"C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLDC4100_64.dll")
    MODE_CONSTANT_CURRENT = 0
    MODE_BRIGHTNESS = 1

    def __init__(self, resource: str = "ASRL8::INSTR", driver_path: Path | None = None):
        self.resource = resource
        path = Path(driver_path or self.DRIVER_PATH)
        if not path.exists():
            raise DC4100Error(
                f"Thorlabs DC4100 driver not found at {path}. Install the 64-bit "
                "Thorlabs DC4100 IVI driver."
            )
        self._dll = ctypes.WinDLL(str(path))
        self._session = ctypes.c_uint32(0)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        u32 = ctypes.c_uint32
        i32 = ctypes.c_int32
        f32 = ctypes.c_float
        u16 = ctypes.c_uint16
        self._dll.TLDC4100_init.argtypes = [ctypes.c_char_p, u16, u16, ctypes.POINTER(u32)]
        self._dll.TLDC4100_init.restype = i32
        self._dll.TLDC4100_close.argtypes = [u32]
        self._dll.TLDC4100_close.restype = i32
        self._dll.TLDC4100_error_message.argtypes = [u32, i32, ctypes.c_char_p]
        self._dll.TLDC4100_error_message.restype = i32

        self._dll.TLDC4100_identificationQuery.argtypes = [
            u32, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p
        ]
        self._dll.TLDC4100_identificationQuery.restype = i32
        for name in ("OperationMode", "SelectionMode"):
            getattr(self._dll, f"TLDC4100_get{name}").argtypes = [u32, ctypes.POINTER(i32)]
            getattr(self._dll, f"TLDC4100_get{name}").restype = i32
            getattr(self._dll, f"TLDC4100_set{name}").argtypes = [u32, i32]
            getattr(self._dll, f"TLDC4100_set{name}").restype = i32
        self._dll.TLDC4100_getLedOnOff.argtypes = [u32, i32, ctypes.POINTER(u16)]
        self._dll.TLDC4100_getLedOnOff.restype = i32
        self._dll.TLDC4100_setLedOnOff.argtypes = [u32, i32, u16]
        self._dll.TLDC4100_setLedOnOff.restype = i32
        for name in ("PercentalBrightness", "ConstCurrent", "LimitCurrent", "Wavelength"):
            getattr(self._dll, f"TLDC4100_get{name}").argtypes = [u32, i32, ctypes.POINTER(f32)]
            getattr(self._dll, f"TLDC4100_get{name}").restype = i32
        self._dll.TLDC4100_setPercentalBrightness.argtypes = [u32, i32, f32]
        self._dll.TLDC4100_setPercentalBrightness.restype = i32

    def _check(self, status: int, operation: str) -> None:
        if status >= 0:
            return
        message = ctypes.create_string_buffer(512)
        if self._session.value:
            self._dll.TLDC4100_error_message(self._session, status, message)
        detail = message.value.decode(errors="replace") or f"status {status}"
        raise DC4100Error(f"{operation} failed: {detail}")

    @staticmethod
    def _index(channel: int) -> int:
        if channel not in range(1, 5):
            raise ValueError("channel must be 1, 2, 3, or 4")
        return channel - 1

    def open(self) -> "ThorlabsDC4100":
        # Query identity, but never reset the instrument on connection.
        status = self._dll.TLDC4100_init(
            self.resource.encode("ascii"), 1, 0, ctypes.byref(self._session)
        )
        self._check(status, f"opening {self.resource}")
        return self

    def close(self) -> None:
        if self._session.value:
            status = self._dll.TLDC4100_close(self._session)
            self._session = ctypes.c_uint32(0)
            if status < 0:
                raise DC4100Error(f"closing controller failed with status {status}")

    def __enter__(self) -> "ThorlabsDC4100":
        return self.open()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def identity(self) -> dict[str, str]:
        buffers = [ctypes.create_string_buffer(256) for _ in range(4)]
        status = self._dll.TLDC4100_identificationQuery(self._session, *buffers)
        self._check(status, "querying identity")
        keys = ("manufacturer", "model", "serial", "firmware")
        return {key: value.value.decode(errors="replace") for key, value in zip(keys, buffers)}

    def _get_int(self, name: str) -> int:
        value = ctypes.c_int32()
        self._check(getattr(self._dll, f"TLDC4100_get{name}")(self._session, ctypes.byref(value)), f"reading {name}")
        return value.value

    def _get_channel_float(self, name: str, channel: int) -> float:
        value = ctypes.c_float()
        self._check(
            getattr(self._dll, f"TLDC4100_get{name}")(
                self._session, self._index(channel), ctypes.byref(value)
            ),
            f"reading channel {channel} {name}",
        )
        return value.value

    def operation_mode(self) -> int:
        return self._get_int("OperationMode")

    def selection_mode(self) -> int:
        return self._get_int("SelectionMode")

    def is_on(self, channel: int) -> bool:
        value = ctypes.c_uint16()
        self._check(
            self._dll.TLDC4100_getLedOnOff(self._session, self._index(channel), ctypes.byref(value)),
            f"reading channel {channel} output state",
        )
        return bool(value.value)

    def brightness(self, channel: int) -> float:
        return self._get_channel_float("PercentalBrightness", channel)

    def constant_current(self, channel: int) -> float:
        return self._get_channel_float("ConstCurrent", channel)

    def current_limit(self, channel: int) -> float:
        return self._get_channel_float("LimitCurrent", channel)

    def wavelength(self, channel: int) -> float:
        return self._get_channel_float("Wavelength", channel)

    def set_output(self, channel: int, enabled: bool) -> None:
        self._check(
            self._dll.TLDC4100_setLedOnOff(self._session, self._index(channel), int(enabled)),
            f"turning channel {channel} {'on' if enabled else 'off'}",
        )

    def pulse(self, channel: int, brightness_percent: float, seconds: float) -> None:
        """Pulse one channel, restoring its previous settings afterward."""
        if not 0.0 <= brightness_percent <= 100.0:
            raise ValueError("brightness_percent must be between 0 and 100")
        if not 0.0 < seconds <= 60.0:
            raise ValueError("seconds must be greater than 0 and no more than 60")

        index = self._index(channel)
        old_mode = self.operation_mode()
        old_brightness = self.brightness(channel)
        old_state = self.is_on(channel)
        try:
            self._check(self._dll.TLDC4100_setOperationMode(self._session, self.MODE_BRIGHTNESS), "selecting brightness mode")
            self._check(
                self._dll.TLDC4100_setPercentalBrightness(
                    self._session, index, ctypes.c_float(brightness_percent)
                ),
                f"setting channel {channel} brightness",
            )
            self.set_output(channel, True)
            time.sleep(seconds)
        finally:
            self.set_output(channel, False)
            self._dll.TLDC4100_setPercentalBrightness(self._session, index, ctypes.c_float(old_brightness))
            self._dll.TLDC4100_setOperationMode(self._session, old_mode)
            if old_state:
                self.set_output(channel, True)
