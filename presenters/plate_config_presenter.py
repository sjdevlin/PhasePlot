from hardware import StageControllerFactory, FocusControllerFactory
from services import Logger, AppConfig, DatabaseService

class PlateConfigPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.stage_controller = StageControllerFactory.create_stage_controller()
        self.focus_controller = FocusControllerFactory.create_focus_controller()

        # Set the on_close callback on the view to free up the serial connection.
        self.view.on_close_callback = self.on_view_close

        self.selected_well_row = None
        self.selected_well_column = None
#        self.display_plate()
        self.view.retrieve_plate_button.configure(command=self.retrieve_plate_details)
#        self.view.next_button.configure(command=self.move_to_next_well)
        self.view.store_button.configure(command=self.store_z_value)


    def on_view_close(self):
        self.logger.info("Plate Config view closed.")

    def retrieve_plate_details(self):
        plate_id_value = int(self.view.id_entry.get())
        self.plate = self.db.get_plate_by_id(plate_id_value)  # Use the entered plate ID.
        if self.plate is None:
            self.view.display_error("Plate not found in database.")
            return
        else:
            self.view.enable_store_button()
#            self.view.enable_next_button()
            self.display_plate()


    def store_z_value(self):
        if self.selected_well_index is not None:
            z_value = self.focus_controller.get_current_z_height()
            self.plate.well[self.selected_well_index].z_height = z_value
            self.db.update_plate(self.plate)
            self.display_plate()
        else:
            self.view.display_error("Please select a well to apply heat to")

    def on_well_selected(self, event):
        self.selected_well_row, self.selected_well_column = self.view.get_row_col_selected_well(event)
        if self.selected_well_row is not None and self.selected_well_column is not None:
            # Find the index of the selected well
            for index, well in enumerate(self.plate.well):
                if well.well_row == self.selected_well_row and well.well_column == self.selected_well_column:
                    self.selected_well_index = index
                    break
            # Move stage to selected well
#            x_pos = self.plate.well[self.selected_well_index].x_position
#            y_pos = self.plate.well[self.selected_well_index].y_position
#            self.stage_controller.move_to_position(x_pos, y_pos)
            # Update Z height display
            z_height = self.plate.well[self.selected_well_index].z_height
            if z_height is not None:
                self.view.z_height.configure(text=f"{z_height:.2f} um")
            self.display_plate()

    def display_plate(self):
        plate_width = self.plate.outline_width
        plate_length = self.plate.outline_length
        offset_x = self.plate.centre_first_well_offset_x
        offset_y = self.plate.centre_first_well_offset_y
        well_diameter = self.plate.well_dimension
        well_spacing_x = self.plate.well_spacing_x
        well_spacing_y = self.plate.well_spacing_y

        well_data = []
        for well in self.plate.well:
            is_selected = (self.selected_well_row == well.well_row and self.selected_well_column == well.well_column)
            well_data.append((well.well_row, well.well_column, is_selected))

        self.view.show_plate(plate_width, plate_length, offset_x, offset_y, well_spacing_x, well_spacing_y, well_diameter, well_data, self.on_well_selected)
