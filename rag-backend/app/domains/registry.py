from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.services.prompt_pack import PromptPack


logger = logging.getLogger(__name__)


class DomainRegistry:
    def __init__(self, domains_path: Path | None = None) -> None:
        self.domains_path = domains_path or Path(__file__).parent
        self._packs: dict[str, PromptPack] = {}

    def load(self) -> None:
        self._packs.clear()
        for prompts_path in sorted(self.domains_path.glob("*/prompts.yaml")):
            try:
                pack = _load_prompt_pack(prompts_path)
            except Exception:
                logger.warning("Failed to load domain prompt pack: %s", prompts_path, exc_info=True)
                continue
            self._packs[pack.domain_id] = pack
            logger.info("Loaded domain prompt pack: domain_id=%s", pack.domain_id)

    def get(self, domain_id: str | None) -> PromptPack:
        if domain_id and domain_id in self._packs:
            return self._packs[domain_id]
        if "default" in self._packs:
            return self._packs["default"]
        return PromptPack(
            domain_id="default",
            description="Default assistant",
            prompts={
                "system": "You are a helpful assistant. Use context when it is relevant.\n\nContext:\n{context}",
                "clarification": "Please clarify: {missing_fields}",
                "planner": "Decide how to answer the user query: {query}",
            },
        )

    def domain_ids(self) -> list[str]:
        return sorted(self._packs)


def _load_prompt_pack(path: Path) -> PromptPack:
    with path.open("r", encoding="utf-8") as prompts_file:
        payload: dict[str, Any] = yaml.safe_load(prompts_file) or {}
    prompts = payload.get("prompts") or {}
    if not isinstance(prompts, dict):
        raise ValueError(f"prompts must be a mapping: {path}")
    return PromptPack(
        domain_id=str(payload["domain_id"]),
        description=str(payload.get("description", "")),
        prompts={str(key): str(value) for key, value in prompts.items()},
    )
