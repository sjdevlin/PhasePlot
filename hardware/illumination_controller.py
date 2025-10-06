from serial import Serial
from services import Logger, AppConfig
from abc import ABC, abstractmethod

class Illumination(ABC):
    """Abstract base class defining the interface for all LED drivers."""

    def __init__(self):
        
        self.logger = Logger() # Singleton instance
        self.my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes

# no abstract methods due to different implementations


class ThorLabsIlluminationController(Illumination):

    def __init__(self):

        self.port = self.my_app_config.get("illumination_port")
        self.baudrate = self.my_app_config.get("illumination_baudrate")
        self.parity = self.my_app_config.get("illumination_parity")
        self.stopbits = self.my_app_config.get("illumination_stopbits")
        self.bytesize = self.my_app_config.get("illumination_bytesize")
        self.timeout = self.my_app_config.get("illumination_timeout")

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
                self.logger.debug(f"Connected to illumination controller.")
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error connecting to illumination controller: {e}")
            return False


    def send_command(self, command):
        self.ser.write((command + '\n').encode())

    def read_response(self):
        return self.ser.readline().decode().strip()

    def illuminate(self, status=False):
        pass

    def select_illumination(self, led_number, intensity):
        pass



class TemikaIlluminationController(Illumination):


    def __init__(self):
        from hardware import TemikaComms
        self.my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes
        self.temika_comms = TemikaComms()
        self.logger = Logger()
        self.name = self.my_app_config.get("temika_name")

    def __bitmask_to_hex(self, bitmask_str):
        # Convert the bitmask string (binary) into an integer
        num = int(bitmask_str, 2)
        # Format it as a 2-byte hex string with a "0x" prefix, padded with leading zeros
        hex_str = f"0x{num:02x}"
        return hex_str

    def illumination_enable(self, led_bitmask):
        hex_str = self.__bitmask_to_hex(led_bitmask)
        command = f"<{self.name}>"
        command += "<illumination>"
        command += f"<enable>{hex_str}</enable>"
        command += "</illumination>"
        command += f"</{self.name}>"
        self.temika_comms.send_command(command)

    def illumination_setup(self, led_number, intensity):
        command = f"<{self.name}>"
        command += "<illumination>"
        command += f"<value number=\"{led_number}\">{intensity}</value>"
        command += "</illumination>"
        command += f"</{self.name}>"
        self.temika_comms.send_command(command)
        self.logger.info(f"Selected illumination {led_number} with intensity {intensity}")
        return True


class IlluminationControllerFactory:

    @staticmethod
    def create_illumination_controller():
        logger = Logger()
        my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes
        illumination_type = my_app_config.get("illumination_type")
        if illumination_type == "ThorLabs":
            return ThorLabsIlluminationController()
        elif illumination_type == "Temika":
            return TemikaIlluminationController()
        else:
            logger.error(f"Unknown illumination controller type: {illumination_type}")
            return None
