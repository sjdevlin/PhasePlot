from models import Experiment, Sample
from datetime import datetime
from operators import ExperimentOperator, ImageRunOperator
import copy



class ExperimentListPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db
        self.view.exp_bind_row_selection(self.on_exp_row_selected)
        self.view.img_bind_row_selection(self.on_img_row_selected)
        self.view.script_button.configure(command=self.generate_script)
        self.view.delete_button.configure(command=self.delete_experiment)
        self.view.copy_button.configure(command=self.copy_experiment)
        self.view.run_button.configure(command=self.run_experiment)
        self.selected_exp_row = None
        self.selected_img_row = None
        self.refresh_view()


    def on_exp_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_exp_row = self.view.get_id_of_selected_exp_row()
        if self.selected_exp_row:
            self.view.enable_copy_button()
            self.view.enable_delete_button()
            self.view.enable_script_button()
            if self.selected_img_row:
                self.view.enable_run_button()

    def on_img_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_img_row = self.view.get_id_of_selected_img_row()
        if self.selected_exp_row:
            self.view.enable_run_button()


    def refresh_view(self):
#        self.selected_row = None
        experiments = self.db.get_all_experiments()
        image_sets = self.db.get_all_image_sets()

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

        data = [
            (
            ims.id,
            ims.description,
            ims.lens,
            ims.stack_size)
            for ims in image_sets
        ]
        self.view.show_image_sets(data)
        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.view.disable_script_button()


    def copy_experiment(self):
        old_experiment = self.db.get_experiment_by_id(self.selected_exp_row)
        new_experiment = Experiment(plate_id = old_experiment.plate_id)
        new_experiment.description = f"{old_experiment.description} (copy)"
        new_experiment.notes = f"**copied from experiment: {old_experiment.id} ** \n{old_experiment.notes}"
        new_experiment.anneal_status = "Not Run"
        new_experiment.creation_date_time = datetime.now()
        new_experiment.sample = [Sample(experiment_id=new_experiment.id, 
                                        well_row = s.well_row, 
                                        well_column = s.well_column, 
                                        mix_cycles = s.mix_cycles,
                                        mix_speed = s.mix_speed,
                                        mix_volume = s.mix_volume,
                                        mix_height = s.mix_height,
                                        pipette = s.pipette  
                                        ) for s in old_experiment.sample]

        self.db.add_experiment(new_experiment)
        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.view.disable_script_button()
        self.refresh_view()

    def new_experiment(self):
        from views import ExperimentDetailView
        from presenters import ExperimentDetailPresenter
        self.view.home_frame.pack_forget()  # Hide the current view
        experiment_view = ExperimentDetailView(self.view)  # Create a new view
        experiment_presenter = ExperimentDetailPresenter(experiment_view, self.view, self.db)  # Initialize the new presenter with the root widget


    def delete_experiment(self):
        self.db.delete_experiment(self.selected_exp_row)
        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.refresh_view()

    def run_experiment(self):
        from views import LogView
        import threading

        new_image_run = ImageRunOperator(self.db.get_experiment_by_id(self.selected_exp_row),
                                            self.db.get_image_set_by_id(self.selected_img_row),
                                            self.db)
        
        # Since Logger is a singleton, simply create it here.
        from services import Logger
        log_file_path = Logger().log_file
        #TODO consider log window to always access singleton logger and no need to pass the reference
        
        # Create a new window to display the log file in real time.
        log_window = LogView(self.view.root_window, log_file_path)
        
        # Run the annealing process in a separate thread.
        def run_and_refresh():
            new_image_run.run()
            # After completion, schedule a refresh of the view in the main thread.
            self.view.root_window.after(0, self.refresh_view)

#        thread = threading.Thread(target=run_and_refresh, daemon=True)
#        thread.start()
        run_and_refresh() #TODO replace with threading when the GUI is stable


    def generate_script(self):
        from operators import ScriptfileGenerator
        from services import DatabaseService
        from tkinter import messagebox
        # Generate the script file for the selected experiment
        if self.selected_exp_row:
            exp = self.db.get_experiment_by_id(self.selected_exp_row)
            if exp:
                script_generator = ScriptfileGenerator(exp)
                script_path = script_generator.generate()
                messagebox.showinfo("Success",f"Script generated at: {script_path}")
                exp.status = "Script Generated"
                self.db.update_experiment(exp)
                self.refresh_view()