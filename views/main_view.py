import customtkinter 
import tkinter as tk
from tkinter import ttk


class MainView():
    def __init__(self, root_window):
        self.root_window = root_window  # Bare class is passed TK root_window widget.
        
        # Main container frame that fills the root_window window.
        self.home_frame = customtkinter.CTkFrame(self.root_window, fg_color='transparent')
        self.home_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # Configure a 3-row grid in the home frame.

        self.experiment_button = customtkinter.CTkButton(self.home_frame, text="Experiment", state=customtkinter.NORMAL)
        self.results_button = customtkinter.CTkButton(self.home_frame, text="Results",state=customtkinter.NORMAL)
        self.annealing_button = customtkinter.CTkButton(self.home_frame, text="Annealing Profiles", state=customtkinter.DISABLED)   
        self.imaging_button = customtkinter.CTkButton(self.home_frame, text="Imaging", state=customtkinter.DISABLED)    
        self.plate_config_button = customtkinter.CTkButton(self.home_frame, text="Configure Plate",state=customtkinter.DISABLED)
        self.plate_sandbox_button = customtkinter.CTkButton(self.home_frame, text="Plate Sandbox",state=customtkinter.DISABLED)
        self.image_sandbox_button = customtkinter.CTkButton(self.home_frame, text="Image Sandbox",state=customtkinter.NORMAL)

        self.experiment_button.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        self.results_button.grid(row=2, column=0, sticky="nsew", padx=20, pady=20,)
        self.annealing_button.grid(row=3, column=0, sticky="nsew", padx=20, pady=20)
        self.imaging_button.grid(row=4, column=0, sticky="nsew", padx=20, pady=20)
        self.plate_config_button.grid(row=5, column=0, sticky="nsew", padx=20, pady=20)
        self.plate_sandbox_button.grid(row=6, column=0, sticky="nsew", padx=20, pady=20)
        self.image_sandbox_button.grid(row=7, column=0, sticky="nsew", padx=20, pady=20)

