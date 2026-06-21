"""DEPRECATED: заменён RedisStateManager (этап 4).

Оставлен временно: импорты из этого модуля ещё используются
в app/main.py и indexer_service.py (этапы 6-8 заменят эти вызовы).
Не добавлять новых вызовов к этому модулю.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from shared_contracts.models import FileIndexState, IndexState

STATE_PATH = Path("/app/state/index_state.json")
TMP_STATE_PATH = Path("/app/state/index_state.tmp.json")
TASKS_DIR = Path("/app/state/tasks")

_state_lock = asyncio.Lock()


def _last_modified_to_datetime(value: float | int | str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _task_state_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _task_tmp_state_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.tmp.json"


def last_successful_path(vault_id: str) -> Path:
    safe_vault_id = "".join(char if char.isalnum() or char in "-" else "" for char in vault_id)
    return STATE_PATH.parent / f"last_successful_{safe_vault_id}.json"


def _read_state_file_unlocked(path: Path) -> IndexState | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as state_file:
        return IndexState.model_validate(json.load(state_file))


def _write_state_file_unlocked(state: IndexState, path: Path, tmp_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp_path.open("w", encoding="utf-8") as state_file:
        json.dump(state.model_dump(mode="json"), state_file, ensure_ascii=False, indent=2)
        state_file.write("\n")
    os.replace(tmp_path, path)


def _read_state_unlocked(task_id: str | None = None) -> IndexState | None:
    if task_id is not None:
        return _read_state_file_unlocked(_task_state_path(task_id))
    return _read_state_file_unlocked(STATE_PATH)


def _write_state_unlocked(state: IndexState) -> None:
    _write_state_file_unlocked(state, STATE_PATH, TMP_STATE_PATH)
    _write_state_file_unlocked(state, _task_state_path(state.task_id), _task_tmp_state_path(state.task_id))


async def load_state(task_id: str) -> IndexState | None:
    async with _state_lock:
        state = _read_state_unlocked(task_id)
        if state is not None:
            return state
        state = _read_state_unlocked()
        if state is None or state.task_id != task_id:
            return None
        return state


async def save_state(state: IndexState) -> None:
    async with _state_lock:
        _write_state_unlocked(state)


async def load_last_successful_state(vault_id: str) -> IndexState | None:
    async with _state_lock:
        return _read_state_file_unlocked(last_successful_path(vault_id))


async def save_last_successful_state(state: IndexState) -> None:
    async with _state_lock:
        path = last_successful_path(state.vault_id)
        tmp_path = path.with_suffix(".tmp.json")
        _write_state_file_unlocked(state, path, tmp_path)


async def create_state(task_id: str, vault_id: str, files_info: list[dict]) -> IndexState:
    files: dict[str, FileIndexState] = {}
    for file_info in files_info:
        relative_path = str(file_info.get("relative_path", "")).strip()
        if not relative_path:
            continue

        files[relative_path] = FileIndexState(
            checksum_md5=str(file_info["checksum"]),
            status="pending",
            progress_pct=0,
            chunks_total=0,
            chunks_processed=0,
            last_modified=_last_modified_to_datetime(file_info["last_modified"]),
            error=None,
        )

    state = IndexState(
        task_id=task_id,
        vault_id=vault_id,
        status="running",
        last_updated=datetime.now(timezone.utc),
        files=files,
        error=None,
    )
    await save_state(state)
    return state


async def update_file_status(
    task_id: str,
    file_path: str,
    status: Literal[
        "pending",
        "parsing",
        "chunking",
        "indexing",
        "done",
        "error",
        "cancelled",
        "empty",
        "indexed",
    ],
    progress_pct: int = 0,
    chunk_ids: list[str] | None = None,
    error: str | None = None,
    chunks_total: int | None = None,
    chunks_processed: int | None = None,
) -> None:
    async with _state_lock:
        state = _read_state_unlocked(task_id)
        if state is None or state.task_id != task_id:
            raise ValueError(f"State not found for task_id={task_id}")

        if file_path not in state.files:
            raise KeyError(f"File is not present in state: {file_path}")

        file_state = state.files[file_path]
        file_state.status = status
        file_state.progress_pct = progress_pct
        file_state.error = error
        if chunk_ids is not None:
            file_state.chunk_ids = []
        if chunks_total is not None:
            file_state.chunks_total = chunks_total
        if chunks_processed is not None:
            file_state.chunks_processed = chunks_processed

        state.last_updated = datetime.now(timezone.utc)
        _write_state_unlocked(state)


async def mark_task_done(task_id: str, error: str | None = None) -> None:
    async with _state_lock:
        state = _read_state_unlocked(task_id)
        if state is None or state.task_id != task_id:
            raise ValueError(f"State not found for task_id={task_id}")
        state.status = "error" if error else "done"
        state.error = error
        state.last_updated = datetime.now(timezone.utc)
        _write_state_unlocked(state)


async def mark_task_cancelled(task_id: str) -> None:
    async with _state_lock:
        state = _read_state_unlocked(task_id)
        if state is None or state.task_id != task_id:
            raise ValueError(f"State not found for task_id={task_id}")
        state.status = "cancelled"
        state.last_updated = datetime.now(timezone.utc)
        _write_state_unlocked(state)
