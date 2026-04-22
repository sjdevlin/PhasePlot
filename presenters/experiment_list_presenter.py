from models import Experiment, Sample, ResultSet, ImageSet, TemperatureProfile
from datetime import datetime
from operators import ExperimentOperator, ResultRunOperator, TemperatureOperator
import copy
import threading



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
        self.view.pause_button.configure(command=self.toggle_pause_run)
        self.view.stop_button.configure(command=self.stop_run)
        self.selected_exp_row = None
        self.selected_rs_row = None
        self.run_active = False
        self.run_paused = False
        self.current_result_run_operator = None
        self.current_temperature_operator = None
        self.current_result_thread = None
        self.current_temperature_thread = None
        self.current_stop_event = None
        self.refresh_view()


    def on_exp_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_exp_row = self.view.get_id_of_selected_exp_row()
        if self.selected_exp_row:
            self.view.enable_copy_button()
            self.view.enable_delete_button()
            self.view.enable_script_button()
            self._update_run_button_state()

    def on_rs_row_selected(self, event):
        """This method handles the row selection logic."""
        self.selected_rs_row = self.view.get_id_of_selected_rs_row()
        self._update_run_button_state()

    def _update_run_button_state(self):
        if self.run_active:
            self.view.disable_run_button()
            return
        if self.selected_exp_row and self.selected_rs_row:
            self.view.enable_run_button()
        else:
            self.view.disable_run_button()


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
            if temp_profile is None:
                temp_range = "N/A"
                temp_step = "N/A"
            else:
                temp_range = str(temp_profile.start_temp) + " - " + str(temp_profile.end_temp)
                temp_step = temp_profile.step_size
            data.append((
                rss.id,
                rss.description,
                image_set.lens,
                temp_range,
                temp_step,
                image_set.stack_size
            ))

        self.view.show_result_sets(data)

        self.view.disable_run_button()
        self.view.disable_copy_button()
        self.view.disable_delete_button()
        self.view.disable_script_button()
        self.view.disable_pause_button()
        self.view.disable_stop_button()
        self.view.set_pause_button_text("Pause")

    def copy_experiment(self):
        old_experiment = self.db.get_experiment_by_id(self.selected_exp_row)
        new_experiment = Experiment(plate_id = old_experiment.plate_id)
        new_experiment.description = f"{old_experiment.description} (copy)"
        new_experiment.notes = f"**copied from experiment: {old_experiment.id} ** \n{old_experiment.notes}"
        new_experiment.anneal_status = "Not Run"
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
        from tkinter import messagebox
        if self.run_active:
            messagebox.showinfo("Run Active", "A run is already in progress.")
            return

        result_set = self.db.get_result_set_by_id(self.selected_rs_row)
        experiment = self.db.get_experiment_by_id(self.selected_exp_row)
        if result_set is None or experiment is None:
            messagebox.showerror("Run Error", "Please select a valid experiment and result set.")
            return

        temperature_profile = self.db.get_temperature_profile_by_id(result_set.temperature_profile_id)
        image_set = self.db.get_image_set_by_id(result_set.image_set_id) if result_set else None
        use_autofocus = bool(getattr(image_set, "autofocus", False))

        # Show user prompts on main thread before starting worker threads
        messagebox.showinfo("Important", "Have you reset the X and Y co-ords to the origin?")  
        if use_autofocus:
            messagebox.showinfo(
                "Focus Check",
                "Please go to first well, ensure the image is in focus, and enable autofocus before starting the run.",
            )
        
        # Create shared lock for thread-safe dictionary access
        shared_lock = threading.Lock()
        stop_event = threading.Event()
        error_state = {"shown": False}

        def handle_operator_error(source, error_message):
            if source == "autofocus_pause":
                self.view.root_window.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Autofocus Paused",
                        f"{error_message}\n\nAdjust focus, then press OK. The run will retry autofocus automatically.",
                    ),
                )
                return

            if stop_event is not None:
                stop_event.set()
            if error_state["shown"]:
                return
            error_state["shown"] = True
            self.view.root_window.after(
                0,
                lambda: messagebox.showerror(
                    "Run Error",
                    f"{source.capitalize()} thread failed:\n{error_message}",
                ),
            )

        def request_manual_site_selection(sample, site_number, total_sites):
            dialog_closed = threading.Event()
            dialog_error = {"message": None}

            def show_dialog():
                try:
                    messagebox.showinfo(
                        "Manual Site Selection",
                        (
                            f"Well {sample.well_row}{sample.well_column}, "
                            f"site {site_number + 1} of {total_sites}\n\n"
                            "Move the microscope stage to the desired frame and set the focus offset "
                            "using stepper A.\n\n"
                            "Click OK when the image and focus offset are ready."
                        ),
                    )
                except Exception as exc:
                    dialog_error["message"] = str(exc)
                finally:
                    dialog_closed.set()

            self.view.root_window.after(0, show_dialog)
            while not dialog_closed.wait(0.2):
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("Run stopped during manual site selection.")

            if dialog_error["message"]:
                raise RuntimeError(f"Manual site selection dialog failed: {dialog_error['message']}")
        
        # start camera with trigger off and then on when imaging starts
        result_run_operator = ResultRunOperator(
            experiment,
            result_set,
            temperature_profile,
            self.db,
            stop_event=stop_event,
            error_callback=handle_operator_error,
            manual_site_callback=request_manual_site_selection,
        )
        result_run_operator.shared_lock = shared_lock

        temperature_operator = None
        if temperature_profile is not None:
            try:
                temperature_operator = TemperatureOperator(
                    temperature_profile,
                    result_run_operator.result_run,
                    self.db,
                    result_run_operator.time_at_temperature,
                    result_run_operator.actual_temperature,
                    result_run_operator.target_temperature,
                    result_run_operator.temperature_last_update,
                    shared_lock,
                    stop_event=stop_event,
                    error_callback=handle_operator_error,
                )
            except Exception as exc:
                result_run_operator.result_run.status = "Failed"
                self.db.update_result_run(result_run_operator.result_run)
                messagebox.showerror("Run Error", f"Temperature controller setup failed:\n{exc}")
                return

        # Prepare worker threads.
        result_thread = threading.Thread(target=result_run_operator.run, daemon=False)
        temperature_thread = None
        if temperature_operator is not None:
            temperature_thread = threading.Thread(target=temperature_operator.run, daemon=False)

        self.run_active = True
        self.run_paused = False
        self.current_result_run_operator = result_run_operator
        self.current_temperature_operator = temperature_operator
        self.current_result_thread = result_thread
        self.current_temperature_thread = temperature_thread
        self.current_stop_event = stop_event

        self.view.disable_run_button()
        self.view.enable_pause_button()
        self.view.enable_stop_button()
        self.view.set_pause_button_text("Pause")

        # Start imaging thread (always required)
        result_thread.start()

        # Temperature thread is optional when no profile is attached to the ResultSet.
        if temperature_thread is not None:
            temperature_thread.start()

        monitor_thread = threading.Thread(
            target=self._monitor_run_completion,
            args=(result_thread, temperature_thread),
            daemon=True,
        )
        monitor_thread.start()

    def toggle_pause_run(self):
        from tkinter import messagebox
        if not self.run_active or self.current_result_run_operator is None:
            return

        try:
            if self.run_paused:
                self.current_result_run_operator.request_resume("Manual resume requested from UI")
                self.run_paused = False
                self.view.set_pause_button_text("Pause")
            else:
                self.current_result_run_operator.request_pause("Manual pause requested from UI")
                self.run_paused = True
                self.view.set_pause_button_text("Resume")
        except Exception as exc:
            messagebox.showerror("Run Error", f"Failed to toggle pause:\n{exc}")

    def stop_run(self):
        from tkinter import messagebox
        if not self.run_active:
            return
        if not messagebox.askyesno("Stop Run", "Stop the current run safely?"):
            return

        if self.current_temperature_operator is not None:
            self.current_temperature_operator.request_stop("Run stop requested from UI")
        if self.current_result_run_operator is not None:
            self.current_result_run_operator.request_stop("Run stop requested from UI")
        if self.current_stop_event is not None:
            self.current_stop_event.set()

        self.run_paused = False
        self.view.set_pause_button_text("Pause")
        self.view.disable_pause_button()
        self.view.disable_stop_button()

    def _monitor_run_completion(self, result_thread, temperature_thread):
        result_thread.join()
        if temperature_thread is not None:
            temperature_thread.join()
        self.view.root_window.after(0, self._on_run_finished)

    def _on_run_finished(self):
        self.run_active = False
        self.run_paused = False
        self.current_result_run_operator = None
        self.current_temperature_operator = None
        self.current_result_thread = None
        self.current_temperature_thread = None
        self.current_stop_event = None
        self.view.set_pause_button_text("Pause")
        self.view.disable_pause_button()
        self.view.disable_stop_button()
        self._update_run_button_state()


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
