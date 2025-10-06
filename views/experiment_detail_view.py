import customtkinter
from tkinter import ttk, messagebox
import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class ExperimentDetailView():
    def __init__(self, parent):
        self.root = parent.root_window  # Bare class is passed TK root widget.
        
        # Configure the root to allow the home_frame to expand.
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        
        # Create and place the home_frame using grid (do not mix pack and grid).
        self.home_frame = customtkinter.CTkFrame(self.root)
        self.home_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure grid rows and columns for home_frame.
        # Rows: top: 3 parts, middle: 5 parts, bottom: 2 parts.
        self.home_frame.grid_rowconfigure(0, weight=3)
        self.home_frame.grid_rowconfigure(1, weight=5)
        self.home_frame.grid_rowconfigure(2, weight=2)
        
        # Columns: left: 2 parts, right: 1 part.
        self.home_frame.grid_columnconfigure(0, weight=2)
        self.home_frame.grid_columnconfigure(1, weight=1)
        
        # Create sub-frames.
        self.metadata_frame = customtkinter.CTkFrame(self.home_frame, fg_color='transparent', border_width=0)
        self.metadata_frame.grid(row=0, column=0, sticky="", padx=15, pady=15)
        
        self.temperature_profile_frame = customtkinter.CTkScrollableFrame(self.home_frame, fg_color='transparent', border_width=0)
        self.temperature_profile_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        
        self.plate_frame = customtkinter.CTkFrame(self.home_frame, bg_color='transparent', border_width=0)
        self.plate_frame.grid(row=1, column=0, sticky="", padx=15, pady=15)
        
        self.temperature_detail_frame = customtkinter.CTkFrame(self.home_frame,fg_color='transparent')
        self.temperature_detail_frame.grid(row=1, column=1, sticky="", padx=15, pady=15)
        
        self.button_frame = customtkinter.CTkFrame(self.home_frame, fg_color='transparent')
        self.button_frame.grid(row=2, column=0, columnspan=2, sticky="", padx=15, pady=15)
        
        # Configure a simple style for the Treeview.
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview",
                        background="gray",
                        fieldbackground="black",
                        foreground="gray85",
                        borderwidth=0,
                        relief="flat")
        style.configure("Treeview.Heading",
                        anchor="w",
                        background="black",
                        foreground="gray99",
                        font=("Arial", 12, "bold"),
                        borderwidth=0,
                        relief="flat")
        style.layout("Treeview.Heading", [
            ("Treeheading.cell", {"sticky": "nswe"}),
            ("Treeheading.border", {"sticky": "nswe", "children": [
                ("Treeheading.padding", {"sticky": "nswe", "children": [
                    ("Treeheading.image", {"side": "right", "sticky": ""}),
                    ("Treeheading.text", {"sticky": "w"})
                ]})
            ]})
        ])
        
        self.columns = ('ID', 'Description')
        self.table = ttk.Treeview(self.temperature_profile_frame, columns=self.columns, show='headings')
        
        # Setup headings.
        self.table.heading('ID', text='ID')
        self.table.heading('Description', text='Description')
        
        # Setup columns.
        self.table.column("ID", width=15, anchor='w')
        self.table.column("Description", width=300, anchor='w')
        self.table.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # Ensure temperature_profile_frame's grid expands the Treeview.
        self.temperature_profile_frame.grid_rowconfigure(0, weight=1)
        self.temperature_profile_frame.grid_columnconfigure(0, weight=1)
        
        # Metadata frame widgets.
        self.description_label = customtkinter.CTkLabel(self.metadata_frame, text="Description:",bg_color='transparent')
        self.description_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.description_entry = customtkinter.CTkEntry(self.metadata_frame, height=30, width=300, bg_color='transparent', fg_color='gray20', border_width=0)
        self.description_entry.grid(row=0, column=1, padx=5, pady=5)
        
        self.notes_label = customtkinter.CTkLabel(self.metadata_frame, text="Notes:",bg_color='transparent')
        self.notes_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.notes_entry = customtkinter.CTkTextbox(self.metadata_frame, height=60, width=300, fg_color='gray20')
        self.notes_entry.grid(row=1, column=1, padx=5, pady=5)
        
        self.status_label = customtkinter.CTkLabel(self.metadata_frame, text="Status:")
        self.status_label.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.status_entry = customtkinter.CTkEntry(self.metadata_frame, width=300, fg_color='gray20',bg_color='transparent')
        self.status_entry.grid(row=2, column=1, padx=5, pady=5)
        
        # Button frame widgets (fixed typo: use self.button_frame, not self.button_frame_frame).
        self.assign_button = customtkinter.CTkButton(master=self.button_frame, text="Assign", state=customtkinter.DISABLED)
        self.assign_button.grid(row=0, column=0, sticky="nsew", padx=50, pady=5)
        self.save_button = customtkinter.CTkButton(master=self.button_frame, text="Save", state=customtkinter.DISABLED)
        self.save_button.grid(row=0, column=1, sticky="nsew", padx=50, pady=5)
        self.clear_button = customtkinter.CTkButton(master=self.button_frame, text="Clear", state=customtkinter.DISABLED)
        self.clear_button.grid(row=0, column=2, sticky="nsew", padx=50, pady=5)
        self.back_button = customtkinter.CTkButton(master=self.button_frame, text="Back", state=customtkinter.NORMAL)
        self.back_button.grid(row=0, column=3, sticky="nsew", padx=50, pady=5)
        
        # Optionally, configure button_frame's grid columns to share space equally.
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)
        self.button_frame.grid_columnconfigure(2, weight=1)
        self.button_frame.grid_columnconfigure(3, weight=1)

    def populate_experiment_metadata(self, description, notes, status):
        self.description_entry.delete(0, "end")
        self.description_entry.insert(0, description)
        self.notes_entry.delete("1.0", "end")
        self.notes_entry.insert("1.0", notes)
        self.status_entry.delete(0, "end")
        self.status_entry.insert(0, status)
        self.status_entry.configure(state=customtkinter.DISABLED)

    def show_temperature_profiles(self, data):
        self.table.delete(*self.table.get_children())
        for row in data:
            self.table.insert("", "end", values=row)

    def draw_temperature_detail(self, target_times, target_temperatures, actual_times, actual_temperatures):
        # Clear any existing widgets in the detail frame.
        for widget in self.temperature_detail_frame.winfo_children():
            widget.destroy()

        # Compute cumulative time and temperature points.

        # Apply custom style for the plot
        mpl.rcParams.update({
            'font.size': 16,
            'font.family': 'Helvetica',
            'text.color': 'white',
            'axes.labelcolor': 'white',
            'xtick.color': 'white',
            'ytick.color': 'white',
            'axes.facecolor': '#555555',
            'figure.facecolor': '#303030',
            'axes.edgecolor': 'white'
        })

        # Create a matplotlib figure.
        fig = Figure(figsize=(9, 6), dpi=50)
        ax = fig.add_subplot(111)
        fig.subplots_adjust(bottom=0.2)

        ax.plot(target_times, target_temperatures, marker='', linestyle='-', color='#EE6611')
        ax.plot(actual_times, actual_temperatures, marker='', linestyle='-', color='red')

        current_time = max(max(target_times) if target_times else 0, max(actual_times) if actual_times else 0)
        ax.set_xlabel("Time (minutes)")
        ax.set_ylabel("Temperature (°C)")
        # Set fixed y-axis and x-axis ranges.
        ax.set_ylim(20, 60)
        ax.set_xlim(0, current_time if current_time > 0 else 1)
        ax.grid(True)

        # Embed the figure in the temperature_detail_frame.
        canvas = FigureCanvasTkAgg(fig, master=self.temperature_detail_frame)
        canvas.draw()
        canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

        # Ensure the frame resizes with the canvas.
        self.temperature_detail_frame.grid_rowconfigure(0, weight=1)
        self.temperature_detail_frame.grid_columnconfigure(0, weight=1)


    def show_plate(self, plate_width, plate_height, offset_x, offset_y, well_spacing_x, well_spacing_y, well_diameter, well_data, callback):

        # Clear the plate frame
        for widget in self.plate_frame.winfo_children():
            widget.destroy()

        # Draw the rectangle
        scale = 3 # change this to be a paraemter

        self.canvas = customtkinter.CTkCanvas(self.plate_frame, width=plate_width*scale+1, height=plate_height*scale+1,highlightthickness=0,bd=0)
        self.canvas.create_rectangle(1, 1, plate_width*scale, plate_height*scale, fill="gray30", state='disabled',width=0)
        self.canvas.grid(row=0, column=0, sticky="", padx=0, pady=0)
        self.canvas.bind("<Button-1>", callback)

        # Draw the wells as selectable circles

        self.well_buttons = {}

        for well in well_data:
            well_index, row, column, status, selected = well
            x = (offset_x * scale) + ((column) * scale * well_spacing_x)
            y = (offset_y * scale) + ((row) * scale * well_spacing_y)
            r = well_diameter * scale 

            if status == 'inactive':
                fill_color = "gray10"
            if status == 'assigned':
                fill_color = "#EE6611"
            if status == 'available':
                fill_color = "white"

            well_button_id = self.canvas.create_oval(
                2+(x - r),2+(y - r),2+(x + r),2+(y + r), 
                fill=fill_color, 
                outline="")
            self.well_buttons[well_button_id] = well_index

            if selected:
                self.canvas.create_oval(
                    2+(x - 2*r),2+ (y - 2*r),2+ (x + 2*r),2+ (y + 2*r), 
                    fill="", 
                    outline="gray99",
                    width=3)
                 
    def get_id_of_selected_well(self, event):
        clicked_item = self.canvas.find_closest(event.x, event.y)[0]  # Get the closest item ID
        if self.canvas.type(clicked_item) == "oval":
            return self.well_buttons[clicked_item] # subtract 1 because first oval is 1
        else:
            return None

    def bind_row_selection(self, callback):
        """Expose a method for the presenter to bind the row selection event."""
        self.table.bind('<<TreeviewSelect>>', callback)

    def get_id_of_selected_row(self):
        """Helper method to retrieve the currently selected row's values."""
        selected_item = self.table.selection()
        if selected_item:
            return self.table.item(selected_item[0], "values")[0]

    def select_profile(self, profile_id):
        for item_id in self.table.get_children():
                # Retrieve the item's data dictionary.
                item_data = self.table.item(item_id)
                values = item_data.get("values")
                # Ensure there are values and the first value matches the profile_id.
                if str(values[0]) == str(profile_id):
                    # Select and bring the matching row into view.
                    self.table.selection_set(item_id)
                    self.table.see(item_id)
                    break

    def clear_profile_selection(self):
        self.table.selection_set(())

    def enable_save_button(self):
            self.save_button.configure(state=customtkinter.NORMAL)

    def enable_clear_button(self):
            self.clear_button.configure(state=customtkinter.NORMAL)

    def enable_assign_button(self):
            self.assign_button.configure(state=customtkinter.NORMAL)

    def disable_save_button(self):
            self.save_button.configure(state=customtkinter.DISABLED)

    def disable_clear_button(self):
            self.clear_button.configure(state=customtkinter.DISABLED)

    def disable_assign_button(self):
            self.assign_button.configure(state=customtkinter.DISABLED)

    def close(self):  # Add a close method to destroy the view.
        self.home_frame.destroy()

    def display_error(self, message):
        messagebox.showerror("Error", message)

    def display_info(self, message):
        messagebox.showinfo("Info", message)

    def ask_question(self, message):
        return messagebox.askyesno("Question", message)
    
    