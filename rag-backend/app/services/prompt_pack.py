from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptPack:
    domain_id: str
    description: str
    prompts: dict[str, str]

    def get(self, name: str, default: str = "") -> str:
        return self.prompts.get(name, default)


def format_prompt(template: str, variables: dict[str, Any]) -> str:
    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    normalized = {key: _stringify(value) for key, value in variables.items()}
    return template.format_map(SafeDict(normalized))


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)
