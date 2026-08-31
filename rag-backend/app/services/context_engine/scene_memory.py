"""context_engine.scene_memory — scene_state persistence + render.

В Фазе 2b scene_state имеет два под-пространства:

    chat.metadata_json["scene_state"] = {
        "explicit": { ... },     # пишет большая LLM через update_scene_state tool
        "drift": {                # пишет DriftDetector (auto, low-confidence)
            "_hints": [...],
            "_ts": "...",
            "_chat_id": "...",
        },
    }

Backwards compatibility: в чатах, созданных до Фазы 2b, scene_state может
храниться в legacy-плоском виде (ключи верхнего уровня — это и есть
explicit). Детектируем это так: если scene_state не содержит ни ключа
`explicit`, ни ключа `drift` — рендерим как раньше (legacy).
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Максимальный размер scene_state JSON (символов). Защищает prompt от раздувания,
# если модель начнёт писать большие значения (например, длинные истории NPC).
_SCENE_STATE_MAX_CHARS = 4 * 1024

# Cap drift hints в prompt — даже если детектор вернул 50, в system_prompt
# уйдёт максимум 8. Остальные остаются в scene_state.drift._hints и могут
# быть прочитаны через API.
_DRIFT_HINTS_PROMPT_CAP = 8


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _is_legacy_flat_scene_state(scene_state: dict[str, Any]) -> bool:
    """Legacy-плоский scene_state: ни `explicit`, ни `drift` ключей.

    Такие данные писал `update_scene_state` tool до Фазы 2b. Чтобы не
    потерять их при чтении, рендерим как есть (plain JSON) — migration
    в новое представление произойдёт при первом успешном merge_explicit.
    """
    return "explicit" not in scene_state and "drift" not in scene_state


def _render_explicit_block(explicit: dict[str, Any]) -> str:
    try:
        text = json.dumps(explicit, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        logger.warning("compose_scene_block: explicit is not JSON-serialisable")
        return ""
    return f"## Текущая сцена\n{text}"


def _render_drift_block(drift: dict[str, Any]) -> str:
    hints = drift.get("_hints") or []
    if not hints:
        return ""
    lines: list[str] = []
    for h in hints[:_DRIFT_HINTS_PROMPT_CAP]:
        if not isinstance(h, dict):
            continue
        conf = h.get("confidence", 0.0)
        try:
            conf_val = float(conf)
        except (TypeError, ValueError):
            conf_val = 0.0
        fact = h.get("fact", "")
        if not isinstance(fact, str):
            fact = str(fact)
        lines.append(f"- [conf={conf_val:.2f}] {fact}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"## Дрейф контекста (авто, может быть ошибочным)\n{body}"


def compose_scene_block(scene_state: dict[str, Any] | None) -> str:
    """Рендерит scene_state в текстовый блок для system_prompt.

    Поддерживает два формата:

    1. **Legacy flat** (до Фазы 2b) — `scene_state` без `explicit`/`drift`.
       Рендерится как JSON верхнего уровня под заголовком `## Текущая сцена`.
    2. **Phase 2b** — два под-пространства. Рендерятся отдельными блоками
       `## Текущая сцена` (explicit) и `## Дрейф контекста` (drift hints).

    Пустой / None / не-dict → пустая строка (блок пропускается).
    Превышение _SCENE_STATE_MAX_CHARS → обрезается с WARNING-меткой.
    """
    if not scene_state:
        return ""
    if not isinstance(scene_state, dict):
        return ""

    if _is_legacy_flat_scene_state(scene_state):
        # Backwards compat: рендерим как раньше.
        try:
            rendered = json.dumps(scene_state, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            logger.warning(
                "compose_scene_block: legacy scene_state is not JSON-serialisable"
            )
            return ""
        block = f"## Текущая сцена\n{rendered}"
    else:
        parts: list[str] = []
        explicit = scene_state.get("explicit")
        if isinstance(explicit, dict) and explicit:
            rendered = _render_explicit_block(explicit)
            if rendered:
                parts.append(rendered)
        drift = scene_state.get("drift")
        if isinstance(drift, dict):
            rendered = _render_drift_block(drift)
            if rendered:
                parts.append(rendered)
        block = "\n\n".join(parts)

    if not block:
        return ""
    if len(block) > _SCENE_STATE_MAX_CHARS:
        block = block[:_SCENE_STATE_MAX_CHARS] + "\n…(truncated)"
        logger.warning(
            "compose_scene_block: scene_state exceeded %d chars, truncated for prompt",
            _SCENE_STATE_MAX_CHARS,
        )
    return block


# ---------------------------------------------------------------------------
# Persistence — read / merge_explicit / write_drift / clear_drift
# ---------------------------------------------------------------------------


async def read_scene_state(chat_id: str, db: AsyncSession) -> dict[str, Any]:
    """Прочитать scene_state из chat.metadata_json.

    Возвращает {} если чат не найден или scene_state отсутствует.
    """
    from app.db.models import Chat

    try:
        chat = await db.get(Chat, _uuid.UUID(chat_id))
    except (ValueError, TypeError):
        return {}
    if chat is None:
        return {}
    return dict(chat.metadata_json.get("scene_state") or {})


async def merge_explicit(
    chat_id: str,
    patch: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Merge patch в scene_state.explicit.

    Семантика:
      - value=None → удалить ключ из explicit.
      - любое иное значение → установить/перезаписать.

    Если scene_state ещё не существует или в legacy-плоском формате,
    мигрируем в новый (старые ключи переезжают в scene_state.explicit).

    Возвращает обновлённый scene_state.
    """
    from app.db.models import Chat

    try:
        chat = await db.get(Chat, _uuid.UUID(chat_id))
    except (ValueError, TypeError):
        return {}
    if chat is None:
        return {}

    current = dict(chat.metadata_json or {})
    scene = dict(current.get("scene_state") or {})

    # Legacy → Phase 2b migration: плоские ключи переезжают в explicit.
    if scene and _is_legacy_flat_scene_state(scene):
        scene = {"explicit": dict(scene)}

    explicit = dict(scene.get("explicit") or {})

    applied: list[str] = []
    removed: list[str] = []
    for key, value in patch.items():
        if not isinstance(key, str) or not key:
            continue
        if value is None:
            if key in explicit:
                explicit.pop(key)
                removed.append(key)
        else:
            explicit[key] = value
            applied.append(key)

    scene["explicit"] = explicit
    current["scene_state"] = scene
    chat.metadata_json = current

    try:
        await db.commit()
        await db.refresh(chat)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scene_memory.merge_explicit: commit failed chat_id=%s: %s",
            chat_id,
            exc,
        )
        await db.rollback()
        return scene

    logger.info(
        "scene_memory.merge_explicit: chat_id=%s applied=%s removed=%s",
        chat_id,
        applied,
        removed,
    )
    return scene


async def write_drift(
    chat_id: str,
    hints: list[dict[str, Any]],
    db: AsyncSession,
) -> None:
    """Записать drift hints в scene_state.drift. Полностью перезаписывает _hints.

    Если scene_state пуст или legacy — создаёт/мигрирует в формат
    {explicit: <legacy or {}>, drift: {_hints: ...}}.
    """
    from app.db.models import Chat

    try:
        chat = await db.get(Chat, _uuid.UUID(chat_id))
    except (ValueError, TypeError):
        return
    if chat is None:
        return

    current = dict(chat.metadata_json or {})
    scene = dict(current.get("scene_state") or {})

    if scene and _is_legacy_flat_scene_state(scene):
        scene = {"explicit": dict(scene)}

    scene["drift"] = {
        "_hints": list(hints),
        "_ts": datetime.now(timezone.utc).isoformat(),
        "_chat_id": chat_id,
    }
    current["scene_state"] = scene
    chat.metadata_json = current

    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scene_memory.write_drift: commit failed chat_id=%s: %s",
            chat_id,
            exc,
        )
        await db.rollback()


async def clear_drift(chat_id: str, db: AsyncSession) -> None:
    """Очистить drift под-пространство (вызывается при accept/reject)."""
    from app.db.models import Chat

    try:
        chat = await db.get(Chat, _uuid.UUID(chat_id))
    except (ValueError, TypeError):
        return
    if chat is None:
        return

    current = dict(chat.metadata_json or {})
    scene = dict(current.get("scene_state") or {})
    if "drift" not in scene:
        return

    scene.pop("drift", None)
    current["scene_state"] = scene
    chat.metadata_json = current

    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "scene_memory.clear_drift: commit failed chat_id=%s: %s",
            chat_id,
            exc,
        )
        await db.rollback()
