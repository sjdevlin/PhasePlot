# Control system for annealing and imaging system
# S. Devlin - University of Cambridge
# 2025

import customtkinter
import sys
from services import Logger, AppConfig, DatabaseService
from presenters import MainPresenter
from views import MainView
import argparse

# check config file argument is provided

parser = argparse.ArgumentParser(description='System X Control Software')
parser.add_argument('config', help='Path to configuration file')
parser.add_argument('-v', '--verbose', action='store_true', help='Display log in real time to screen')
parser.add_argument('-d', '--debug', action='store_true', help='Enable debug level output to log file')
args = parser.parse_args()

verbose = args.verbose
debug = args.debug
config_file = args.config

if not config_file:
    print("Error: Configuration file (*.yaml) must be provided")
    sys.exit(1)

try:
    config = AppConfig(config_file, verbose, debug)
except Exception as e:
    print(f"Error loading configuration file: {str(e)}")
    sys.exit(1)

# Initialize the logger
logger = Logger(config.get("log_dir"), config.get("log_file"), config.get("error_file"), debug, verbose)

# Initialize the main window
customtkinter.set_appearance_mode("dark")  # Modes: system (default), light, dark
customtkinter.set_default_color_theme("blue")  # Themes: blue (default), dark-blue, green
root_window = customtkinter.CTk()
root_window.title("System X")
root_window.geometry("200x500+200+100")


# Database connection
db = DatabaseService(config.get("sqlite_db"))

# Initialize the view and presenter
main_view = MainView(root_window)
presenter = MainPresenter(main_view, db)

root_window.mainloop()
