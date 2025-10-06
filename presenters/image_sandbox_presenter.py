from hardware import StageControllerFactory, CameraControllerFactory, IlluminationControllerFactory, FocusControllerFactory
from services import Logger, AppConfig, DatabaseService

class ImageSandboxPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()

        # Instantiate and connect the controllers for imaging.
        camera_type = AppConfig().get("camera_type")
        self.camera_controller = CameraControllerFactory.create_camera_controller(camera_type)

        self.stage_controller = StageControllerFactory.create_stage_controller()
        self.illumination_controller = IlluminationControllerFactory.create_illumination_controller()
        self.focus_controller = FocusControllerFactory.create_focus_controller()


        self.view.apply_illumination_button.configure(command=self.apply_illumination)
        self.view.record_image_button.configure(command=self.record_image)
#        self.view.autofocus_button.configure(command=self.autofocus)
        self.view.move_stage_button.configure(command=self.move_stage)


    def apply_illumination(self):
        try:
            led_number = int(self.view.led_number_entry.get())
            led_intensity = float(self.view.led_intensity_entry.get())
        except ValueError:
            self.logger.error("Invalid number or intensity value entered.")
            self.view.display_error("Please enter valid integer & float")
            return
        led_bitmask = self.view.led_bitmask_entry.get()
        self.illumination_controller.illumination_setup(led_number,led_intensity)
        self.illumination_controller.illumination_enable(led_bitmask)
        self.logger.info(f"Applied illumination to LED {led_number} with intensity {led_intensity}")

    def move_stage(self):
        try:
            x_pos = float(self.view.position_entry.get())
            speed = float(self.view.speed_entry.get())
        except ValueError:
            self.logger.error("Invalid x pos or speed value entered.")
            self.view.display_error("Please enter valid integers")
            return
        self.stage_controller.move(position=x_pos, axis="x", speed=speed)
        self.logger.info(f"Moved stage to position {x_pos} with speed {speed}")


    def record_image(self):
        try:
            file_name = self.view.file_name_entry.get()
            shutter_speed = float(self.view.shutter_speed_entry.get())
        except ValueError:
            self.logger.error("Invalid shutter speed value entered.")
            self.view.display_error("Please enter valid integers")
            return
        self.camera_controller.set_shutter_speed(shutter_speed)
        self.camera_controller.set_filename(file_name)
        self.camera_controller.capture_image()
        self.logger.info("Image captured")
#        self.view.display_message("Image captured successfully")


    def autofocus(self):
        try:
            status = self.view.autofocus_status.get()
            if status == "ON":
                self.focus_controller.autofocus(True)
            else:
                self.focus_controller.autofocus(False)
            self.logger.info(f"Autofocus set to {status}")
        except Exception as e:
            self.logger.error(f"Error setting autofocus: {e}")
            self.view.display_error("Failed to set autofocus")

