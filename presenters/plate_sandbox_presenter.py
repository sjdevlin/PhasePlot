from hardware import PlateController
from services import Logger, AppConfig, DatabaseService

class PlateSandboxPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()

        # Instantiate and connect the PlateController.
        self.plate_controller = PlateController()
        connection_status = self.plate_controller.connect()

        # Set the on_close callback on the view to free up the serial connection.
        self.view.on_close_callback = self.on_view_close

        if connection_status:
            serial_number = self.plate_controller.get_serial_number()
            if serial_number is not None and serial_number > 0:
                self.logger.info(f"Connected to plate {serial_number}")
                self.plate = self.db.get_plate_by_serial_number(serial_number)
                if self.plate is not None:
                    self.plate_controller.zero_all_wells()
                    self.logger.info(f"Plate found in database with ID: {self.plate.id}")
            else:
                self.logger.error("Failed to connect to plate")
                self.view.display_error("Failed to connect to plate")

            self.selected_well_index = None
            self.display_plate()
            self.view.apply_button.configure(command=self.apply_heat)

    def on_view_close(self):
        """Callback invoked when the sandbox view window is closed.
        Disconnects the serial connection to free up resources."""
        self.logger.info("Sandbox view closed. Disconnecting from plate.")
        self.plate_controller.disconnect()

    def apply_heat(self):
        if self.selected_well_index is not None:
            try:
                heat_value = int(self.view.heat_entry.get())
            except ValueError:
                self.logger.error("Invalid heat value entered.")
                self.view.display_error("Please enter a valid integer heat value.")
                return
            self.plate_controller.apply_heat(self.selected_well_index, heat_value)
            self.display_plate()
        else:
            self.view.display_error("Please select a well to apply heat to")

    def on_well_selected(self, event):
        self.selected_well_index = self.view.get_id_of_selected_well(event)
        if self.selected_well_index is not None and self.plate.well[self.selected_well_index].active:
            temperature = self.plate_controller.get_temperature_celsius(
                self.plate.well[self.selected_well_index].sensor_address, 
                self.plate.well[self.selected_well_index].calibration_factor
            )
            if temperature is not None:
                self.view.well_temperature_value.configure(text=f"{temperature:.2f}°C")
            self.display_plate()

    def display_plate(self):
        plate_width = self.plate.outline_width
        plate_height = self.plate.outline_height
        offset_x = self.plate.centre_first_well_offset_x
        offset_y = self.plate.centre_first_well_offset_y
        well_diameter = self.plate.well_dimension
        well_spacing_x = self.plate.well_spacing_x
        well_spacing_y = self.plate.well_spacing_y

        well_data = []
        for well in self.plate.well:
            well_status = "Active" if well.active else "Inactive"
            is_selected = (self.selected_well_index == well.well_index)
            well_data.append((well.well_index, well.well_row, well.well_col, well_status, is_selected))

        self.view.show_plate(plate_width, plate_height, offset_x, offset_y, well_spacing_x, well_spacing_y, well_diameter, well_data, self.on_well_selected)
