from tokenize import String
from serial import Serial
from time import sleep
from services import Logger, AppConfig
from abc import ABC, abstractmethod

class Stage(ABC):
    """Abstract base class defining the interface for all cameras."""

    def __init__(self, port, parity, baudrate, stopbits, bytesize, timeout):
        
        self.logger = Logger() # Singleton instance
        self.my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes

    @abstractmethod
    def move(self, distance):
        pass

    @abstractmethod
    def get(self):
        pass



class OlympusStageController(Stage):

    def __init__(self):

        self.port = self.my_app_config.get("stage_port")
        self.baudrate = self.my_app_config.get("stage_baudrate")
        self.parity = self.my_app_config.get("stage_parity")
        self.stopbits = self.my_app_config.get("stage_stopbits")
        self.bytesize = self.my_app_config.get("stage_bytesize")
        self.timeout = self.my_app_config.get("stage_timeout")

    def connect(self):
        try:

            self.ser = Serial(
                        port=self.port,
                        baudrate=self.baudrate,
                        parity=self.parity,
                        stopbits=self.stopbits,
                        bytesize=self.bytesize,
                        timeout=self.timeout)

            if self.ser.is_open:
                self.logger.debug(f"Connected to stage.")
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error connecting to stage: {e}")
            return False


    def send_command(self, command):
        self.ser.write((command + '\n').encode())

    def read_response(self):
        return self.ser.readline().decode().strip()

    def move(self, distance):
        pass

    def get(self):
        pass




class TemikaStageController(Stage):

    def __init__(self):
        from hardware import TemikaComms
        self.temika_comms = TemikaComms()
        self.my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes
        self.logger = Logger()
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

        if "status" in reply:
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


class StageControllerFactory:

    @staticmethod
    def create_stage_controller():
        logger = Logger() # Singleton instance
        my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes
        stage_type = my_app_config.get("stage_type")

        if stage_type == "Olympus":
            return OlympusStageController()
        elif stage_type == "Temika":
            return TemikaStageController()
        else:
            logger.error(f"Unknown stage type: {stage_type}")
            return None
