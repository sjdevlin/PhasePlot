from hardware import *
from datetime import datetime
from hardware.annealer_controller import AnnealerController
from models.results import ResultRunData
from services import Logger, AppConfig, Movie2Tiff, PIDCalculator, pid_calculator
from models import Experiment, Sample, ImageSet, ResultRun, ResultRunImage
from time import sleep
import random

class ResultRunOperator:
    def __init__(self, experiment, result_set, db):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.result_set = result_set
        self.experiment = experiment
        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)
        self.image_set = self.db.get_image_set_by_id(self.result_set.image_set_id)
        self.temperature_profile = self.db.get_temperature_profile_by_id(self.result_set.temperature_profile_id)
        self.annealer = self.db.get_annealer_by_id(self.result_set.annealer_id)
        self.converter = Movie2Tiff()  # Initialize the Movie2Tiff converter

        annealer_parameters = self.db.get_annealer_by_id(self.annealer.id)
        self.annealer_controller = AnnealerController(annealer_parameters=annealer_parameters) # all annealers same so no need for factory here

        camera_type = self.app_config.get("camera_type", "default_camera") #change to do this in the camera initialization
        self.camera_controller = CameraControllerFactory.create_camera_controller(camera_type)
        self.stage_controller = StageControllerFactory.create_stage_controller()
        self.illumination_controller = IlluminationControllerFactory.create_illumination_controller()
        self.focus_controller = FocusControllerFactory.create_focus_controller()

        self.illumination_controller.illumination_setup(self.app_config.get("illumination_led_number", 1),
                                                         self.app_config.get("illumination_intensity", 0.3))
        self.camera_controller.set_shutter_speed(self.app_config.get("shutter_speed", 10000))
        self.movie_path = self.app_config.get("movie_file_directory", "./")
        self.MAX_INTENSITY = self.app_config.get("max_heat_intensity")






    def run(self):
        from views import LogView
        from tkinter import messagebox

        # check the annealer is connected
        if self.annealer_controller.connect():
            self.logger.info("Annealer connected")
        else:
            self.logger.error("Annealer not connected")
            return


        # ask user to ensure that image is in focus before starting the run
        # create window that pauses the run until the user clicks "Continue"
        # save the z value i focus for future reference       
        messagebox.showinfo("Important", "Have you reset the X and Y co-ords to the origin?")  
        messagebox.showinfo("Focus Check", "Please go to first well and ensure that the image is in focus and enable autofocus before starting the run.")  
        self.focus_position = self.focus_controller.get_z()  # Get the current Z position as a reference for focus
        first_well_row = self.experiment.sample[0].well_row
        first_well_column = self.experiment.sample[0].well_column
        first_well_index = self.plate.get_well_index(first_well_row, first_well_column)
        stored_z_height = first_well_index.z_height

        difference = abs(self.focus_position - stored_z_height)

        if difference < 5.0: #TODO make config value
            self.logger.info("Stored Z height looks good, starting the run.")
        else:
            self.logger.error("Z Height difference too large. Please refocus and try again.")
            return

        self.move_position = self.focus_position - 50  # Move Z position for the next major move

       # First create the image run in the database, then retrieve it.  
        # This ensures that the image run is created before we start the imaging process.

        number_prev_runs_of_exp_set = self.db.get_number_result_runs_by_exp_and_set(self.experiment.id, self.result_set_set.id)

        self.result_run_id = self.db.add_result_run(ResultRun(
            experiment_id=self.experiment.id,
            result_set_id=self.result_set.id,
            description= (f"{self.experiment.description}: Result Run: {number_prev_runs_of_exp_set + 1}"),
            notes=(f"Result Set: {self.image_set.description}"),
            image_run_start_date_time= datetime.now(),
            image_run_status="Not Started",
            number_of_samples=len(self.experiment.sample)
        ))

        self.result_run = self.db.get_result_run_by_id(self.result_run_id)

        # Iterate through each sample in the experiment
        self.logger.info(f"Started result run for experiment {self.experiment.id} with result set {self.result_set.id}")

        KP = self.app_config.get("kp")
        KI = self.app_config.get("ki")
        KD = self.app_config.get("kd")

        self.pid_kp = KP
        self.pid_ki = KI
        self.pid_kd = KD

        pid_controllers = {}
        target_temperature = {}
        time_target_temperature_reached = {}
        for sample in self.experiment.sample:
            pid_controllers[sample.id] = PIDCalculator(KP, KI, KD)
            target_temperature[sample.id] = self.temperature_profile.get_start_temperature()
            time_target_temperature_reached[sample.id] = datetime.now()
            #remember these are dictionaries keyed by sample.id

        #home the stage before starting the imaging run
        #self._home_stage()
        self.focus_controller.autofocus(False)  # Ensure autofocus is off before homing
        self.focus_controller.move_z(self.move_position)  #TODO change to config value

        exp_complete = False
        while not exp_complete:

            for sample in self.experiment.sample:

                temperature_in_range = self.control_temperature(sample, pid_controllers[sample.id], target_temperature[sample.id])

                if not temperature_in_range:
                    time_target_temperature_reached[sample.id] = datetime.now()
                else:
                    elapsed_time_at_target_temperature = (datetime.now() - time_target_temperature_reached[sample.id]).total_seconds()

                if elapsed_time_at_target_temperature > self.result_set.temperature_profile.soak_time_seconds:
                    # Once temperature is in range, proceed to image
                    self.logger.info(f"Temperature in range for sample {sample.id}. Proceeding to image.")
                    target_temperature[sample.id] = self.temperature_profile.get_next_temperature(target_temperature[sample.id])


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


    def set_and_hold_start_temperature(self):
        """
        Set and hold the start temperature for the annealer.
        """
        target_temp = self.temperature_profile.get_start_temperature()
        self.logger.info(f"Setting annealer to start temperature: {start_temp}°C")
        last_poll_time = datetime.now()  
        some_wells_not_at_temp = True

        while some_wells_not_at_temp:

            some_wells_not_at_temp = False

            for sample in self.experiment.sample:

                well_row = sample.well_row
                well_column = sample.well_column
                well_index = (well_row - 1) * self.annealer.num_columns + (well_column - 1) # done differently elsewhere why?
                address = self.annealer.well[well_index].sensor_address
                calibration_factor = self.annealer.well[well_index].calibration_factor
                current_temp = self.annealer.get_temperature_celsius(address)

                error = target_temp - current_temp
                if abs(error) > 0.5:  # TODO make config value
                    some_wells_not_at_temp = True

                pid_proportion = 0
                pid_integral = 0
                pid_derivative = 0

                if error > 1.0:
                    intensity = self.MAX_INTENSITY
                    pid_calculator[sample.id].reset()
                elif error < -1.0:
                    intensity = 0
                    pid_calculator[sample.id].reset()
                else: 
                    pid = pid_calculator[sample.id]
                    pid_output, pid_proportion, pid_integral, pid_derivative = pid.update(error, interval)
                    intensity = max(0, min(int(pid_output), self.MAX_INTENSITY))

                # Apply the computed heating intensity to the well
                self.plate_controller.apply_heat(well_index, intensity)
                
                elapsed_seconds = int((current_time - self.experiment.anneal_start_date_time).total_seconds())
                elapsed_minutes = int(elapsed_seconds / 60)

                new_sample_data = ResultRunData(
                        sample_id=sample.id,
                        result_run_id=self.result_run.id,
                        reading_date_time=current_time,
                        target_temperature=target_temp,
                        elapsed_minutes=elapsed_minutes,
                        actual_temperature=current_temp,
                        heat_applied=intensity
                    )
                



            current_time = datetime.now()
            interval = (current_time - last_poll_time).total_seconds()
            last_poll_time = current_time




        self.logger.info(f"Annealer set to hold at {start_temp}°C")