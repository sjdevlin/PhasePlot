import customtkinter 
import tkinter as tk
from tkinter import ttk


class ImageRunListView():
    def __init__(self):
        self.root_window = customtkinter.CTkToplevel()  # Bare class is passed TK root_window widget.
        self.root_window.title("Results from Image Runs")
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
            width=900,
            height=50,
            fg_color='transparent'
        )
        self.intro_frame.grid(row=0, column=0, sticky="ew", pady=(30,15))
        
        self.description_label = customtkinter.CTkLabel(
            self.intro_frame,
            text_color='white',
            text=(
                'Process and View Imaging Runs'
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
            width=900,
            height=350,
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
        
        self.res_columns = ('ID', 'Description', 'Samples','Images', 'Completed')
        self.res_table = ttk.Treeview(self.experiment_table_frame, columns=self.res_columns, show='headings')
        
        # Setup headings.
        self.res_table.heading('ID', text='ID')
        self.res_table.heading('Description', text='Description')
        self.res_table.heading('Samples', text='Samples')
        self.res_table.heading('Images', text='Images')
        self.res_table.heading('Completed', text='Completed')
        
        # Setup columns.
        self.res_table.column("ID", width=50, anchor='w',minwidth=40, stretch=False)
        self.res_table.column("Description", width=500, anchor='w')
        self.res_table.column("Samples", width=60, anchor='w', stretch=False)
        self.res_table.column("Images", width=60, anchor='w', stretch=False)
        self.res_table.column("Completed", width=100, anchor='w')
        
        self.res_table.pack(fill="both", expand=True)
#        self.table.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)       

       # ----------------------------
        # Button Row for Experiment Table
        # ----------------------------

        # ----------------------------
        # Bottom Row: Button Frame
        # ----------------------------
        self.res_button_frame = customtkinter.CTkFrame(
            self.home_frame,
            width=200,
            height=30,
            fg_color='transparent'
        )
        self.res_button_frame.grid(row=2, column=0, sticky="ew", pady=(5, 10))
        
        # Configure a 3-column grid in the button frame.
        for col in range(2):
            self.res_button_frame.grid_columnconfigure(col, weight=1)
                
        self.review_button = customtkinter.CTkButton(
            master=self.res_button_frame,
            text="Review",
            state=customtkinter.DISABLED
        )
        self.review_button.grid(sticky="",row=0, column=0, padx=5, pady=10)

        self.process_button = customtkinter.CTkButton(
            master=self.res_button_frame,
            text="Process",
            state=customtkinter.DISABLED
        )
        self.process_button.grid(sticky="",row=0, column=1, padx=5, pady=10)



    def list_results(self, data):
        # First clear table
        self.res_table.delete(*self.res_table.get_children())
        # Then restore rows from data
        for row in data:
            self.res_table.insert("", "end", values=row)


    def res_bind_row_selection(self, callback):
        """Expose a method for the presenter to bind the row selection event."""
        self.res_table.bind('<<TreeviewSelect>>', callback)

    def get_id_of_selected_res_row(self):
        """Helper method to retrieve the currently selected row's values."""
        selected_item = self.res_table.selection()
        if selected_item:
            return self.res_table.item(selected_item[0], "values")[0]
            
        return None

    def enable_review_button(self):
            self.review_button.configure(state=customtkinter.NORMAL)

    def enable_process_button(self):
            self.process_button.configure(state=customtkinter.NORMAL)

    def disable_review_button(self):
            self.review_button.configure(state=customtkinter.DISABLED)

    def disable_process_button(self):
            self.process_button.configure(state=customtkinter.DISABLED)



