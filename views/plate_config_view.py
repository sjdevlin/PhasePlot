import customtkinter
from tkinter import ttk, messagebox
from services import AppConfig
import os

class PlateConfigView():

    def __init__(self):

        self.root_window = customtkinter.CTkToplevel()  # Bare class is passed TK root_window widget.
        self.root_window.title("Configure Plate")
        self.root_window.geometry("800x500+430+230")
        #self.root_window.attributes('-topmost', True)

        # Create and place the home_frame using grid (do not mix pack and grid).
        self.home_frame = customtkinter.CTkFrame(self.root_window)
        self.home_frame.grid(row=0, column=0, sticky="nsew")
  #      self.home_frame.pack(fill="both", expand=True)
        self.home_frame.grid_columnconfigure(0, minsize=400)
        self.home_frame.grid_columnconfigure(1, minsize=400)

        # Button frame widgets (fixed typo: use self.button_frame, not self.button_frame_frame).
        self.check_plate_button = customtkinter.CTkButton(master=self.home_frame, text="Check Plate", state=customtkinter.NORMAL)
        self.check_plate_button.grid(row=0, column=0, sticky="w", padx=20, pady=20)
        self.add_new_button = customtkinter.CTkButton(master=self.home_frame, text="Add New Plate", state=customtkinter.DISABLED)
        self.add_new_button.grid(row=0, column=0, sticky="e", padx=20, pady=20)

        self.plate_description_label = customtkinter.CTkLabel(self.home_frame, text="Plate Description:")
        self.plate_description_label.grid(row=1, column=0, padx=20, pady=10, sticky="w")

        self.plate_description_label = customtkinter.CTkLabel(self.home_frame, text="Connection:")
        self.plate_description_label.grid(row=1, column=1, padx=0, pady=10, sticky="w")

        self.plate_description_label = customtkinter.CTkLabel(self.home_frame, text="Find Addresses:")
        self.plate_description_label.grid(row=2, column=1, padx=0, pady=10, sticky="w")

        self.plate_description_label = customtkinter.CTkLabel(self.home_frame, text="Calibrate Sensors:")
        self.plate_description_label.grid(row=3, column=1, padx=0, pady=10, sticky="w")

        self.plate_description_label = customtkinter.CTkLabel(self.home_frame, text="Allocate:")
        self.plate_description_label.grid(row=4, column=1, padx=0, pady=10, sticky="w")

        self.log_window_label = customtkinter.CTkLabel(self.home_frame, text="Information:")
        self.log_window_label.grid(row=5, column=1, padx=0, pady=10, sticky="w")

        self.connection_status = customtkinter.CTkTextbox(self.home_frame, height=30, width=250, fg_color='gray20')
        self.connection_status.grid(row=1, column=1, padx=20, pady=10,sticky="e")

        self.address_status = customtkinter.CTkTextbox(self.home_frame, height=30, width=250, fg_color='gray20')
        self.address_status.grid(row=2, column=1, padx=20, pady=10, sticky="e")

        self.calibrate_status = customtkinter.CTkTextbox(self.home_frame, height=30, width=250, fg_color='gray20')
        self.calibrate_status.grid(row=3, column=1, padx=20, pady=10,sticky="e")

        self.configure_status = customtkinter.CTkTextbox(self.home_frame, height=30, width=250, fg_color='gray20')
        self.configure_status.grid(row=4, column=1, padx=20, pady=10,sticky="e")

        self.log_window = customtkinter.CTkTextbox(self.home_frame, height=150, width=380, fg_color='gray20')
        self.log_window.grid(row=6, column=1, padx=0, pady=20,sticky="w")

    def update_terminal(self, message):
        self.log_window.insert("end", message+"\n")
        self.log_window.see("end")  # Auto-scroll to the end.


    def display_error(self, message):
        messagebox.showerror("Error", message)

    def display_info(self, message):
        messagebox.showinfo("Info", message)

    def ask_question(self, message):
        return messagebox.askyesno("Question", message)
    
    