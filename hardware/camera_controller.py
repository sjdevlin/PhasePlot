from services import Logger, AppConfig
from abc import ABC, abstractmethod
from serial import Serial
from time import sleep

class BaseCamera(ABC):
    """Abstract base class defining the interface for all cameras."""

    def __init__(self):
        
        self.logger = Logger() # Singleton instance
        self.app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes

    @abstractmethod
    def set_shutter_speed(self, speed):
        pass

    @abstractmethod
    def capture_image(self):
        """Takes an image and returns the image data"""
        pass

class CameraControllerFactory:

    @staticmethod
    def create_camera_controller(camera_type=None):#TODO put getting camera_type back here
        if camera_type == "IDS":
#            return IdsCameraAdapter() 
            pass
        elif camera_type == "FLIR":
            return FlirCameraAdapter()
        else:
            raise ValueError(f"Unsupported camera manufacturer: {camera_type}")

"""class IdsCameraAdapter(BaseCamera):

    from pyueye import ueye
    #Adapter for IDS cameras using their SDK

    def _initialize_ids_sdk(self):
        h_cam = ueye.HIDS(0)
        ret = ueye.is_InitCamera(h_cam, None)
        if ret != ueye.IS_SUCCESS:
            return h_cam

        if ret != ueye.IS_SUCCESS:
            pass #TODO: Handle error

    def set_shutter_speed(self, speed):
        print(f"Setting Sony {self.model} shutter speed to {speed}")

    def set_iso(self, iso):
        print(f"Setting Sony {self.model} ISO to {iso}")

    def set_gain(self, gain):
        print(f"Setting Sony {self.model} gain to {gain}")

    def capture_image(self):
        print(f"Capturing image with Sony {self.model}")
        return f"Image from {self.model}"


    def send_command(self, command):
        self.ser.write((command + '\n').encode())

    def read_response(self):
        return self.ser.readline().decode().strip()

"""


class FlirCameraAdapter(BaseCamera):


    def __init__(self):
        from hardware import TemikaComms
        super().__init__()
        # Add any Flir-specific initialization here
        self.temika_comms = TemikaComms()
        self.logger.info("TemikaCameraAdapter initialized.")
        self.camera_name = self.app_config.get("camera_name")
        self.image_dimension_x = self.app_config.get("image_dimension_x", 1920)  # Default to 1920 if not set
        self.image_dimension_y = self.app_config.get("image_dimension_y", 1080)
        # permanent camera settings
        command = f"<camera name=\"{self.camera_name}\">"
        command += "<genicam>"
        command += "<boolean feature=\"AcquisitionFrameRateEnable\">ON</boolean>"
        command += "<enumeration feature=\"AcquisitionMode\">Continuous</enumeration>"
        command += "<enumeration feature=\"TriggerMode\">On</enumeration>"
        command += "<enumeration feature=\"TriggerSource\">Software</enumeration>"
        command += "<command feature=\"TriggerSoftware\"></command>"
        command += "</genicam>"
        command += "</camera>"
        self.temika_comms.send_command(command)

    def set_shutter_speed(self, speed):
        command = f"<camera name=\"{self.camera_name}\">"
        command += "<genicam>"
        command += f"<float feature=\"ExposureTime\">{speed}</float>"
        command += "</genicam>"
        command += "</camera>"
        self.temika_comms.send_command(command)

    def set_filename(self, filename):
        command = "<save>"
        command += f"<basename>"
        command += filename
        command += f"</basename>"
        command += "<append>NOTHING</append>"
        command += "</save>"
        self.temika_comms.send_command(command)
        return True

    def set_iso(self, iso):
        pass

    def set_gain(self, gain):
        pass

    def capture_image(self):        
        command = f"<camera name=\"{self.camera_name}\">"
        command += "<send_trigger></send_trigger>"
        command += "</camera>"
        self.temika_comms.send_command(command, wait_for="Done")

    def start_recording(self):        
        command = f"<camera name=\"{self.camera_name}\">"
        command += "<record>ON</record>"
        command += "</camera>\n"
        self.temika_comms.send_command(command)

    def stop_recording(self):        
        command = f"<camera name=\"{self.camera_name}\">"
        command += "<record>OFF</record>"
        command += "</camera>\n"
        self.temika_comms.send_command(command)
