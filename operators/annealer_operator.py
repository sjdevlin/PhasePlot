from hardware import AnnealerController
from services import Logger, AppConfig, DatabaseService
from models import Annealer, AnnealerWell
from time import sleep

class AnnealerOperator():
    def __init__(self, db, progress_callback=None):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.progress_callback = progress_callback

    def check_annealer(self):
        #establish connection
        self.annealer_controller = AnnealerController()
        connection_status = self.annealer_controller.connect()

        if connection_status:
            serial_number = self.annealer_controller.get_serial_number()
        
        return connection_status, serial_number

    def configure_annealer(self, annealer):

        #get number of wells
        self.annealer = annealer
        self.annealer_controller.zero_all_wells()

        #get sensors
        self.addresses = self.annealer_controller.get_sensors(self.annealer.num_wells)
        self.progress_callback(self.addresses, None, None, "Sensors found")

        #calibrate sensors
        temperature = self.calibrate()
        self.progress_callback(None, self.calibration_factors, temperature, "Calibration complete")

        #allocate sensors
        self.allocate_sensors()
        self.progress_callback(None, None, None, "Allocation Starting")

    def calibrate(self):
        responses = []
        addresses = self.addresses.copy()
        for address in self.addresses:
            temperature = self.annealer_controller.get_temperature_celsius(address) 
            if temperature is not None:
                responses.append(temperature)
            else:
                self.logger.warning(f"Sensor {address} is being removed from calibration due to error.")
                addresses.remove(address) # should ensure response & address list are same length

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

        self.heat_intensity = self.app_config.get("max_heat_intensity")
        self.calibration_heating_time = self.app_config.get("calibration_heating_time")
        self.calibration_min_temp_rise = self.app_config.get("calibration_min_temp_rise")

        new_annealer = Annealer(
            serial_number=self.annealer.serial_number + 1,
            description=self.annealer.description + " (configured: ) + datetime.now().strftime('%Y-%m-%d %H:%M:%S')",
            outline_width=self.annealer.outline_width,
            outline_height=self.annealer.outline_height,
            num_rows=self.annealer.num_rows,
            num_cols=self.annealer.num_cols,
            centre_first_well_offset_x=self.annealer.centre_first_well_offset_x,
            centre_first_well_offset_y=self.annealer.centre_first_well_offset_y,
            well_dimension=self.annealer.well_dimension,
            well_spacing_x=self.annealer.well_spacing_x,
            well_spacing_y=self.annealer.well_spacing_y,
            min_well_volume=self.annealer.min_well_volume,
            max_well_volume=self.annealer.max_well_volume,
            configured=True,
            number_active_sensors=len(self.addresses)
        )
        #save plate in order to get a new plate_id

        self.old_temperatures = {address: self.starting_temperature for address in self.addresses}
        self.new_temperatures = {address: self.starting_temperature for address in self.addresses}  # Moved outside the loop

        for well_index in range(self.annealer.num_wells):
            try:
                self.annealer_controller.apply_heat(well_index, self.heat_intensity)        
            except:
                self.logger.error(f"Failed to apply heat to well {well_index}")
                continue 

            sensor_address = self.find_address()
                                          # Temperature has increased by more than 0.5°C
            if sensor_address is not None :
                new_well = AnnealerWell(
                            sensor_address=sensor_address,
                            calibration_factor=self.calibration_factors[sensor_address],
                            well_index=well_index,
                            active=True,
                            well_row=(well_index) // new_annealer.num_cols,
                            well_col=(well_index) % new_annealer.num_cols
                        )
                        
                self.addresses.remove(sensor_address)

            else:
                new_well = AnnealerWell(
                            sensor_address="",
                            calibration_factor=0.0,
                            active=False,
                            well_index=well_index,
                            well_row=well_index // new_annealer.num_cols,
                            well_col=well_index % new_annealer.num_cols
                        )
                        
            new_annealer.well.append(new_well)
            self.logger.info(f"Sensor {sensor_address} assigned to well {well_index}")
            #self.progress_callback(None, None, None, f"Sensor {sensor_address} assigned to well {well_index}")

            # Shift new temperatures to old for the next iteration
            self.annealer_controller.apply_heat(well_index, 0) # turn off heater        

        self.db.add_annealer(new_annealer)
        #self.progress_callback(None, None, None, f"Annealer configured with ID: {new_annealer.id}.")
        self.annealer_controller.set_serial_number(new_annealer.serial_number)
        self.logger.info(f"Annealer configured with ID: {new_annealer.id}.")


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

                self.old_temperatures.update(self.new_temperatures)

        if max_temp_change > self.calibration_min_temp_rise:
            return max_temp_address
        else:
            self.logger.warning(f"Sensor {max_temp_address} did not meet the minimum temperature rise of {self.calibration_min_temp_rise}C.")
            max_temp_address = None







