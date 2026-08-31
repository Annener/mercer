"""context_engine.scene_memory — рендер scene_state для system_prompt.

В Фазе 2b здесь появятся `read_scene_state`, `merge_explicit`, `write_drift`,
`clear_drift` для работы с `chat.metadata.scene_state.{explicit,drift}`.
В Фазе 1 — только рендер.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# Максимальный размер scene_state JSON (символов). Защищает prompt от раздувания,
# если модель начнёт писать большие значения (например, длинные истории NPC).
_SCENE_STATE_MAX_CHARS = 4 * 1024


def compose_scene_block(scene_state: dict[str, Any] | None) -> str:
    """Рендерит блок «Текущая сцена» для system_prompt.

    - Пустой / None / не-dict → пустая строка (блок пропускается).
    - Слишком большой JSON (>_SCENE_STATE_MAX_CHARS) → обрезается с WARNING-меткой.
      Полный текст при этом всё равно доступен модели через `chat.metadata.scene_state`
      в read-only (host-controlled) режиме — мы просто не пихаем его целиком в prompt.

    Структура выходного текста (plain text, не JSON-строка, чтобы модель
    читала естественно):

        ## Текущая сцена
        - location: Забытые Королевства, подземелье
        - active_npcs:
          - Бехолдер
          - Культисты Теней
        - current_act: Глава 3 — Падение
    """
    if not scene_state:
        return ""
    if not isinstance(scene_state, dict):
        return ""
    try:
        rendered = json.dumps(scene_state, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        logger.warning(
            "compose_scene_block: scene_state is not JSON-serialisable, skipping"
        )
        return ""
    if len(rendered) > _SCENE_STATE_MAX_CHARS:
        rendered = rendered[:_SCENE_STATE_MAX_CHARS] + "\n…(truncated)"
        logger.warning(
            "compose_scene_block: scene_state exceeded %d chars, truncated for prompt",
            _SCENE_STATE_MAX_CHARS,
        )
    return f"## Текущая сцена\n{rendered}"