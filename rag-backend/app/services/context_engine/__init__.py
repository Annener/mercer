"""context_engine — внутренний модуль сборки chat context.

Публичный API:
- `build_chat_context` — собрать system_prompt + Campaign State + Scene State
- `build_chat_context_with_state` — то же + вернуть state_block для debug
- `build_state_block_only` — только текст Campaign State block
- `compose_scene_block` — рендер scene_state в строку для prompt

Используется из `app.api.chat`, `app.api.pipeline_resume`,
`app.services.pipeline_executor` (раньше шло через фасад
`app.services.effective_context`, теперь — напрямую).
"""
from .assembly import (
    build_chat_context,
    build_chat_context_with_state,
    build_state_block_only,
)
from .scene_memory import compose_scene_block

__all__ = [
    "build_chat_context",
    "build_chat_context_with_state",
    "build_state_block_only",
    "compose_scene_block",
]