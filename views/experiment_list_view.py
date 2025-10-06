import customtkinter 
import tkinter as tk
from tkinter import ttk


class ExperimentListView():
    def __init__(self):
        self.root_window = customtkinter.CTkToplevel()  # Bare class is passed TK root_window widget.
        self.root_window.title("Experiment List")
        self.root_window.geometry("1000x600")

        # Main container frame that fills the root_window window.
        self.home_frame = customtkinter.CTkFrame(self.root_window)
        self.home_frame.pack(fill="both", expand=True)
        
        # Configure a 3-row grid in the home frame.
        self.home_frame.grid_rowconfigure(0, weight=0)  # Intro row (fixed height)
        self.home_frame.grid_rowconfigure(1, weight=1)  # Table row (expandable)
        self.home_frame.grid_rowconfigure(2, weight=0)  # Button row (fixed height)
        self.home_frame.grid_rowconfigure(3, weight=1)  # Table row (expandable)
        self.home_frame.grid_rowconfigure(4, weight=0)  # Button row (fixed height)
        self.home_frame.grid_columnconfigure(0, weight=1)
        
        # ----------------------------
        # Top Row: Intro Frame
        # ----------------------------
        self.intro_frame = customtkinter.CTkFrame(
            self.home_frame,
            width=800,
            height=50,
            fg_color='transparent'
        )
        self.intro_frame.grid(row=0, column=0, sticky="ew", pady=(30,15))
        
        self.description_label = customtkinter.CTkLabel(
            self.intro_frame,
            text_color='white',
            text=(
                'Clone or delete experiments and launch imaging runs'
            )
        )
        # Using grid inside the intro_frame.
        self.intro_frame.grid_columnconfigure(0, weight=1)
        self.description_label.grid(row=0, column=0, sticky="", padx=10, pady=10)
        
        # ----------------------------
        # Third Row: Experiment Table Frame
        # ----------------------------
        self.experiment_table_frame = customtkinter.CTkScrollableFrame(
            master=self.home_frame,
            width=800,
            height=250,
            fg_color='transparent',
            border_width=0
        )
        self.experiment_table_frame.grid(row=1, column=0, sticky="nsew", padx=100, pady=20)
        
        # Set up the style and theme for the Treeview.
        style = ttk.Style()
        style.theme_use('clam')  # Use a theme that respects our styling.
        style.configure(
            "Treeview",
            background="gray",
            fieldbackground="black",
            foreground="gray85",
            outline="",
            borderwidth=0,
            relief="flat",
            bordercolor="transparent",
        )
        style.configure(
            "Treeview.Heading",
            anchor="w",  # Left justify the header text.
            background="black",
            foreground="gray99",
            outline="",
            borderwidth=0,
            font=("Arial", 12, "bold"),
            relief="flat",
            bordercolor="transparent"
        )
        style.layout("Treeview.Heading", [
            ("Treeheading.cell", {"sticky": "nswe"}),
            ("Treeheading.border", {"sticky": "nswe", "children": [
                ("Treeheading.padding", {"sticky": "nswe", "children": [
                    ("Treeheading.image", {"side": "right", "sticky": ""}),
                    ("Treeheading.text", {"sticky": "w"})  # This forces left alignment.
                ]})
            ]})
        ])
        
        self.exp_columns = ('ID', 'Description', 'Plate','Created', 'Samples')
        self.exp_table = ttk.Treeview(self.experiment_table_frame, columns=self.exp_columns, show='headings')
        
        # Setup headings.
        self.exp_table.heading('ID', text='ID')
        self.exp_table.heading('Description', text='Description')
        self.exp_table.heading('Plate', text='Plate ID')
        self.exp_table.heading('Created', text='Created')
        self.exp_table.heading('Samples', text='Samples')
        
        # Setup columns.
        self.exp_table.column("ID", width=30, anchor='w',minwidth=40, stretch=False)
        self.exp_table.column("Description", width=350, anchor='w')
        self.exp_table.column("Plate", width=75, anchor='w')
        self.exp_table.column("Created", width=100, anchor='w')
        self.exp_table.column("Samples", width=75, anchor='w',minwidth=60, stretch=False)
        
        self.exp_table.pack(fill="both", expand=True)
#        self.table.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)       

       # ----------------------------
        # Button Row for Experiment Table
        # ----------------------------

        # ----------------------------
        # Bottom Row: Button Frame
        # ----------------------------
        self.exp_button_frame = customtkinter.CTkFrame(
            self.home_frame,
            width=200,
            height=30,
            fg_color='transparent'
        )
        self.exp_button_frame.grid(row=2, column=0, sticky="ew", pady=(5, 10))
        
        # Configure a 3-column grid in the button frame.
        for col in range(3):
            self.exp_button_frame.grid_columnconfigure(col, weight=1)
                
        self.copy_button = customtkinter.CTkButton(
            master=self.exp_button_frame,
            text="Clone",
            state=customtkinter.DISABLED
        )
        self.copy_button.grid(sticky="",row=0, column=0, padx=5, pady=10)

        self.delete_button = customtkinter.CTkButton(
            master=self.exp_button_frame,
            text="Delete",
            state=customtkinter.DISABLED
        )
        self.delete_button.grid(sticky="",row=0, column=1, padx=5, pady=10)

        self.script_button = customtkinter.CTkButton(
            master=self.exp_button_frame,
            text="Generate Script",
            state=customtkinter.DISABLED
        )
        self.script_button.grid(sticky="",row=0, column=2, padx=5, pady=10)


       # ----------------------------
        # Fourth Row: Experiment Table Frame
        # ----------------------------
        self.image_set_table_frame = customtkinter.CTkScrollableFrame(
            master=self.home_frame,
            width=800,
            height=250,
            fg_color='transparent',
            border_width=0
        )
        self.image_set_table_frame.grid(row=3, column=0, sticky="nsew", padx=100, pady=20)
        
        
        self.img_columns = ('ID', 'Description', 'Lens', 'Z Stack')
        self.img_table = ttk.Treeview(self.image_set_table_frame, columns=self.img_columns, show='headings')
        
        # Setup headings.
        self.img_table.heading('ID', text='ID')
        self.img_table.heading('Description', text='Description')
        self.img_table.heading('Lens', text='Lens')
        self.img_table.heading('Z Stack', text='Z Stack')
        
        # Setup columns.
        self.img_table.column("ID", width=30, anchor='w',minwidth=40, stretch=False)
        self.img_table.column("Description", width=350, anchor='w')
        self.img_table.column("Lens", width=75, anchor='w')
        self.img_table.column("Z Stack", width=75, anchor='w',minwidth=60, stretch=False)
        
        self.img_table.pack(fill="both", expand=True)
#        self.table.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)       

        # ----------------------------
        # Bottom Row: Button Frame
        # ----------------------------
        self.button_frame = customtkinter.CTkFrame(
            self.home_frame,
            width=500,
            height=30,
            fg_color='transparent'
        )
        self.button_frame.grid(row=4, column=0, sticky="", pady=(5, 10))
        
        self.run_button = customtkinter.CTkButton(
            master=self.button_frame,
            text="Run",
            state=customtkinter.DISABLED,
            fg_color='#992200'
        )
        self.run_button.grid(sticky="",row=0, column=0, padx=5, pady=10)


    def show_experiments(self, data):
        # First clear table
        self.exp_table.delete(*self.exp_table.get_children())
        # Then restore rows from data
        for row in data:
            self.exp_table.insert("", "end", values=row)

    def show_image_sets(self, data):
        # First clear table
        self.img_table.delete(*self.img_table.get_children())
        # Then restore rows from data
        for row in data:
            self.img_table.insert("", "end", values=row)


    def exp_bind_row_selection(self, callback):
        """Expose a method for the presenter to bind the row selection event."""
        self.exp_table.bind('<<TreeviewSelect>>', callback)

    def img_bind_row_selection(self, callback):
        """Expose a method for the presenter to bind the row selection event."""
        self.img_table.bind('<<TreeviewSelect>>', callback)

    def get_id_of_selected_exp_row(self):
        """Helper method to retrieve the currently selected row's values."""
        selected_item = self.exp_table.selection()
        if selected_item:
            return self.exp_table.item(selected_item[0], "values")[0]
            
        return None

    def get_id_of_selected_img_row(self):
        """Helper method to retrieve the currently selected row's values."""
        selected_item = self.img_table.selection()
        if selected_item:
            return self.img_table.item(selected_item[0], "values")[0]
            
        return None


    def enable_edit_button(self):
            self.edit_button.configure(state=customtkinter.NORMAL)

    def enable_copy_button(self):
            self.copy_button.configure(state=customtkinter.NORMAL)

    def enable_run_button(self):
            self.run_button.configure(state=customtkinter.NORMAL)

    def enable_delete_button(self):
            self.delete_button.configure(state=customtkinter.NORMAL)

    def enable_script_button(self):
            self.script_button.configure(state=customtkinter.NORMAL)


    def disable_edit_button(self):
            self.edit_button.configure(state=customtkinter.DISABLED)

    def disable_copy_button(self):
            self.copy_button.configure(state=customtkinter.DISABLED)

    def disable_run_button(self):
            self.run_button.configure(state=customtkinter.DISABLED)

    def disable_delete_button(self):
            self.delete_button.configure(state=customtkinter.DISABLED)

    def disable_script_button(self):
            self.script_button.configure(state=customtkinter.DISABLED)

