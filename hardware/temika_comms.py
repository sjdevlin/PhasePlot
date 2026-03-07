from tokenize import String
from services import Logger, AppConfig
from services.singleton import Singleton
import socket
import select
import time

class TemikaComms(metaclass=Singleton):

    def __init__(self):
        self.logger = Logger()
        self.my_app_config = AppConfig()  # Singleton instance - may be opened multiple times from different classes
        self.host = self.my_app_config.get("temika_host")
        self.port = self.my_app_config.get("temika_port")
        self.timeout = self.my_app_config.get("temika_timeout")
        self.buffer_size = self.my_app_config.get("temika_buffer_size")
        self.number_of_retries = max(1, int(self.my_app_config.get("temika_retries", 3)))
        self.socket = None
        self.connect()

    def connect(self):
        if self.socket:
            self.logger.debug("Socket already connected.")
            return True

        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            self.socket.setblocking(True)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.buffer_size)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.buffer_size)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)

            self.logger.debug(f"Connected successfully to Temika server at {self.host}:{self.port}.")
            self.send_command("<temika>") # This opens the connection
            return True

        except (socket.error, OSError) as e:
            self.logger.error(f"Error connecting to Temika server: {e}")
            if self.socket:
                try:
                    self.socket.close()
                except OSError:
                    pass
            self.socket = None
            return False

    def send_command(self, command, wait_for=None):
        if not self.socket or self.socket.fileno() == -1:
            self.logger.warning("Socket is not connected or invalid. Attempting to reconnect...")
            if self.socket:
                self.logger.debug("Closing invalid socket.")
                self.socket.close()
                self.socket = None

            for attempt in range(self.number_of_retries):
                if self.connect():
                    self.logger.info(f"Reconnected successfully on attempt {attempt + 1}.")
                    break
                self.logger.warning(f"Reconnect attempt {attempt + 1} failed.")
            else:
                self.logger.error(f"Failed to reconnect after {self.number_of_retries} attempts.")
                return None



        try:

            # Clear any data in the receive buffer before sending command
            try:
                # Set socket to non-blocking temporarily
                self.socket.setblocking(False)
                # Try to read and discard any pending data
                while True:
                    chunk = self.socket.recv(self.buffer_size)
                    if not chunk:
                        break
            except (socket.error, BlockingIOError):
                # No more data to read or would block
                pass
            finally:
                # Set socket back to blocking mode
                self.socket.setblocking(True)

            # Send the command
            self.socket.sendall(command.encode())
            self.logger.debug(f"Sent command: {command}")

            data = b''
            if wait_for is not None:
                    # Wait for the response
                    start_time = time.time()
                    while True:
                        # Check if timeout has been reached
                        if time.time() - start_time > self.timeout:
                            self.logger.error(f"Timeout after {self.timeout}s waiting for 'Done' response")
                            break
                        
                        readable, _, _ = select.select([self.socket], [], [], 1.0)
                        if not readable:
                            self.logger.debug("No data available yet while waiting for response")
                            continue
                            
                        part = self.socket.recv(self.buffer_size)
                        if not part:
                            break
                        data += part
                        if b'ERROR' in data:
                            self.logger.error("Encountered 'ERROR' in Temika response.")
                            return None
                        if wait_for.encode() in data:
                            break


            if not data:
                return None

            try:
                return data.decode(errors="replace").strip()
            except UnicodeDecodeError as e:
                self.logger.error(f"Failed to decode response: {e}")
                return None

        except (socket.error, OSError) as e:
            self.logger.error(f"Socket error during send_command: {e}")
            if self.socket:
                try:
                    self.socket.close()
                except OSError:
                    pass
            self.socket = None
            return None
