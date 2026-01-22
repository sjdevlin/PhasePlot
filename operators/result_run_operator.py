from hardware import *
from datetime import datetime
from models.results import ResultRunData
from services import Logger, AppConfig, Movie2Tiff, PIDCalculator, pid_calculator
from models import Experiment, Sample, ImageSet, ResultRun, Image
from time import sleep
import random

class ResultRunOperator:
    def __init__(self, experiment, result_set, temperature_profile, db):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.result_set = result_set
        self.experiment = experiment
        self.temperature_profile = temperature_profile
        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)
        self.image_set = self.db.get_image_set_by_id(self.result_set.image_set_id)
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
        self.image_path = self.app_config.get("image_file_directory", "./")

        number_prev_runs_of_exp_set = self.db.get_number_result_runs_by_exp_and_set(self.experiment.id, self.result_set.id)

        KP = self.app_config.get("kp")
        KI = self.app_config.get("ki")
        KD = self.app_config.get("kd")


        self.result_run_id = self.db.add_result_run(ResultRun(
            experiment_id=self.experiment.id,
            result_set_id=self.result_set.id,            
            description= (f"{self.experiment.description}: Result Run: {number_prev_runs_of_exp_set + 1}"),
            notes=(f"Result Set: {self.image_set.description}"),
            start_date_time= datetime.now(),
            status="Not Started",
            number_of_samples=len(self.experiment.sample),
            pid_kp = KP,
            pid_ki = KI,
            pid_kd = KD
        ))

        self.result_run = self.db.get_result_run_by_id(self.result_run_id)
        self.result_run.time_at_temperature = {}
        self.result_run.target_temperature = {} # this needs to be in result run so it can be shared between threads

        for sample in self.experiment.sample:
            self.result_run.time_at_temperature[sample.id] = 0
            self.result_run.target_temperature[sample.id] = self.temperature_profile.start_temp


    def run(self):
        print("DEBUG: run() method started", flush=True)
        from views import LogView
        import tkinter as tk
        
        # Note: User interaction prompts moved to presenter to run on main thread
        # This method should run on a worker thread without blocking tkinter
        
        self.logger.info("Camera trigger enabled")
        self.camera_controller.set_trigger()  # Ensure trigger mode is on

        first_well_row = self.experiment.sample[0].well_row
        first_well_column = self.experiment.sample[0].well_column
        
        stored_z_height = self.plate.get_well_z_height(first_well_row, first_well_column)


       # First create the image run in the database, then retrieve it.  
        # This ensures that the image run is created before we start the imaging process.

        # Iterate through each sample in the experiment

        #home the stage before starting the imaging run
        #self._home_stage()
        self.focus_controller.autofocus(False)  # Ensure autofocus is off before homing
        self.focus_position = self.focus_controller.get_z()  # Get the current Z position as a reference for focus
        self.move_position = self.focus_position - 100  # Move Z position for the next major move
        self.focus_controller.move_z(self.move_position)  #TODO change to config value

        exp_complete = False

        while not exp_complete:

            for sample in self.experiment.sample:

                while (self.result_run.time_at_temperature[sample.id] < self.temperature_profile.soak_time_seconds):
                    sleep (1)  #this blocks the imaging so we dont keep moving all over the place just samples are right temp
                    # Once soak time is reached, proceed to image

                self.logger.info(f"Soak time reached for sample {sample.id}. Proceeding to image.")
                                                                                                                 
                for site_number in range(self.image_set.number_of_sites):

                    movie_stub = f"{self.movie_path}/{self.result_run.id}_{sample.well_row}_{sample.well_column}_{site_number}"
                    image_stub = f"{self.image_path}/{self.result_run.id}_{sample.well_row}_{sample.well_column}_{site_number}"
                    self.camera_controller.set_filename(movie_stub)

                    self._move_stage_to_site(sample, site_number)
                    stored_z_height = self.plate.get_well_z_height(sample.well_row, sample.well_column)
                    self._readjust_focus(stored_z_height)

                    self._take_stack(sample, site_number)
                    movie_filename = f"{movie_stub}{self.app_config.get('movie_extension', '.movie')}"
                    self._process_stack(movie_filename, image_stub, sample, site_number)
                    self._readjust_focus(stored_z_height)

                self.focus_controller.move_z(stored_z_height-100)  # Drop Z for next major move
                self.result_run.target_temperature[sample.id] -= self.temperature_profile.step_size
                self.result_run.time_at_temperature[sample.id] = 0  # Reset time at temperature for 

            exp_complete = True
            for sample in self.experiment.sample:
                if self.result_run.target_temperature[sample.id] >= self.temperature_profile.end_temp:
                    exp_complete = False    

        self.finish_date_time = datetime.now()
        self.status = "Complete"
        self.db.update_result_run(self.result_run)
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

        # Convert well row (letter) and column (1-based index) to zero-based indexes
        row_index = ord(sample.well_row.upper()) - ord('A')
        col_index = sample.well_column - 1

        x = self.plate.centre_first_well_offset_x + (col_index * self.plate.well_spacing_x)
        x = x + (self.plate.well_dimension * random.uniform(-0.15, 0.15))
        y = self.plate.centre_first_well_offset_y + (row_index * self.plate.well_spacing_y)
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

    def _readjust_focus(self, stored_z_height=None):
        """
        Adjust the focus before taking images.
        This method can be extended to include more sophisticated focus adjustments if needed.
        """

        if stored_z_height is not None:
            self.focus_controller.move_z(stored_z_height)  # Return to last focus
        else:
            self.focus_controller.autofocus(True)  # Enable autofocus to get in position then disable it
            self.focus_controller.autofocus(False)  # Disable autofocus after getting in position

        self.focus_position = self.focus_controller.get_z()  # Get the current Z position as a reference for focus

    def _process_stack(self, movie_filename, image_stub, sample, site_number):

        self.logger.info(f"Processing image stack {movie_filename} at site number {site_number} for sample {sample.id}")
        filenames, focus_scores = self.converter.convert(movie_name=movie_filename, file_stub=image_stub)

        for idx, (file, score) in enumerate(zip(filenames, focus_scores)):

            new_image = Image(
                    sample_id=sample.id,
                    result_run_id=self.result_run.id,
                    site_number=site_number,
                    stack_number=idx,  # Sequential stack index
                    dimension_x=getattr(self.camera_controller, "image_dimension_x", 0),
                    dimension_y=getattr(self.camera_controller, "image_dimension_y", 0),
                    file_path=str(file),
                    timestamp=datetime.now(),
                    focus_score=score,  # Focus score calculated from the Movie2Tiff conversion
                    average_droplet_size=0.0,  # Placeholder, to be calculated later
                    standard_deviation_droplet_size=0.0  # Placeholder, to be calculated later
                    )

            self.db.add_result_run_image(new_image)

        self.logger.info(f"Image stack extracted for movie {movie_filename}")


