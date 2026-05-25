from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


logger = logging.getLogger(__name__)

CACHE_DIR = Path("/app/cache/embeddings")


def _cache_key(text: str, model_name: str, dimensions: int) -> str:
    payload = f"{text}_{model_name}_{dimensions}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _paths(key: str) -> tuple[Path, Path, Path, Path]:
    vector_path = CACHE_DIR / f"{key}.npy"
    meta_path = CACHE_DIR / f"{key}.meta.json"
    tmp_vector_path = CACHE_DIR / f"{key}.tmp.npy"
    tmp_meta_path = CACHE_DIR / f"{key}.tmp.meta.json"
    return vector_path, meta_path, tmp_vector_path, tmp_meta_path


def _remove_cache_files(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to remove embedding cache file: %s", path, exc_info=True)


def get_cached(text: str, model_name: str, dimensions: int) -> list[float] | None:
    key = _cache_key(text, model_name, dimensions)
    vector_path, meta_path, _, _ = _paths(key)

    if not vector_path.exists() or not meta_path.exists():
        return None

    try:
        if vector_path.stat().st_size == 0 or meta_path.stat().st_size == 0:
            raise ValueError("Cache file is empty.")

        with meta_path.open("r", encoding="utf-8") as meta_file:
            metadata: dict[str, Any] = json.load(meta_file)
        if metadata.get("model_name") != model_name or metadata.get("dimensions") != dimensions:
            raise ValueError("Cache metadata does not match requested model.")

        vector = np.load(vector_path)
        if vector.ndim != 1 or int(vector.shape[0]) != dimensions:
            raise ValueError("Cached vector dimension mismatch.")
        return [float(value) for value in vector.tolist()]
    except Exception as exc:
        logger.warning("Ignoring corrupt embedding cache entry %s: %s", key, exc)
        _remove_cache_files(vector_path, meta_path)
        return None


def save_cache(text: str, model_name: str, dimensions: int, vector: list[float]) -> None:
    key = _cache_key(text, model_name, dimensions)
    vector_path, meta_path, tmp_vector_path, tmp_meta_path = _paths(key)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if len(vector) != dimensions:
            raise ValueError(f"Vector dimension mismatch: expected {dimensions}, got {len(vector)}")

        np.save(tmp_vector_path, np.asarray(vector, dtype=np.float32))
        metadata = {
            "model_name": model_name,
            "dimensions": dimensions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with tmp_meta_path.open("w", encoding="utf-8") as meta_file:
            json.dump(metadata, meta_file, ensure_ascii=False, indent=2)
            meta_file.write("\n")

        os.replace(tmp_vector_path, vector_path)
        os.replace(tmp_meta_path, meta_path)
    except Exception as exc:
        logger.warning("Failed to save embedding cache entry %s: %s", key, exc)
        _remove_cache_files(tmp_vector_path, tmp_meta_path)
