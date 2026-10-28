"""Shared Micro-Manager connection for the Olympus IX81 microscope frame."""

from __future__ import annotations

import os
from pathlib import Path

import pymmcore

from services import AppConfig, Logger
from services.singleton import Singleton


class OlympusIX81Hub(metaclass=Singleton):
    """Own the single Micro-Manager/serial session used by IX81 peripherals."""

    DEFAULT_MM_PATH = Path(r"C:\Program Files\Micro-Manager-2.0")
    DEVICE_NAMES = {
        "focus": "ManualFocus",
        "objective": "Objective",
        "filter_cube": "FilterCube",
        "autofocus": "AutoFocusZDC",
    }

    def __init__(self) -> None:
        self.config = AppConfig()
        self.logger = Logger()
        self.port = self.config.get(
            "ix81_port", self.config.get("focus_port", "COM9")
        )
        self.mm_path = Path(
            self.config.get("micromanager_path", str(self.DEFAULT_MM_PATH))
        )
        self.core: pymmcore.CMMCore | None = None
        self._dll_directory = None
        self.labels: dict[str, str] = {}
        self.connect()

    def connect(self) -> bool:
        if self.core is not None:
            return True

        adapter = self.mm_path / "mmgr_dal_Olympus.dll"
        if not adapter.exists():
            raise FileNotFoundError(f"Olympus Micro-Manager adapter not found: {adapter}")

        self._dll_directory = os.add_dll_directory(str(self.mm_path))
        core = pymmcore.CMMCore()
        core.enableStderrLog(False)
        core.setDeviceAdapterSearchPaths([str(self.mm_path)])

        try:
            self._configure_serial_port(core)
            core.loadDevice("IX81", "Olympus", "OlympusHub")
            core.setProperty("IX81", "Port", self.port)
            core.initializeDevice("IX81")

            for role, device_name in self.DEVICE_NAMES.items():
                label = f"IX81-{device_name}"
                try:
                    core.loadDevice(label, "Olympus", device_name)
                    core.setParentLabel(label, "IX81")
                    core.initializeDevice(label)
                    self.labels[role] = label
                except Exception as error:
                    self.logger.warning(
                        f"IX81 peripheral {device_name} is unavailable: {error}"
                    )

            if "focus" not in self.labels:
                raise RuntimeError("The IX81 ManualFocus device is unavailable")
        except Exception:
            core.reset()
            if self._dll_directory is not None:
                self._dll_directory.close()
                self._dll_directory = None
            raise

        self.core = core
        self.logger.info(f"Connected to Olympus IX81 frame on {self.port}.")
        return True

    def _configure_serial_port(self, core: pymmcore.CMMCore) -> None:
        core.loadDevice(self.port, "SerialManager", self.port)
        settings = {
            "AnswerTimeout": "500",
            "BaudRate": "19200",
            "DelayBetweenCharsMs": "0",
            "Handshaking": "Off",
            "Parity": "Even",
            "StopBits": "2",
        }
        for name, value in settings.items():
            core.setProperty(self.port, name, value)
        core.initializeDevice(self.port)

    def close(self) -> None:
        if self.core is not None:
            self.core.reset()
            self.core = None
            self.labels.clear()
        if self._dll_directory is not None:
            self._dll_directory.close()
            self._dll_directory = None

    def _device(self, role: str) -> tuple[pymmcore.CMMCore, str]:
        if self.core is None:
            self.connect()
        if role not in self.labels:
            raise RuntimeError(f"IX81 {role.replace('_', ' ')} device is unavailable")
        assert self.core is not None
        return self.core, self.labels[role]

    def get_focus_position(self) -> float:
        core, label = self._device("focus")
        return float(core.getPosition(label))

    def move_focus_absolute(self, position_um: float) -> None:
        core, label = self._device("focus")
        core.setPosition(label, float(position_um))
        core.waitForDevice(label)

    def get_objective_position(self) -> int:
        core, label = self._device("objective")
        return int(core.getState(label)) + 1

    def set_objective_position(self, position: int) -> None:
        core, label = self._device("objective")
        self._set_six_position_device(core, label, position)

    def get_filter_cube_position(self) -> int:
        core, label = self._device("filter_cube")
        return int(core.getState(label)) + 1

    def set_filter_cube_position(self, position: int) -> None:
        core, label = self._device("filter_cube")
        self._set_six_position_device(core, label, position)

    @staticmethod
    def _set_six_position_device(
        core: pymmcore.CMMCore, label: str, position: int
    ) -> None:
        if position not in range(1, 7):
            raise ValueError("position must be between 1 and 6")
        core.setState(label, position - 1)
        core.waitForDevice(label)

    def autofocus_available(self) -> bool:
        return "autofocus" in self.labels

    def set_autofocus(self, enabled: bool) -> bool:
        if not self.autofocus_available():
            return False
        core, label = self._device("autofocus")
        if enabled:
            core.fullFocus()
        else:
            core.enableContinuousFocus(False)
        core.waitForDevice(label)
        return True
