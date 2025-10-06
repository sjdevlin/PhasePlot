import serial.tools.list_ports

class Communicator:
    def __init__(self):
        """Initialize the communicator with an empty list of connected devices."""
        self.connected_devices = []

    def scan(self):
        """Scan for available serial (USB) devices and update the connected_devices list."""
        self.connected_devices = [
            (port.device, port.description) for port in serial.tools.list_ports.comports()
        ]

    def __repr__(self):
        return f"Communicator(connected_devices={self.connected_devices})"

# Example Usage
if __name__ == "__main__":
    comm = Communicator()
    comm.scan()
    print(comm.connected_devices)  # Output: [(COM3, 'Silicon Labs CP210x USB to UART Bridge'), ...]
