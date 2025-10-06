from hardware import StageControllerFactory, CameraControllerFactory, IlluminationControllerFactory, FocusControllerFactory
from services import Logger, AppConfig, DatabaseService
from models import Plate
from time import sleep

class MicroscopeOperator():
    def __init__(self, db, progress_callback=None):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.progress_callback = progress_callback


#    def focus??(self, plate):






