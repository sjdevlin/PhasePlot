from hardware import AnnealerController
from services import Logger, AppConfig, DatabaseService
from models import Annealer, AnnealerWell
from time import sleep
from datetime import datetime

class AnnealerConfigOperator():
    def __init__(self, db, progress_callback=None):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.progress_callback = progress_callback

    def check_annealer(self):
        #establish connection
        self.annealer_controller = AnnealerController()
        serial_number = None
        connection_status = self.annealer_controller.connect()

        if connection_status:
            serial_number = self.annealer_controller.get_serial_number()
        else:
            self.logger.error("Annealer connection failed.")
        
        return connection_status, serial_number

    def configure_annealer(self, annealer):

        #get number of wells
        self.annealer = annealer
        self.annealer_controller.zero_all_wells()

        #get sensors
        self.addresses = self.annealer_controller.get_sensors(self.annealer.num_wells) or []
        if not self.addresses:
            self.logger.error("No sensors detected; aborting annealer configuration.")
            if self.progress_callback:
                self.progress_callback([], None, None, "No sensors detected")
            return
        if self.progress_callback:
            self.progress_callback(self.addresses, None, None, "Sensors found")

        #calibrate sensors
        temperature = self.calibrate()
        if temperature is None:
            self.logger.error("Calibration failed; aborting annealer configuration.")
            if self.progress_callback:
                self.progress_callback(None, None, None, "Calibration failed")
            return
        if self.progress_callback:
            self.progress_callback(None, self.calibration_factors, temperature, "Calibration complete")

        #allocate sensors
        self.allocate_sensors()
        if self.progress_callback:
            self.progress_callback(None, None, None, "Allocation Starting")

    def calibrate(self):
        responses = []
        addresses = self.addresses.copy()
        for address in self.addresses:
            temperature = self.annealer_controller.get_temperature_celsius(sensor_address=address) 
            if temperature is not None:
                responses.append(temperature)
            else:
                self.logger.warning(f"Sensor {address} is being removed from calibration due to error.")
                addresses.remove(address) # should ensure response & address list are same length

        if not responses:
            self.logger.error("Calibration failed: no valid temperature responses.")
            return None

        average_response = sum(responses) / len(responses)
        self.calibration_factors = {}

        for address, response in zip(addresses, responses):
            if abs(response - average_response) > 0.5:
                self.logger.warning(f"Calibration warning: response of sensor {address} differs from average by more than 0.5")
            factor = average_response - response
            self.calibration_factors[address] = factor

        self.addresses = addresses # remove the non working sensors from the object list
        self.starting_temperature = average_response
        self.logger.info(f"Calibration complete. Average temperature: {average_response}")

        return average_response 

    def allocate_sensors(self):

        self.heat_intensity = self.app_config.get("max_heat_intensity", 0)
        self.calibration_heating_time = self.app_config.get("calibration_heating_time", 1)
        self.calibration_min_temp_rise = self.app_config.get("calibration_min_temp_rise", 0.1)

        new_annealer = Annealer(
            serial_number=self.annealer.serial_number + 1,
            description=self.annealer.description + f" (configured: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            plate_id=self.annealer.plate_id,
            num_wells=self.annealer.num_wells,
            configured=True,
            number_active_sensors=len(self.addresses)
        )
        #save annealer in order to get a new annealer_id

        self.old_temperatures = {address: self.starting_temperature for address in self.addresses}
        self.new_temperatures = {address: self.starting_temperature for address in self.addresses}

        for well_index in range(self.annealer.num_wells):
            try:
                self.annealer_controller.apply_heat(index=well_index, intensity=self.heat_intensity)        
            except Exception as e:
                self.logger.error(f"Failed to apply heat to well {well_index}: {e}")
                continue 

            sensor_address = self.find_address()
            
            if sensor_address is not None:
                # TODO: calculate row and col using a lookup based on annealer type
                row, col = self._calculate_row_col(well_index)
                new_well = AnnealerWell(
                            sensor_address=sensor_address,
                            calibration_factor=self.calibration_factors[sensor_address],
                            well_index=well_index,
                            well_row=row,
                            well_column=col,
                            active=True,
                        )
                self.addresses.remove(sensor_address)
                self.logger.info(f"Sensor {sensor_address} assigned to well {well_index} (row={row}, col={col})")
            else:
                row, col = self._calculate_row_col(well_index)
                new_well = AnnealerWell(
                            sensor_address="",
                            calibration_factor=0.0,
                            well_index=well_index,
                            well_row=row,
                            well_column=col,
                            active=False,
                        )
                self.logger.info(f"Well {well_index} (row={row}, col={col}) assigned no sensor")
                        
            new_annealer.wells.append(new_well)
            self.annealer_controller.apply_heat(well_index, 0)

        self.db.add_annealer(new_annealer)
        self.annealer_controller.set_serial_number(new_annealer.serial_number)
        self.logger.info(f"Annealer configured with ID: {new_annealer.id}.")

    def _calculate_row_col(self, well_index):
        """Calculate row and column from well index based on annealer type."""
        # TODO: make this more felxible based on different annealer types
        if self.annealer.num_wells == 24:
            row = chr(ord('A') + (well_index // 6))
            column = well_index % 6 + 1
            return row, column
        else:   
            return 0, 0

    def find_address(self):

        self.logger.debug(f"Attempt to find sensor address with sufficient temperature rise.")
        sleep(self.calibration_heating_time)            

        max_temp_change = 0
        max_temp_address = None

        for address in self.addresses:
            self.new_temperatures[address] = self.annealer_controller.get_temperature_celsius(
                address, self.calibration_factors[address]
            )
            if self.new_temperatures[address] is None:
                self.logger.warning(f"Sensor {address} error.")
            else:    
                old_temp = self.old_temperatures[address]
                new_temp = self.new_temperatures[address]

                self.logger.info(f"Sensor {address}: Old:{old_temp:.1f}C, New:{new_temp:.1f}C, Diff:{new_temp - old_temp:.1f}C")

                if (new_temp - old_temp > max_temp_change):
                    max_temp_change = new_temp - old_temp
                    max_temp_address = address

        # Update old temperatures after processing all sensors
        self.old_temperatures.update(self.new_temperatures)

        if max_temp_change > self.calibration_min_temp_rise:
            return max_temp_address
        else:
            self.logger.warning(f"Sensor did not meet the minimum temperature rise of {self.calibration_min_temp_rise}C. Max change: {max_temp_change:.1f}C")
            return None







