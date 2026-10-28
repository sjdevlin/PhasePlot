from services import Logger, AppConfig
from abc import ABC, abstractmethod

class Stage(ABC):
    """Abstract base class defining the interface for all stages."""

    def __init__(self):
        self.logger = Logger() # Singleton instance
        self.my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes

    @abstractmethod
    def move(self, distance):
        pass

    @abstractmethod
    def get(self):
        pass

    def get_position(self, axis="x"):
        return self.get()



class OlympusStageController(Stage):

    def __init__(self):
        super().__init__()
        from hardware.olympus_stc import OlympusSTC

        self.normal_stage_speed = float(
            self.my_app_config.get("normal_stage_speed", 6250)
        ) / 1000.0
        self.max_stage_speed = float(
            self.my_app_config.get("max_stage_speed", 25000)
        ) / 1000.0
        self.origin_offset_x = float(
            self.my_app_config.get("origin_offset_x", 0)
        ) / 1000.0
        self.origin_offset_y = float(
            self.my_app_config.get("origin_offset_y", 0)
        ) / 1000.0
        self.stc = OlympusSTC(
            port=self.my_app_config.get("stage_port"),
            timeout=float(self.my_app_config.get("stage_timeout", 1.0)),
        )

    def connect(self):
        try:
            self.stc.connect()
            identity = self.stc.identify()
            self.logger.debug(f"Connected to Olympus stage: {identity}")
            return True
        except Exception as e:
            self.logger.error(f"Error connecting to stage: {e}")
            return False

    def _ensure_connected(self):
        if self.stc.serial is None or not self.stc.serial.is_open:
            if not self.connect():
                raise ConnectionError("Could not connect to the Olympus STC stage")

    def move(self, axis, position, speed="normal"):
        """Move one axis to an absolute PhasePlot position in millimetres."""
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        self._ensure_connected()
        stage_speed = self.max_stage_speed if speed == "max" else self.normal_stage_speed
        self.stc.set_velocity(stage_speed)

        raw_x, raw_y = self.stc.get_position()
        if axis == "x":
            raw_x = float(position) - self.origin_offset_x
        else:
            # Preserve PhasePlot's existing convention that increasing plate Y
            # corresponds to decreasing hardware Y.
            raw_y = self.origin_offset_y - float(position)
        self.stc.move_absolute(raw_x, raw_y)
        self.stc.wait_until_ready()

    def reset(self, axis="x"):
        """Set the selected hardware axis coordinate to zero without moving."""
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        self._ensure_connected()
        raw_x, raw_y = self.stc.get_position()
        if axis == "x":
            raw_x = 0.0
        else:
            raw_y = 0.0
        self.stc.set_position(raw_x, raw_y)

    def get(self, axis="x"):
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        self._ensure_connected()
        raw_x, raw_y = self.stc.get_position()
        return raw_x if axis == "x" else raw_y

    def get_position(self, axis="x"):
        raw_position = self.get(axis)
        if axis == "y":
            return self.origin_offset_y - raw_position
        return raw_position + self.origin_offset_x




class TemikaStageController(Stage):

    def __init__(self):
        super().__init__()
        from hardware import TemikaComms
        self.temika_comms = TemikaComms()
        self.name = self.my_app_config.get("temika_name")
        self.normal_stage_speed = self.my_app_config.get("normal_stage_speed", 1000)  # in microns/s
        self.max_stage_speed = self.my_app_config.get("max_stage_speed", 10000)


    def move(self, axis, position, speed):
        stage_speed = self.max_stage_speed if speed == "max" else self.normal_stage_speed
        position = position * self.my_app_config.get("stage_scale", 1.0)
        offset = self.my_app_config.get("origin_offset_x") if axis == "x" else self.my_app_config.get("origin_offset_y")
        position -= offset  # Apply origin offset
        position = -1 * position  if axis == "y" else position  # Invert Y axis for Temika
        command = f"<{self.name}>"
        command += f"<stepper axis=\"{axis}\">"
        command += f"<move_absolute>{position} {stage_speed}</move_absolute>"
        command += "<wait_moving_end></wait_moving_end>"
        command += "</stepper>"
        command += f"</{self.name}>"
        self.temika_comms.send_command(command, wait_for="Done")

    def reset(self, axis="x"):
        command = f"<{self.name}>"
        command += f"<stepper axis=\"{axis}\">"
        command += f"<reset></reset>"
        command += "</stepper>"
        command += f"</{self.name}>"
        self.temika_comms.send_command(command)


    def get(self, axis="x"):
        command = f"<{self.name}>"
        command += f"<stepper axis=\"{axis}\">"
        command += "<status></status>"
        command += "</stepper>"
        command += f"</{self.name}>"
        reply = self.temika_comms.send_command(command,wait_for="status")

        if reply and "status" in reply:
            parts = reply.split("status ")
            if len(parts) > 1:
                pos = float(parts[1].split()[0])
                pos = pos / self.my_app_config.get("stage_scale", 1.0)
            else:
                pos = 0.0
        else:
            self.logger.error(f"No status found in reply, returning 0.0 position for {axis}.")
            pos = 0.0
        return pos

    def get_position(self, axis="x"):
        raw_position = self.get(axis)
        scale = self.my_app_config.get("stage_scale", 1.0)
        offset = self.my_app_config.get("origin_offset_x") if axis == "x" else self.my_app_config.get("origin_offset_y")
        offset_position = offset / scale

        if axis == "y":
            return offset_position - raw_position
        return raw_position + offset_position


class StageControllerFactory:

    @staticmethod
    def create_stage_controller():
        logger = Logger() # Singleton instance
        my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes
        stage_type = my_app_config.get("stage_type")

        if stage_type in ("Olympus", "Olympus_STC"):
            return OlympusStageController()
        elif stage_type == "Temika":
            return TemikaStageController()
        else:
            logger.error(f"Unknown stage type: {stage_type}")
            return None
