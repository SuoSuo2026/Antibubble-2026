import yaml


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def get_roi_tuple(config):
    roi = config["roi"]
    return roi["x"], roi["y"], roi["w"], roi["h"]
