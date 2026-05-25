from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


def parse_markdown(path: str) -> dict[str, Any]:
    content = Path(path).read_text(encoding="utf-8")
    metadata: dict[str, Any] = {}
    text = content

    if content.startswith("---"):
        lines = content.splitlines(keepends=True)
        if lines and lines[0].strip() == "---":
            closing_index = next(
                (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
                None,
            )
            if closing_index is not None:
                frontmatter = "".join(lines[1:closing_index])
                try:
                    parsed = yaml.safe_load(frontmatter) or {}
                    if isinstance(parsed, dict):
                        metadata = parsed
                except yaml.YAMLError:
                    logger.warning("Failed to parse Markdown frontmatter: %s", path, exc_info=True)
                text = "".join(lines[closing_index + 1 :])

    return {"text": text.strip(), "metadata": metadata}
