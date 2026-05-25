from __future__ import annotations

from pydantic import BaseModel, Field


class LanceDBConfig(BaseModel):
    data_path: str = "/data/lancedb"
    cache_size_mb: int = 256


class StorageAppConfig(BaseModel):
    lancedb: LanceDBConfig = Field(default_factory=LanceDBConfig)
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"
