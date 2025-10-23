from tokenize import String
from serial import Serial
from time import sleep
from services import Logger, AppConfig

class PlateController():

    def __init__(self):
        
        self.logger = Logger() # Singleton instance
        my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes

        self.annealer_port = my_app_config.get("annealer_port")
        self.annealer_baudrate = my_app_config.get("annealer_baudrate")
        self.annealer_timeout = my_app_config.get("annealer_timeout")
        self.annealer_serial_delay = my_app_config.get("annealer_serial_delay")
        self.annealer_retries = my_app_config.get("annealer_retries")
        self.annealer_heat = my_app_config.get("annealer_heat")
        self.annealer_get_temp = my_app_config.get("annealer_get_temp")
        self.annealer_get_address = my_app_config.get("annealer_get_address")
        self.annealer_get_serial_number = my_app_config.get("annealer_get_serial_number")
        self.annealer_set_serial_number = my_app_config.get("annealer_set_serial_number")
        self.annealer_zero_all_wells = my_app_config.get("annealer_zero_all_wells")
        self.celsius_multiplier = my_app_config.get("celsius_multiplier")

    def connect(self):
        try:
            self.ser = Serial(self.annealer_port, self.annealer_baudrate, timeout=self.annealer_timeout)
            if self.ser.is_open:
                self.logger.info(f"Connected to plate.")
                self.ser.reset_input_buffer() # Clear input buffer
                return True
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error connecting to plate: {e}")
            return False

    def disconnect(self):
        """Close the serial port properly before closing the window."""
        if self.ser and self.ser.is_open:
            print("Closing Serial Port")
            self.ser.close()
        

    def send_command(self, command):
        self.ser.write((command + '\n').encode())

    def read_response(self):
        return self.ser.readline().decode().strip()

    def get_serial_number(self):
        retries = self.annealer_retries
        while retries > 0:
            self.send_command(self.annealer_get_serial_number)
            sleep(self.annealer_serial_delay)
            response = self.read_response()
            try:
                response_int = int(response)  # Try converting to an integer
                self.logger.info(f"Serial number returned: {response}")
                self.ser.reset_input_buffer() # Clear input buffer
                return response_int
            except ValueError:
                retries -= 1
                self.ser.reset_input_buffer() # Clear input buffer
                self.logger.error(f"Invalid response to request for serial number: {response}")
        else:
            self.logger.error(f"No response from plate from serial number request.")
            return None

    def set_serial_number(self, serial_number):
        retries = self.annealer_retries
        command = f"{self.annealer_set_serial_number} {serial_number}"
        while retries > 0:
            self.send_command(command)
            sleep(self.annealer_serial_delay)
            response = self.read_response()
            if response == str(serial_number):
                self.logger.info(f"Serial number {response} saved to Plate")
                return True
            retries -= 1
            self.logger.error(f"Invalid response from Plate to request to set Serial Number: {response}")
        else:
            self.logger.error(f"No response from plate trying to set serial number {self.well_index}.")
            return None


    def get_sensors(self, num_wells):
        retries = self.annealer_retries
        while retries > 0:
            self.send_command(self.annealer_get_address)
            sleep(self.annealer_serial_delay)
            response = self.read_response()
            addresses = response.split('*')
            addresses = [addr.strip() for addr in addresses if addr.strip()]
            if len(addresses) == num_wells:
                self.addresses = addresses
                self.logger.info(f"Addresses found for all wells")
                break
            retries -= 1
        else:
            self.logger.info(f"Failed to get all addresses.  Found {len(addresses)} out of {num_wells}.")
            self.logger.error(f"Failed to get all addresses.  Found {len(addresses)} out of {num_wells}.")
            return addresses

    def get_temperature_celsius(self, address, calibration_factor=1):
        retries = self.annealer_retries

        while retries > 0:
            self.send_command(f"{self.annealer_get_temp} {address}")
            sleep(self.annealer_serial_delay)
            response = self.read_response()

            if response is None:  # If read_response() times out or returns nothing
                self.logger.warning(f"Timeout from sensor {address}, retrying...")
                retries -= 1
                continue  # Retry

            try:
                response_int = int(response)  # Try converting to an integer
                float_temperture = (float(response_int) + calibration_factor) * self.celsius_multiplier 
#                self.logger.info(f"Sensor {address} returned temperature: {float_temperture}")
                self.ser.reset_output_buffer() # Clear output buffer
                self.ser.reset_input_buffer() # Clear input buffer
                return float_temperture
            except ValueError:
                retries -= 1
                self.ser.reset_input_buffer() # Clear input buffer
                self.ser.reset_output_buffer() # Clear output buffer
                self.logger.warning(f"Temperature Sensor Error from Plate: {response}")


        else:
            self.logger.error(f"Too many errors from sensor {address}.")
            return None
        

        
    def apply_heat(self, index, intensity):
        command = self.annealer_heat + " " + str(index) + " " + str(intensity)
        retries = self.annealer_retries
        while retries > 0:
            self.send_command(command)
            sleep(self.annealer_serial_delay)
            response = self.read_response()
            if response == command:
                self.logger.info(f"Applied {intensity} heat to well {index}")
                self.ser.reset_input_buffer() # Clear input buffer
                self.ser.reset_output_buffer() # Clear output buffer
                return True
            self.ser.reset_input_buffer() # Clear input buffer
            self.ser.reset_output_buffer() # Clear output buffer
            retries -= 1
            self.logger.warning(f"Invalid Response from Annealer: {response}")
        else:
            self.logger.error(f"No response to heat command from well {index}.")
            return None


    def zero_all_wells(self):
        command = "A"
        retries = self.annealer_retries
        while retries > 0:
            self.send_command(command)
            sleep(self.annealer_serial_delay)
            response = self.read_response()
            if response == command:
                self.logger.info(f"Switched off all wells")
                self.ser.reset_input_buffer() # Clear input buffer
                self.ser.reset_output_buffer() # Clear output buffer
                return True
            retries -= 1
            self.logger.warning(f"Invalid Response from Annealer: {response}")
        else:
            self.logger.error(f"No response to zero command.")
            return None

