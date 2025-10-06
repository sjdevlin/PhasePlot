from hardware import CameraControllerFactory, StageControllerFactory, IlluminationControllerFactory, FocusControllerFactory
from datetime import datetime
from services import Logger, AppConfig, Movie2Tiff
from models import Experiment, Sample, ImageSet, ImageRun, Image
from time import sleep
import random

class ImageRunOperator:
    def __init__(self, experiment, image_set, db):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.image_set = image_set
        self.experiment = experiment
        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)
        self.converter = Movie2Tiff()  # Initialize the Movie2Tiff converter

        camera_type = self.app_config.get("camera_type", "default_camera") #change to do this in the camera initialization
        self.camera_controller = CameraControllerFactory.create_camera_controller(camera_type)
        self.stage_controller = StageControllerFactory.create_stage_controller()
        self.illumination_controller = IlluminationControllerFactory.create_illumination_controller()
        self.focus_controller = FocusControllerFactory.create_focus_controller()

        self.illumination_controller.illumination_setup(self.app_config.get("illumination_led_number", 1),
                                                         self.app_config.get("illumination_intensity", 0.3))
        self.camera_controller.set_shutter_speed(self.app_config.get("shutter_speed", 10000))
        self.movie_path = self.app_config.get("movie_file_directory", "./")



    def run(self):
        from views import LogView
        from tkinter import messagebox

        # ask user to ensure that image is in focus before starting the run
        # create window that pauses the run until the user clicks "Continue"
        # save the z value i focus for future reference       
        messagebox.showinfo("Important", "Have you reset the X and Y co-ords to the origin?")  
        messagebox.showinfo("Focus Check", "Please go to first well and ensure that the image is in focus and enable autofocus before starting the run.")  
        self.focus_position = self.focus_controller.get_z()  # Get the current Z position as a reference for focus
        self.move_position = self.focus_position - 20  # Move Z position for the next major move


       # First create the image run in the database, then retrieve it.  
        # This ensures that the image run is created before we start the imaging process.

        number_prev_runs_of_exp_set = self.db.get_number_image_runs_by_exp_and_set(self.experiment.id, self.image_set.id)

        self.image_run_id = self.db.add_image_run(ImageRun(
            image_set_id=self.image_set.id,
            experiment_id=self.experiment.id,
            description= (f"{self.experiment.description}: Image Run: {number_prev_runs_of_exp_set + 1}"),
            notes=(f"Image Set: {self.image_set.description}"),
            image_run_start_date_time= datetime.now(),
            image_run_status="Not Started",
            number_of_samples=len(self.experiment.sample)
        ))

        self.image_run = self.db.get_image_run_by_id(self.image_run_id)

        # Iterate through each sample in the experiment
        self.logger.info(f"Started imaging run for experiment {self.experiment.id} with image set {self.image_set.id}")

        #home the stage before starting the imaging run
        #self._home_stage()
        self.focus_controller.autofocus(False)  # Ensure autofocus is off before homing
        self.focus_controller.move_z(self.move_position)  #TODO change to config value

        for sample in self.experiment.sample:

            self.logger.info(f"Processing sample {sample.id} at well ({sample.well_row}, {sample.well_column})")                

            for site_number in range(self.image_set.number_of_sites):

                filename = f"{self.movie_path}/{self.image_run.id}_{sample.well_row}_{sample.well_column}_{site_number}"
                self.camera_controller.set_filename(filename)

                self._move_stage_to_site(sample, site_number)
                self._readjust_focus()

                self._take_stack(sample, site_number)
                movie_filename = f"{filename}{self.app_config.get('movie_extension', '.movie')}"
                self._process_stack(movie_filename, sample, site_number)
                self._readjust_focus()

            self.focus_controller.move_z(self.move_position)  # Drop Z for next major move

        self.finish_date_time = datetime.now()
        self.status = "Complete"
        self.db.update_image_run(self.experiment)
        self.logger.info("Imaging complete")

    def _home_stage(self):
        self.logger.info("Homing the stage before starting the imaging run")
        self.focus_controller.autofocus(False)  # Ensure autofocus is off before homing
        self.focus_controller.move_z(self.focus_position - 100)  #TODO change to config value
        self.stage_controller.move(axis="x", position=0, speed=self.app_config.get("max_stage_speed", 1000)) #TODO save config value in object
        self.stage_controller.move(axis="y", position=0, speed=self.app_config.get("max_stage_speed", 1000))
        self.stage_controller.reset(axis="x")
        self.stage_controller.reset(axis="y")
        self.logger.info("Stage homed successfully")


    def _move_stage_to_site(self, sample, site_number):

        x = self.plate.centre_first_well_offset_x + (sample.well_column * self.plate.well_spacing_x)
        x = x + (self.plate.well_dimension * random.uniform(-0.15, 0.15))
        y = self.plate.centre_first_well_offset_y + (sample.well_row * self.plate.well_spacing_y)
        y = y + (self.plate.well_dimension * random.uniform(-0.15, 0.15))

        self.stage_controller.move(position = x, axis= "x", speed="normal")
        self.stage_controller.move(position = y, axis="y", speed="normal")
        sleep(1)  # Allow time for the stage to stabilize
    
    def _take_stack(self, sample, site_number):

        self.logger.info(f"Taking image stack for sample {sample.id} at well ({sample.well_row}, {sample.well_column}), site {site_number}")
        self.camera_controller.start_recording()
        for stack_number in range(self.image_set.stack_size):
            new_z = self.focus_controller.get_z() + self.image_set.stack_step_size
            self.focus_controller.move_z(new_z, speed="normal")  # Move to the new Z position for the stack
            self.camera_controller.capture_image()
        self.camera_controller.stop_recording()

    def _readjust_focus(self):
        """
        Adjust the focus before taking images.
        This method can be extended to include more sophisticated focus adjustments if needed.
        """
        self.focus_controller.move_z(self.focus_position)  # Return to last focus
        self.focus_controller.autofocus(True)  # Enable autofocus to get in position then disable it
        self.focus_controller.autofocus(False)  # Disable autofocus after getting in position
        self.focus_position = self.focus_controller.get_z()  # Get the current Z position as a reference for focus

    def _process_stack(self, movie_filename, sample, site_number):

        self.logger.info(f"Processing image stack {movie_filename} at site number {site_number} for sample {sample.id}")
        filenames, focus_scores = self.converter.convert(movie_name = movie_filename)

        for file, score in zip(filenames, focus_scores):

            new_image = Image(
                    sample_id=sample.id,
                    image_run_id=self.image_run.id,
                    image_site_number=site_number,
                    image_stack_number=focus_scores.index(score),  # Use the index of the score as the stack ID
                    image_dimension_x=self.camera_controller.image_dimension_x,
                    image_dimension_y=self.camera_controller.image_dimension_y,
                    image_file_path=str(file),
                    image_timestamp=datetime.now(),
                    image_focus_score=score,  # Focus score calculated from the Movie2Tiff conversion
                    average_droplet_size=0.0,  # Placeholder, to be calculated later
                    standard_deviation_droplet_size=0.0  # Placeholder, to be calculated later
                    )

                # Save the image to the database
            self.db.add_image(new_image)

        self.logger.info(f"Image stack extracted for movie {movie_filename}")
