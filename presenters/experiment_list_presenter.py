from models import Experiment, Sample, ResultSet, ImageSet, TemperatureProfile
from datetime import datetime
from operators import ExperimentOperator, ResultRunOperator, TemperatureOperator
import copy



class ExperimentListPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.view.exp_bind_row_selection(self.on_exp_row_selected)
        self.view.rs_bind_row_selection(self.on_rs_row_selected)
        self.view.script_button.configure(command=self.generate_script)
        self.view.delete_button.configure(command=self.delete_experiment)
        self.view.copy_button.configure(command=self.copy_experiment)
        self.view.run_button.configure(command=self.run_experiment)
        self.selected_exp_row = None
        self.selected_rs_row = None
        self.refresh_view()


    def on_exp_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_exp_row = self.view.get_id_of_selected_exp_row()
        if self.selected_exp_row:
            self.view.enable_copy_button()
            self.view.enable_delete_button()
            self.view.enable_script_button()
            if self.selected_rs_row:
                self.view.enable_run_button()

    def on_rs_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_rs_row = self.view.get_id_of_selected_rs_row()
        if self.selected_exp_row:
            self.view.enable_run_button()


    def refresh_view(self):
#        self.selected_row = None
        experiments = self.db.get_all_experiments()
        result_sets = self.db.get_all_result_sets()

        # Convert SQLAlchemy objects into dictionaries or tuples
        data = [
            (
            exp.id,
            exp.description,
            exp.plate_id,
            exp.creation_date_time.strftime('%Y-%m-%d %H:%M:%S') if exp.creation_date_time else "",
            len(exp.sample) )
            for exp in experiments
        ]
        self.view.show_experiments(data)

        data = []
        for rss in result_sets:
            temp_profile = self.db.get_temperature_profile_by_id(rss.temperature_profile_id)
            image_set = self.db.get_image_set_by_id(rss.image_set_id)
            data.append((
                rss.id,
                rss.description,
                image_set.lens,
                str(temp_profile.start_temp) + " - " + str(temp_profile.end_temp),
                temp_profile.step_size,
                image_set.stack_size
            ))

        self.view.show_result_sets(data)

        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.view.disable_script_button()

    def copy_experiment(self):
        old_experiment = self.db.get_experiment_by_id(self.selected_exp_row)
        new_experiment = Experiment(plate_id = old_experiment.plate_id)
        new_experiment.description = f"{old_experiment.description} (copy)"
        new_experiment.notes = f"**copied from experiment: {old_experiment.id} ** \n{old_experiment.notes}"
        new_experiment.status = "Not Run"
        new_experiment.creation_date_time = datetime.now()
        new_experiment.liquid_protocol_id = old_experiment.liquid_protocol_id  # Copy the protocol reference
        new_experiment.sample = [Sample(experiment_id=new_experiment.id, 
                                        well_row = s.well_row, 
                                        well_column = s.well_column,
                                        ns_concentration = s.ns_concentration
                                        ) for s in old_experiment.sample]

        self.db.add_experiment(new_experiment)
        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.view.disable_script_button()
        self.refresh_view()


    def delete_experiment(self):
        self.db.delete_experiment(self.selected_exp_row)
        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.refresh_view()

    def run_experiment(self):
        from views import LogView
        import threading
        from tkinter import messagebox

        result_set = self.db.get_result_set_by_id(self.selected_rs_row)
        experiment = self.db.get_experiment_by_id(self.selected_exp_row)
        temperature_profile = self.db.get_temperature_profile_by_id(result_set.temperature_profile_id)

        # Show user prompts on main thread before starting worker threads
        messagebox.showinfo("Important", "Have you reset the X and Y co-ords to the origin?")  
        messagebox.showinfo("Focus Check", "Please go to first well and ensure that the image is in focus and enable autofocus before starting the run.")  
        
        # Create shared lock for thread-safe dictionary access
        shared_lock = threading.Lock()
        
        #start camera with trigger off and then on when imaging starts
        result_run_operator = ResultRunOperator(experiment, result_set, temperature_profile, self.db)
        result_run_operator.shared_lock = shared_lock
        
        temperature_operator = TemperatureOperator(
            temperature_profile, 
            result_run_operator.result_run, 
            self.db,
            result_run_operator.time_at_temperature,
            result_run_operator.actual_temperature,
            result_run_operator.target_temperature,
            shared_lock
        )
        
        # Start threads as non-daemon so they complete their work
        result_thread = threading.Thread(target=result_run_operator.run, daemon=False)
        result_thread.start()

        temperature_thread = threading.Thread(target=temperature_operator.run, daemon=False)
        temperature_thread.start()


    def generate_script(self):
        from services import DatabaseService, LiquidHandler
        from tkinter import messagebox
        # Generate the script file for the selected experiment
        if self.selected_exp_row:
            exp = self.db.get_experiment_by_id(self.selected_exp_row)
            if exp:
                script_generator = LiquidHandler(experiment=exp, db_service=self.db)
                script_path = script_generator.generate()
                messagebox.showinfo("Success",f"Script generated at: {script_path}")
                exp.status = "Script Generated"
                self.db.update_experiment(exp)
                self.refresh_view()