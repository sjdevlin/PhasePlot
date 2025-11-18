import customtkinter
from tkinter import ttk, messagebox
from services import well_to_indices, indices_to_well

class PlateConfigView():
    def __init__(self, on_close_callback=None):
        self.on_close_callback = on_close_callback
        self.root = customtkinter.CTkToplevel()  # Create the Toplevel window.
        self.root.title("Sandbox")
        self.root.geometry("600x500")
        
        # Bind the window close event to our on-close method.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
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
        self.plate_frame = customtkinter.CTkFrame(self.home_frame, bg_color='transparent', border_width=0)
        self.plate_frame.grid(row=0, column=0, sticky="", padx=5, pady=10)

        self.literal1 = customtkinter.CTkLabel(self.home_frame, text="Current Z:")
        self.literal1.grid(row=1, column=0, padx=10, pady=10, sticky="w")

        self.z_height  = customtkinter.CTkLabel(self.home_frame, text="--")
        self.z_height.grid(row=1, column=1, padx=10, pady=10, sticky="e")

        self.plate_literal = customtkinter.CTkLabel(self.home_frame, text="Enter Plate ID:")
        self.plate_literal.grid(row=2, column=0, padx=10, pady=10, sticky="w")

        self.id_entry = customtkinter.CTkEntry(self.home_frame, height=30, width=100, fg_color='gray20')
        self.id_entry.grid(row=2, column=0, padx=10, pady=10, sticky="e")

        self.retrieve_plate_button = customtkinter.CTkButton(master=self.home_frame, text="Retreive Plate", state=customtkinter.NORMAL)
        self.retrieve_plate_button.grid(row=2, column=1, sticky="", padx=0, pady=5)

#        self.next_button = customtkinter.CTkButton(master=self.home_frame, text="Next Well", state=customtkinter.DISABLED)
#        self.next_button.grid(row=3, column=0, sticky="", padx=0, pady=5)

        self.store_button = customtkinter.CTkButton(master=self.home_frame, text="Store", state=customtkinter.DISABLED)
        self.store_button.grid(row=3, column=1, sticky="", padx=0, pady=5)

    def _on_close(self):
        """Called when the window is closed. Invoke the callback and destroy the window."""
        if self.on_close_callback:
            self.on_close_callback()
        self.root.destroy()

    def show_plate(self, plate_width, plate_length, offset_x, offset_y, well_spacing_x, well_spacing_y, well_diameter, well_data, callback):
        # Clear the plate frame
        for widget in self.plate_frame.winfo_children():
            widget.destroy()

        scale = 2  # Change this to be a parameter if needed.
        self.canvas = customtkinter.CTkCanvas(self.plate_frame, width=plate_width*scale+1, height=plate_length*scale+1,
                                               highlightthickness=0, bd=0)
        self.canvas.create_rectangle(1, 1, plate_width*scale, plate_length*scale, fill="gray30", state='disabled', width=0)
        self.canvas.grid(row=0, column=0, sticky="", padx=0, pady=0)
        self.canvas.bind("<Button-1>", callback)

        self.well_button_row = {}
        self.well_button_column = {}
        for well in well_data:
            row, column, selected = well
            # Convert row label (e.g., "A", "B", "AA") to an integer with A=1
            row_int, column_int = well_to_indices(row, column)
            x = (offset_x * scale ) + (column_int * scale * well_spacing_x )
            y = (offset_y * scale ) + (row_int * scale * well_spacing_y )
            r = well_diameter * scale 
            fill_color = "white" 
            well_button_id = self.canvas.create_oval(
                2+(x - r), 2+(y - r), 2+(x + r), 2+(y + r), 
                fill=fill_color, 
                outline=""
            )
            self.well_button_row[well_button_id] = row
            self.well_button_column[well_button_id] = column

            if selected:
                self.canvas.create_oval(
                    2+(x - 2*r), 2+(y - 2*r), 2+(x + 2*r), 2+(y + 2*r), 
                    fill="", 
                    outline="gray99",
                    width=4
                )
                 
    def get_row_col_selected_well(self, event):
        clicked_item = self.canvas.find_closest(event.x, event.y)[0]  # Get the closest item ID.
        if self.canvas.type(clicked_item) == "oval":
            return self.well_button_row[clicked_item], self.well_button_column[clicked_item]
        else:
            return None

    def enable_store_button(self):
        self.store_button.configure(state=customtkinter.NORMAL)

    def disable_store_button(self):
        self.store_button.configure(state=customtkinter.DISABLED)
    
#    def enable_next_button(self):
#        self.next_button.configure(state=customtkinter.NORMAL)

 #   def disable_next_button(self):
 #       self.next_button.configure(state=customtkinter.DISABLED)


    def display_error(self, message):
        messagebox.showerror("Error", message)

    def display_info(self, message):
        messagebox.showinfo("Info", message)

    def ask_question(self, message):
        return messagebox.askyesno("Question", message)
