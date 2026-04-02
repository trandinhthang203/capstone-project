import yaml
from box import ConfigBox
import os
import json

def read_yaml():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.yaml")
    
    with open(config_path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
        return ConfigBox(content)

def read_json(base_url, file_name):
    file_path = os.path.join(base_url, file_name)
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)
        return data