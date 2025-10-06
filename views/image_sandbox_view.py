import customtkinter
from tkinter import ttk, messagebox

class ImageSandboxView():
    def __init__(self):
        self.root = customtkinter.CTkToplevel()  # Create the Toplevel window.
        self.root.title("Image Sandbox")
        self.root.geometry("400x600")
        
        # Configure the root to allow the home_frame to expand.
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Create and place the home_frame using grid.
        self.home_frame = customtkinter.CTkFrame(self.root)
        self.home_frame.grid(row=0, column=0, sticky="nsew")
                
        # Configure grid columns.
        self.home_frame.grid_columnconfigure(0, weight=2)
        self.home_frame.grid_columnconfigure(1, weight=1)
        
        # Create sub-frames.
#        self.plate_frame = customtkinter.CTkFrame(self.home_frame, bg_color='transparent', border_width=0)
#        self.plate_frame.grid(row=0, column=0, sticky="", padx=5, pady=10)

        self.led_number = customtkinter.CTkLabel(self.home_frame, text="LED:")
        self.led_number.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.led_number_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.led_number_entry.grid(row=0, column=0, padx=10, pady=10, sticky="e")

        self.led_bitmask = customtkinter.CTkLabel(self.home_frame, text="Bitmask:")
        self.led_bitmask.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.led_bitmask_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.led_bitmask_entry.grid(row=1, column=0, padx=10, pady=10, sticky="e")

 
        self.led_intensity = customtkinter.CTkLabel(self.home_frame, text="Brightness:")
        self.led_intensity.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.led_intensity_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.led_intensity_entry.grid(row=2, column=0, padx=10, pady=10, sticky="e")

        self.apply_illumination_button = customtkinter.CTkButton(self.home_frame, text="Apply Illumination", state=customtkinter.NORMAL)
        self.apply_illumination_button.grid(row=3, column=0, padx=0, pady=5, sticky="e")


        self.shutter_speed = customtkinter.CTkLabel(self.home_frame, text="Shutter Speed:")
        self.shutter_speed.grid(row=4, column=0, padx=10, pady=10, sticky="w")
        self.shutter_speed_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.shutter_speed_entry.grid(row=4, column=0, padx=10, pady=10, sticky="e")

        self.file_name = customtkinter.CTkLabel(self.home_frame, text="File Name:")
        self.file_name.grid(row=5, column=0, padx=10, pady=10, sticky="w")
        self.file_name_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.file_name_entry.grid(row=5, column=0, padx=10, pady=10, sticky="e")

        self.record_image_button = customtkinter.CTkButton(self.home_frame, text="Record Image", state=customtkinter.NORMAL)
        self.record_image_button.grid(row=6, column=0, padx=0, pady=5, sticky="e")

        self.position = customtkinter.CTkLabel(self.home_frame, text="Position:")
        self.position.grid(row=7, column=0, padx=10, pady=10, sticky="w")
        self.position_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.position_entry.grid(row=7, column=0, padx=10, pady=10, sticky="e")

        self.speed = customtkinter.CTkLabel(self.home_frame, text="Speed:")
        self.speed.grid(row=8, column=0, padx=10, pady=10, sticky="w")
        self.speed_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.speed_entry.grid(row=8, column=0, padx=10, pady=10, sticky="e")

        self.move_stage_button = customtkinter.CTkButton(self.home_frame, text="Move Stage", state=customtkinter.NORMAL)
        self.move_stage_button.grid(row=9, column=0, sticky="e", padx=0, pady=5)

