"""Minimal serial interface for the Olympus STC stage controller."""

from __future__ import annotations

from time import monotonic, sleep
from typing import Callable

from serial import EIGHTBITS, PARITY_NONE, STOPBITS_ONE, Serial


class OlympusSTC:
    """Small STC client intended for initial hardware smoke testing.

    Coordinates are expressed in millimetres, as specified by the STC manual.
    The controller uses reverse-polish commands, for example ``1 0 r``.
    """

    def __init__(
        self,
        port: str,
        *,
        timeout: float = 1.0,
        line_ending: str = "\r",
        serial_factory: Callable[..., Serial] = Serial,
    ) -> None:
        if not port:
            raise ValueError("An Olympus STC serial port is required")

        self.port = port
        self.timeout = timeout
        self.line_ending = line_ending
        self._serial_factory = serial_factory
        self.serial: Serial | None = None

    def connect(self) -> None:
        if self.serial is not None and self.serial.is_open:
            return

        self.serial = self._serial_factory(
            port=self.port,
            baudrate=19200,
            bytesize=EIGHTBITS,
            parity=PARITY_NONE,
            stopbits=STOPBITS_ONE,
            timeout=self.timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def close(self) -> None:
        if self.serial is not None and self.serial.is_open:
            self.serial.close()

    def __enter__(self) -> "OlympusSTC":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def send(self, command: str) -> None:
        serial_port = self._require_connection()
        serial_port.write(f"{command}{self.line_ending}".encode("ascii"))
        serial_port.flush()

    def query(self, command: str) -> str:
        serial_port = self._require_connection()
        serial_port.reset_input_buffer()
        self.send(command)
        # The manual describes an Enter-terminated ASCII interface. Reading a
        # byte at a time also handles controllers returning CR without LF.
        response = bytearray()
        deadline = monotonic() + self.timeout
        while monotonic() < deadline:
            byte = serial_port.read(1)
            if not byte:
                continue
            if byte in (b"\r", b"\n"):
                if response:
                    break
                continue
            response.extend(byte)
        return response.decode("ascii", errors="replace").strip()

    def identify(self) -> str:
        return self.query("identify")

    def get_position(self) -> tuple[float, float]:
        response = self.query("p")
        fields = response.replace(",", ".").split()
        if len(fields) != 2:
            raise RuntimeError(f"Unexpected STC position response: {response!r}")
        return float(fields[0]), float(fields[1])

    def move_relative(self, x_mm: float, y_mm: float) -> None:
        self.send(f"{x_mm:g} {y_mm:g} r")

    def move_absolute(self, x_mm: float, y_mm: float) -> None:
        self.send(f"{x_mm:g} {y_mm:g} m")

    def get_status(self) -> int:
        response = self.query("st")
        try:
            return int(response)
        except ValueError as error:
            raise RuntimeError(f"Unexpected STC status response: {response!r}") from error

    def wait_until_ready(self, timeout: float = 30.0, poll_interval: float = 0.05) -> None:
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if self.get_status() & 1 == 0:
                return
            sleep(poll_interval)
        raise TimeoutError(f"Olympus STC did not become ready within {timeout:g} seconds")

    def _require_connection(self) -> Serial:
        if self.serial is None or not self.serial.is_open:
            raise RuntimeError("Olympus STC is not connected")
        return self.serial
