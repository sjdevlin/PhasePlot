import os
import customtkinter as ctk

class LogView(ctk.CTkToplevel):
    def __init__(self, parent, log_file_path, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.title("Real-Time Log Viewer")
        self.geometry("600x400")
        self.log_file_path = log_file_path

        # Use a CTkTextbox for displaying the log text
        self.text_area = ctk.CTkTextbox(self, wrap="word")
        self.text_area.pack(expand=True, fill="both", padx=10, pady=10)

        # Open the log file in read mode and move to the end (to show only new logs)
        self.log_fp = open(self.log_file_path, "r", encoding="utf-8")
        self.log_fp.seek(0, os.SEEK_END)

        self.poll_interval = 1000  # in milliseconds
        self.after(self.poll_interval, self.update_log)

    def update_log(self):
        """Read any new lines from the log file and display them."""
        line = self.log_fp.readline()
        while line:
            self.text_area.insert("end", line)
            # Scroll to the bottom to show the latest content
            self.text_area.see("end")
            line = self.log_fp.readline()
        self.after(self.poll_interval, self.update_log)

    def destroy(self):
        if not self.log_fp.closed:
            self.log_fp.close()
        super().destroy()


