import logging
import sys
import os


class Logger:
    
    def __init__(self, log_dir="logs", log_file="app.log", error_file="error.log", debug=False, console_output=False):

        self.log_dir = log_dir
        self.log_file = os.path.join(log_dir, log_file)
        self.error_file = os.path.join(log_dir, error_file)
        self.console_output = console_output

        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)

        # Create loggers
        self.logger = logging.getLogger("AppLogger")
        self.logger.setLevel(logging.DEBUG)  # Capture all log levels
        
        self.error_logger = logging.getLogger("ErrorLogger")
        self.error_logger.setLevel(logging.ERROR)  # Capture only errors

        # Prevent duplicate log entries
        self.logger.propagate = False
        self.error_logger.propagate = False

        # Create formatters
        log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")

        # File handler for general logs
        file_handler = logging.FileHandler(self.log_file, mode='a', encoding='utf-8')
        if debug:
            file_handler.setLevel(logging.DEBUG)
        else:
            file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(log_formatter)
        self.logger.addHandler(file_handler)

        # File handler for error logs
        error_handler = logging.FileHandler(self.error_file, mode='a', encoding='utf-8')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(log_formatter)
        self.error_logger.addHandler(error_handler)

        # Console handler (optional)
        if self.console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            if debug:
                console_handler.setLevel(logging.DEBUG)
            else:
                console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(log_formatter)
            self.logger.addHandler(console_handler)

    def debug(self, message):
        """Log a debug message."""
        self.logger.debug(message)

    def info(self, message):
        """Log an info message."""
        self.logger.info(message)

    def warning(self, message):
        """Log a warning message."""
        self.logger.warning(message)

    def error(self, message):
        """Log an error message (also recorded in the error log)."""
        self.logger.error(message)
        self.error_logger.error(message)

    def critical(self, message):
        """Log a critical error message."""
        self.logger.critical(message)
        self.error_logger.critical(message)