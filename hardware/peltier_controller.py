import math

from services import AppConfig, Logger
from .temika_comms import TemikaComms


class PeltierController:
    """Control the Temika Peltier feedback channel."""

    def __init__(self) -> None:
        self.logger = Logger()
        app_config = AppConfig()
        self.kp = float(app_config.get("Peltier_Kp", 1000))
        self.ki = float(app_config.get("Peltier_Ki", 5))
        self.max_duty_cycle = float(app_config.get("Peltier_Max_Duty_Cycle", 0.5))

        if not 0 <= self.max_duty_cycle <= 1:
            raise ValueError("Peltier_Max_Duty_Cycle must be between 0 and 1")

        self.comms = TemikaComms()

    def set_status(self, status: str) -> None:
        """Enable or disable Peltier temperature feedback."""
        normalized_status = status.lower()
        if normalized_status not in {"active", "inactive"}:
            raise ValueError("Peltier status must be 'active' or 'inactive'")

        enable = "ON" if normalized_status == "active" else "OFF"
        command = (
            '<pwr number="0">'
            "<feedback>"
            f"<enable>{enable}</enable>"
            "<type>PELTIER</type>"
            "<sensor>RTD</sensor>"
            f"<max_duty_cycle>{self.max_duty_cycle:g}</max_duty_cycle>"
            f"<kp>{self.kp:g}</kp>"
            f"<ki>{self.ki:g}</ki>"
            "</feedback>"
            "</pwr>"
        )
        self.comms.send_command(command)

    def set_temperature(self, temperature: float) -> None:
        """Set the Peltier temperature setpoint in degrees Celsius."""
        temperature = float(temperature)
        if not math.isfinite(temperature):
            raise ValueError("Peltier temperature must be finite")

        command = (
            '<pwr number="0">'
            "<feedback>"
            f"<set>{temperature:g}</set>"
            "</feedback>"
            "</pwr>"
        )
        self.comms.send_command(command)
