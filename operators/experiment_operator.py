from datetime import datetime
from services import Logger, AppConfig
from models import Experiment
from time import sleep

class ExperimentOperator:
    def __init__(self, experiment, db):
        self.db = db
        self.logger = Logger()
        self.app_config = AppConfig()
        self.experiment = experiment
        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)

    def create_json(self):
        # Calculate experiment duration and build per-minute target temperature profile
        pass
