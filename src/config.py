"""Config and field YAML loading."""

import os
import yaml


def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_config(root_dir: str) -> tuple[dict, dict, str]:
    """Return (cfg, field_data, field_name).  Raises FileNotFoundError on missing files."""
    config_path = os.path.join(root_dir, "config.yaml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found: {config_path}")

    cfg = load_yaml(config_path)
    field_file = cfg.get("field", "fieldSPL.yaml")
    field_path = os.path.join(root_dir, "fields", field_file)

    if not os.path.exists(field_path):
        raise FileNotFoundError(f"Field file not found: {field_path}")

    field_data = load_yaml(field_path)
    field_name = os.path.splitext(field_file)[0]
    return cfg, field_data, field_name


def load_teams(root_dir: str) -> dict[int, dict]:
    """Return {team_number: {"name": str, "colors": [str]}} from config/teams.yaml."""
    teams_path = os.path.join(root_dir, "config", "teams.yaml")
    if not os.path.exists(teams_path):
        return {}
    entries = yaml.safe_load(open(teams_path)) or []
    return {
        e["number"]: {
            "name":   e["name"],
            "colors": e.get("fieldPlayerColors", []),
        }
        for e in entries if "number" in e and "name" in e
    }
