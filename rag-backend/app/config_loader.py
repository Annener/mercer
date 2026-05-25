from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import AppConfig


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping.")
    return data


@lru_cache(maxsize=1)
def get_config(config_path: str = "/app/config/config.yaml") -> AppConfig:
    path = Path(config_path)
    if not path.exists():
        path = Path("/app/config/config.example.yaml")
    return AppConfig.model_validate(_load_yaml(path))
