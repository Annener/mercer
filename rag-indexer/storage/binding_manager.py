from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from shared_contracts.models import VaultBinding


BINDINGS_PATH = Path("/app/state/vault_bindings.json")
TMP_BINDINGS_PATH = BINDINGS_PATH.with_suffix(".json.tmp")

_lock = asyncio.Lock()


async def get_binding(vault_id: str) -> VaultBinding | None:
    async with _lock:
        bindings = _load_bindings()
        binding_data = bindings.get(vault_id)
        if binding_data is None:
            return None
        return VaultBinding.model_validate(binding_data)


async def create_or_get_binding(vault_id: str, embedding_model_id: str, expected_dimensions: int) -> VaultBinding:
    async with _lock:
        bindings = _load_bindings()
        existing = bindings.get(vault_id)
        if existing is not None:
            binding = VaultBinding.model_validate(existing)
            if (
                binding.embedding_model_id != embedding_model_id
                or binding.expected_dimensions != expected_dimensions
            ):
                raise ValueError(
                    "Embedding model binding is immutable; detach and full reindex are required to change it."
                )
            return binding

        binding = VaultBinding(
            vault_id=vault_id,
            embedding_model_id=embedding_model_id,
            expected_dimensions=expected_dimensions,
            locked=False,
            status="unbound",
            chunk_count=0,
        )
        _save_binding_unlocked(binding, bindings)
        return binding


async def lock_binding(vault_id: str) -> None:
    async with _lock:
        bindings = _load_bindings()
        binding_data = bindings.get(vault_id)
        if binding_data is None:
            raise ValueError(f"Vault binding not found for vault_id={vault_id!r}.")
        binding = VaultBinding.model_validate(binding_data)
        binding.locked = True
        binding.status = "bound"
        _save_binding_unlocked(binding, bindings)


async def increment_chunk_count(vault_id: str, delta: int = 1) -> None:
    async with _lock:
        bindings = _load_bindings()
        binding_data = bindings.get(vault_id)
        if binding_data is None:
            raise ValueError(f"Vault binding not found for vault_id={vault_id!r}.")
        binding = VaultBinding.model_validate(binding_data)
        binding.chunk_count = max(binding.chunk_count + delta, 0)
        _save_binding_unlocked(binding, bindings)


async def _save_binding(binding: VaultBinding) -> None:
    async with _lock:
        bindings = _load_bindings()
        _save_binding_unlocked(binding, bindings)


def _load_bindings() -> dict[str, Any]:
    if not BINDINGS_PATH.exists():
        return {}
    with BINDINGS_PATH.open("r", encoding="utf-8") as bindings_file:
        data = json.load(bindings_file)
    if not isinstance(data, dict):
        raise ValueError(f"Binding file {BINDINGS_PATH} must contain a JSON object.")
    return data


def _save_binding_unlocked(binding: VaultBinding, bindings: dict[str, Any]) -> None:
    BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    bindings[binding.vault_id] = binding.model_dump()
    with TMP_BINDINGS_PATH.open("w", encoding="utf-8") as tmp_file:
        json.dump(bindings, tmp_file, ensure_ascii=False, indent=2)
        tmp_file.write("\n")
    TMP_BINDINGS_PATH.replace(BINDINGS_PATH)
