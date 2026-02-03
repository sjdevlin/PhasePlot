from hardware import AnnealerController
from datetime import datetime
from models.results import ResultRunData
from services import Logger, AppConfig, PIDCalculator
from models import Experiment, Sample, ResultRun, ResultRunData
from time import sleep

class TemperatureOperator:
    def __init__(self, temperature_profile, result_run, db):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.result_run = result_run
        self.temperature_profile = temperature_profile

        self.result_set = self.db.get_result_set_by_id(self.result_run.result_set_id)
        self.experiment = self.db.get_experiment_by_id(self.result_run.experiment_id)

        self.annealer_controller = AnnealerController() # all annealers same so no need for factory here

        if self.annealer_controller.connect():
            self.logger.info("Annealer connected")
            serial_number = self.annealer_controller.get_serial_number()
            self.annealer_prarameters = self.db.get_annealer_by_serial_number(serial_number)
            if not self.annealer_prarameters:
                self.logger.error(f"No annealer parameters found for serial number {serial_number}")
                return
            self.result_run.annealer_id = self.annealer_prarameters.id
        else:
            self.logger.error("Annealer not connected")
            return



    def run(self):

        MAX_INTENSITY = self.app_config.get("max_heat_intensity")

        self.logger.info(f"Started temperature run for experiment {self.experiment.id} with result set {self.result_set.id}")

        pid_calculator = {}
        time_target_temperature_reached = {}
        for sample in self.experiment.sample:
            pid_calculator[sample.id] = PIDCalculator(self.result_run.pid_kp, self.result_run.pid_ki, self.result_run.pid_kd)
            time_target_temperature_reached[sample.id] = datetime.now()
            #remember these are dictionaries keyed by sample.id

        current_time = datetime.now()
        last_poll_time = current_time
        elapsed_seconds = 0
        elapsed_minutes = 0
        interval = 10.0  # Initial interval

        while self.result_run.status == "Running":

            for sample in self.experiment.sample:

                well_row = sample.well_row
                well_column = sample.well_column

                annealer_well = next(
                    (well for well in self.annealer_prarameters.wells
                     if well.well_row == well_row and well.well_column == well_column),
                    None
                )
                sensor_address = annealer_well.sensor_address

                if sensor_address is None:
                    self.logger.error(f"Fatal: No sensor address found for sample {sample.id} in well {well_row}{well_column}")
                    exit(1)
                    
                calibration_offset = annealer_well.calibration_factor
                heater_index = annealer_well.well_index

                current_time = datetime.now()
                # can i get address for this row and well ?
                current_temp = self.annealer_controller.get_temperature_celsius(sensor_address=sensor_address, calibration_factor=calibration_offset)

                if current_temp is None:
                    self.logger.error(f"Failed to read temperature for sample {sample.id} at well {well_row}{well_column}")
                    continue

                self.result_run.actual_temperature[sample.id] = current_temp
                error = self.result_run.target_temperature[sample.id] - current_temp
                if abs(error) > 0.2:  # TODO make config value
                    time_target_temperature_reached[sample.id] = datetime.now()
                    self.result_run.time_at_temperature[sample.id] = 0
                else:
                    self.result_run.time_at_temperature[sample.id] = int((datetime.now() - time_target_temperature_reached[sample.id]).total_seconds())
                    self.logger.info(f"Sample {sample.id} has been at target temperature for {self.result_run.time_at_temperature[sample.id]} seconds")

                pid_proportion = 0
                pid_integral = 0
                pid_derivative = 0

                if error > 1.0:
                    intensity = MAX_INTENSITY
                    pid_calculator[sample.id].reset()
                elif error < -1.0:
                    intensity = 0
                    pid_calculator[sample.id].reset()
                else: 
                    pid = pid_calculator[sample.id]
                    pid_output, pid_proportion, pid_integral, pid_derivative = pid.update(error, interval)
                    intensity = max(0, min(int(pid_output), MAX_INTENSITY))

                # Apply the computed heating intensity to the well

                
                self.annealer_controller.apply_heat( index=heater_index, intensity=intensity)
                
                elapsed_seconds = int((current_time - self.result_run.start_date_time).total_seconds())
                elapsed_minutes = int(elapsed_seconds / 60)

                new_sample_data = ResultRunData(
                        sample_id=sample.id,
                        result_run_id=self.result_run.id,
                        reading_date_time=current_time,
                        target_temperature=self.result_run.target_temperature[sample.id],
                        elapsed_minutes=elapsed_minutes,
                        actual_temperature=current_temp,
                        heat_applied=intensity
                    )

                self.db.add_result_run_data(new_sample_data)
                self.logger.info(f"Sample {sample.id} - Target: {self.result_run.target_temperature[sample.id]}, Actual: {current_temp}, Intensity: {intensity} P({pid_proportion})I({pid_integral}) ")   
#TODO: check logic of time here.  INterval based on whole cycle - but current time being updated each time OK?
            interval = (current_time - last_poll_time).total_seconds()
            last_poll_time = current_time








