"""context_engine — внутренний модуль сборки chat context.

Публичный API:
- `build_chat_context` — собрать system_prompt + Campaign State + Scene State
- `build_chat_context_with_state` — то же + вернуть state_block для debug
- `build_state_block_only` — только текст Campaign State block
- `compose_scene_block` — рендер scene_state в строку для prompt

Phase 2b:
- `read_scene_state` — прочитать scene_state из chat.metadata_json
- `merge_explicit` — merge patch в scene_state.explicit (от LLM tool)
- `write_drift` — записать drift hints в scene_state.drift (от DriftDetector)
- `clear_drift` — очистить scene_state.drift

Drift loop (Phase 2b/3):
- `DriftLoop` — фоновая петля drift detection с cooldown и idle scan
- `DriftStatusBus` — pub/sub для SSE/poll уведомлений о фазах drift

Используется из `app.api.chat`, `app.api.pipeline_resume`,
`app.services.pipeline_executor`, `app.services.agent_loop`.
"""
from .assembly import (
    build_chat_context,
    build_chat_context_with_state,
    build_state_block_only,
)
from .scene_memory import (
    clear_drift,
    compose_scene_block,
    merge_explicit,
    read_scene_state,
    write_drift,
)
from .status_bus import DriftStatusBus

__all__ = [
    "build_chat_context",
    "build_chat_context_with_state",
    "build_state_block_only",
    "compose_scene_block",
    "read_scene_state",
    "merge_explicit",
    "write_drift",
    "clear_drift",
    "DriftStatusBus",
]
