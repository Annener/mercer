from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from config import StorageAppConfig


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping.")
    return data


def get_storage_config(config_path: str = "/app/config.yaml") -> StorageAppConfig:
    return StorageAppConfig.model_validate(_load_yaml(Path(config_path)))
