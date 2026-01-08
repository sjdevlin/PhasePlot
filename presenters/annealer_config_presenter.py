from operators import AnnealerConfigOperator
from models import Plate
import threading

class AnnealerConfigPresenter():
    def __init__(self, view, db):
        self.view = view
        self.db = db

        self.view.check_plate_button.configure(command=self.check_annealer)
        self.operator = AnnealerConfigOperator(self.db, self.update_progress)


    def check_annealer(self):

        connection_status, serial_number = self.operator.check_annealer()

        if connection_status:
            self.view.connection_status.insert("end", "Connection established.")
        else:
            self.view.connection_status.insert("end", "Connection Failed.")
            return

        if serial_number > 0:
            self.view.update_terminal("Annealer found with serial number: " + str(serial_number))
            self.annealer = self.db.get_annealer_by_serial_number(serial_number)
            if self.annealer is not None:
                self.view.update_terminal("Annealer found in database.")
                configure_new = self.view.ask_question("Annealer found in database with ID:" + str(self.annealer.id) + ".\nDo you want to re-configure as a new annealer?")
            else:
                configure_new = self.view.ask_question("Annealer with serial number:" + str(serial_number) + " not found in database.\nDo you want to configure as a new annealer?")
        else:
            self.view.update_terminal("Annealer has no serial number.")
            return    

        if configure_new: #TODO process to fix logic here.  Configure new is none if plate not found
            self.view.root_window.update()
            self.configure_annealer()
    
    def configure_annealer(self):
        from views import LogView
        import threading
        from services import Logger

        def run_and_refresh():
            self.operator.configure_annealer(self.annealer)
            # After completion, schedule a refresh of the view in the main thread.
            self.view.after(0, self.view.update_terminal("Configure thread complete."))

        # Since Logger is a singleton, simply create it here.
        log_file_path = Logger().log_file
        #TODO consider log window to always access singleton logger and no need to pass the reference
        
        # Create a new window to display the log file in real time.
        log_window = LogView(self.view.root_window, log_file_path)

        # Run the config process in a separate thread.
        thread = threading.Thread(target=run_and_refresh, daemon=True)
        thread.start()
    
    def update_progress(self, addresses, calibration_factors, temperature, message):

        self.view.update_terminal(message)

        if addresses is not None:
            self.view.address_status.insert("end", f"{len(addresses)} out of {self.annealer.num_wells} sensors found.")
        if calibration_factors is not None and temperature is not None:
            self.view.calibrate_status.insert("end", f"{len(calibration_factors)} Sensors calibrated. Average temperature: {temperature}")

        
