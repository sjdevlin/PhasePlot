
from models import Experiment, Sample
from datetime import datetime

#TODO refactor some of this should go into model I think

class ExperimentDetailPresenter():
    def __init__(self, view, home_page, db, experiment_id=None):
        self.home_page = home_page
        self.view = view
        self.db = db
        self.changed = False #TODO do I use this ?
        self.populate_profile_table() 

        if experiment_id is not None:
            self.experiment = self.db.get_experiment_by_id(experiment_id)
            self.status = 'Editing' if self.experiment.anneal_status == 'Not Run' else 'Viewing'
        else:
            self.experiment = Experiment(plate_id=5)
            num_wells_in_plate = self.db.get_plate_by_id(self.experiment.plate_id).num_wells
            self.experiment.sample = []
            self.status = 'New'  # maybe editing will also work here - but we'll wait and see
            self.experiment.description = 'Enter Description'
            self.experiment.notes = 'Enter Notes'
            self.experiment.anneal_status = 'Not Run'


        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)
#        self.wells = self.db.get_wells_by_plate_id(self.experiment.plate_id)
        self.selected_well_index = None

        self.view.populate_experiment_metadata(self.experiment.description, self.experiment.notes, self.experiment.anneal_status) # add "status" e.g. viewing to this
        self.display_plate()

        self.view.assign_button.configure(command=self.assign_profile)
        self.view.clear_button.configure(command=self.clear_profile)
        self.view.save_button.configure(command=self.save_experiment)
        self.view.back_button.configure(command=self.back)
        
        self.view.bind_row_selection(self.on_profile_selected) 


    def populate_profile_table(self):
        self.selected_row = None
        self.temperature_profiles = self.db.get_all_profiles()

        # Convert SQLAlchemy objects into dictionaries or tuples
        data = [
            (
                profile.id,
                profile.description,
            )
            for profile in self.temperature_profiles
        ]
        self.view.show_temperature_profiles(data)

    def on_profile_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_row = self.view.get_id_of_selected_row()
        if self.selected_row is not None and self.selected_well_index is not None:
            self.draw_profile_graph(self.selected_row)
            print ("Selected: ", self.selected_row, self.selected_well_index)
            profile_id = next((sample.temperature_profile_id for sample in self.experiment.sample if sample.well_index == self.selected_well_index),None) 
            if profile_id is None:
                self.view.disable_clear_button()
                self.view.enable_assign_button()

    def draw_profile_graph(self, profile_id):
        temperature_profile = self.db.get_profile_by_id(profile_id)

        start_temp = 25
        target_times = []
        target_temperatures = []
        actual_times = []
        actual_temperatures = []
        current_time = 0

        if self.status == 'Viewing':
            sample_obj = next((s for s in self.experiment.sample if s.well_index == self.selected_well_index), None)
            if sample_obj is None:
                return
            result = self.db.get_sample_data_by_id(sample_obj.id)
            for line in result:  # Adjust attribute if the results are stored under a different name
                actual_times.append(line.elapsed_minutes)
                target_times.append(line.elapsed_minutes)
                actual_temperatures.append(line.actual_temperature)
                target_temperatures.append(line.target_temperature)
        else:
            target_temperatures.append(start_temp)
            target_times.append(0)
            for profile in temperature_profile.detail_line:
                current_time += profile.duration_mins
                target_times.append(current_time)
                target_temperatures.append(profile.temp_end)



        self.view.draw_temperature_detail(target_times, target_temperatures, actual_times, actual_temperatures)


    def on_well_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_well_index = self.view.get_id_of_selected_well(event)
        self.selected_row = self.view.get_id_of_selected_row()
        if self.selected_well_index is not None:
            if self.plate.well[self.selected_well_index].active:
                profile_id = next((sample.temperature_profile_id for sample in self.experiment.sample if sample.well_index == self.selected_well_index),None) 
                self.display_plate()
                if profile_id is not None:
                    self.view.select_profile(profile_id)
                    self.view.disable_assign_button()
                    if self.status != 'viewing':
                        self.view.enable_clear_button() 
                else:
                    if self.selected_row is not None:
                        self.view.enable_assign_button()
                    self.view.disable_clear_button()
            
    def display_plate(self):
        #eventually change this so that only slected wells are updated
        plate_width = self.plate.outline_width
        plate_height = self.plate.outline_height
        offset_x = self.plate.centre_first_well_offset_x
        offset_y = self.plate.centre_first_well_offset_y
        well_diameter = self.plate.well_dimension
        well_spacing_x = self.plate.well_spacing_x
        well_spacing_y = self.plate.well_spacing_y

        # Convert SQLAlchemy objects into dictionaries or tuples
        well_data = []
        for well in self.plate.well:

            sample_index = next((index for index, sample in enumerate(self.experiment.sample) if sample.well_index == well.well_index), None)
            is_selected = False
            well_status = 'inactive'

            if sample_index != None: #don't use true/false since profile might have code zero !!
                well_status = 'assigned'
            elif well.active:
                well_status = 'available'

            if self.selected_well_index == well.well_index:
                is_selected = True

            well_data.append((
                well.well_index,
                well.well_row,
                well.well_col,
                well_status,
                is_selected
            ))

        self.view.show_plate(plate_width, plate_height, offset_x, offset_y,well_spacing_x,well_spacing_y, well_diameter, well_data, self.on_well_selected)

   

    def clear_profile(self):
        well_index = self.selected_well_index
        sample_index = next((index for index, sample in enumerate(self.experiment.sample) if sample.well_index == well_index), None)
        if sample_index is not None:
            self.experiment.sample.pop(sample_index)
        self.view.clear_profile_selection()
        self.view.disable_clear_button()
        self.view.disable_assign_button()
        self.view.enable_save_button()
        self.display_plate()

    def save_experiment(self):
        self.experiment.description = self.view.description_entry.get()
        self.experiment.notes = self.view.notes_entry.get("1.0", "end")
        if self.status == 'New':
            self.experiment.creation_date_time = datetime.now()
            self.experiment.anneal_status = 'Not Run'
            if self.db.add_experiment(self.experiment):
                self.view.display_info("Experiment saved successfully.")
            else:
                self.view.display_error("Error updating experiment.")
        else:
            if self.db.update_experiment(self.experiment):
                self.view.display_info("Experiment updated successfully.")
            else:
                self.view.display_error("Error updating experiment.")


    def back(self):
        self.view.close()
        self.home_page.home_frame.pack()  # Show the main view again

