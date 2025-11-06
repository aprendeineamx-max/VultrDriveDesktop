import json
import os
import sys

class ConfigManager:
    def __init__(self, config_file='config.json'):
        # Detectar si estamos ejecutando desde PyInstaller
        if getattr(sys, 'frozen', False):
            # Ejecutando desde ejecutable empaquetado
            base_path = os.path.dirname(sys.executable)
        else:
            # Ejecutando desde script Python
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        self.config_file = os.path.join(base_path, config_file)
        self.configs = self.load_configs()

    def load_configs(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {}

    def save_configs(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.configs, f, indent=4)

    def add_config(self, profile_name, access_key, secret_key, host_base):
        self.configs[profile_name] = {
            'access_key': access_key,
            'secret_key': secret_key,
            'host_base': host_base
        }
        self.save_configs()

    def delete_config(self, profile_name):
        if profile_name in self.configs:
            del self.configs[profile_name]
            self.save_configs()

    def get_config(self, profile_name):
        return self.configs.get(profile_name)

    def list_profiles(self):
        return list(self.configs.keys())
