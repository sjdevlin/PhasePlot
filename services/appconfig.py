import yaml
import os
from .singleton import Singleton


class AppConfig(metaclass=Singleton):
    def __init__(self, config_file='./config.yaml', verbose=False, debug=False):
        self.verbose = verbose
        self.debug = debug
        self._load_config(config_file)

    def _load_config(self, config_file):
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Config file '{config_file}' not found.")

        with open(config_file, 'r') as file:
            self._config = yaml.safe_load(file)

    def get(self, key, default=None):
        return self._config.get(key, default)
