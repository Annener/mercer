# Context Engine + Auto-Draft — план реализации

## Назначение документа

Этот документ описывает поэтапный план выноса работы с контекстом в отдельный внутренний модуль `ContextEngine` и добавления фонового drift-detection с auto-draft campaign state.

**Цели:**

1. Стабилизировать обновление контекста (особенно list-полей)
2. Упростить расширение (добавление новых слоёв контекста)
3. Добавить фоновый drift-detection с auto-draft и явным review

**Ключевые решения:**

- Без отдельного sidecar/HTTP-сервиса — internal модуль внутри `rag-backend`
- Drift-модель — по аналогии с `rerank_models`: таблица БД, Settings UI, локальный или внешний провайдер
- Локальная модель по умолчанию: **Qwen2.5-3B-Instruct (Q4_K_M)**, запускается в `pdf-sidecar` (расширяем существующий)
- Drift cooldown: 30 сек
- TTL draft: 3 часа
- Auto-apply **никогда** — только draft + явный review пользователя
- Draft пересоздаётся только если новый drift отличается от текущего draft (content hash)

**Не входит в план:**

- ❌ Sidecar/HTTP-сервис для контекста
- ❌ Auto-apply без review
- ❌ Schema changes (create_field / update_field) в auto-draft
- ❌ file_changes в auto-draft — только по явной кнопке
- ❌ Удаление полей — manual UI

---

## Общая архитектура

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          rag-backend                                     │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    context_engine/ (новый)                        │   │
│  │                                                                  │   │
│  │  assembly.py      ← единая точка сборки system_prompt+state+scene│   │
│  │  scene_memory.py  ← scene_state: explicit (LLM) + drift (auto)   │   │
│  │  drift.py         ← DriftDetector (маленькая локальная модель)   │   │
│  │  draft.py         ← CampaignStateDrafter (большая модель)         │   │
│  │  loop.py          ← Background loop + cooldown 30 сек             │   │
│  │  migration.py     ← Обратная совместимость                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│           │                            ▲                                  │
│           │                            │                                  │
│           ▼                            │                                  │
│  ┌──────────────────┐    ┌────────────────────────┐                    │
│  │ effective_context│    │ update_mode_executor    │                    │
│  │ (фасад)          │    │ + state_patch_context   │                    │
│  └──────────────────┘    └────────────────────────┘                    │
│           │                            ▲                                  │
│           ▼                            │                                  │
│  ┌──────────────────┐    ┌────────────────────────┐                    │
│  │ chat.py /        │    │ api/context_draft.py    │                    │
│  │ pipeline_executor│    │ (GET/POST endpoints)    │                    │
│  └──────────────────┘    └────────────────────────┘                    │
│                                                                          │
│  ┌─────────────────────────────┐    ┌──────────────────────────────┐   │
│  │ providers/drift/            │    │ services/drift_model_service │   │
│  │ host_sidecar.py (default)   │    │ api/settings/drift_models.py │   │
│  │ openai_compatible.py        │    │                               │   │
│  └─────────────────────────────┘    └──────────────────────────────┘   │
│           │                                     │                        │
└───────────┼─────────────────────────────────────┼────────────────────────┘
            │                                     │
            ▼                                     ▼
   ┌──────────────────┐                 ┌──────────────────┐
   │  pdf-sidecar     │                 │  drift_models    │
   │  + POST /drift   │                 │  таблица БД      │
   │  (Qwen2.5-3B)    │                 │  + Settings UI   │
   └──────────────────┘                 └──────────────────┘
```

**Поток данных:**

```
chat turn (user → main LLM → response)
        │
        │ после SSE event "final"
        ▼
[chat.py] → drift_loop.trigger_for_chat(chat_id)
        │
        │ cooldown 30 сек (Redis SETNX)
        ▼
[DriftDetector] → pdf-sidecar /drift → JSON hints
        │
        │ confidence threshold (0.5)
        ▼
[scene_memory.write_drift] → chat.metadata.scene_state.drift
        │
        │ если hints непустые И отличаются от текущего draft
        ▼
[CampaignStateDrafter] → generation_model (большая) → state_patch operations
        │
        ▼
[Redis draft:campaign:{cid}:chat:{chatid}] TTL 3 часа
        │
        ▼
[UI ChatContextBar] badge "Возможные обновления"
        │
        ▼
[Пользователь] Accept / Reject / "Проверить файлы"
        │
        ├── Accept → campaign_state_value_service.apply_patch
        ├── Reject  → удалить Redis-ключ
        └── Check-files → update_mode_executor.start_from_proposal(state_patch_context=...)
```

---

## Карта файлов

### Новые файлы

```
rag-backend/app/services/context_engine/
├── __init__.py          # Публичный API
├── assembly.py          # build_chat_context() — единая точка сборки
├── scene_memory.py      # scene_state: explicit + drift под-пространства
├── drift.py             # DriftDetector
├── draft.py             # CampaignStateDrafter
├── loop.py              # DriftLoop с cooldown
└── migration.py         # Обратная совместимость

rag-backend/app/providers/drift/
├── __init__.py
├── base.py              # DriftProvider интерфейс
├── host_sidecar.py      # Клиент к pdf-sidecar /drift
└── openai_compatible.py # Внешний провайдер

rag-backend/app/services/
└── drift_model_service.py    # CRUD активной модели (как rerank_model_service)

rag-backend/app/api/settings/
└── drift_models.py           # Settings роутер

rag-backend/app/api/
└── context_draft.py          # GET/POST /api/chats/{chat_id}/context-draft/*

rag-backend/migrations/versions/
└── 0013_drift_models.py      # drift_models таблица + seed

rag-backend/app/static/frontend/src/components/chat/
└── ContextDraftCard.tsx      # Карточка draft (по аналогии с UpdateModePanel)

pdf-sidecar/
└── drift.py                  # POST /drift handler + ленивая загрузка модели
```

### Изменённые файлы

```
rag-backend/app/db/models.py                       # + DriftModel ORM
rag-backend/app/main.py                            # + include_router, + drift_loop в lifespan
rag-backend/app/services/effective_context.py       # фасад → context_engine
rag-backend/app/services/agent_loop.py             # scene_state.explicit под-пространство
rag-backend/app/api/chat.py                        # вызов drift_loop после turn-а
rag-backend/app/services/update_mode_executor.py   # + state_patch_context параметр
rag-backend/app/static/frontend/src/components/chat/ChatContextBar.tsx   # badge draft
rag-backend/app/static/frontend/src/components/chat/ChatArea.tsx        # рендер ContextDraftCard
rag-backend/app/static/frontend/src/components/settings/tabs/ModelsTab.tsx # секция Drift Models

pdf-sidecar/main.py                                # + /drift endpoint
pdf-sidecar/start.sh                               # DRIFT_MODEL_PATH env
```

---

## Фаза 1: ContextEngine скелет + рефакторинг

**Цель:** вынести существующую логику сборки контекста в чёткий модуль. Без нового функционала. Все существующие тесты должны проходить без изменений.

### Задачи

1. Создать `rag-backend/app/services/context_engine/` пакет
2. Перенести `_compose_full_system_prompt_text` из `effective_context.py` в `context_engine/assembly.py`
3. Перенести `compose_scene_block` из `effective_context.py` в `context_engine/scene_memory.py`
4. Перенести `_resolve_system_prompt_text` в `context_engine/assembly.py`
5. Перенести `_resolve_campaign_state_block_safe` в `context_engine/assembly.py`
6. Создать `context_engine/migration.py` с односторонними шимами для backward compat
7. Сделать `effective_context.py` тонким фасадом, всё делегирует в `context_engine`
8. Обновить все импорты в `chat.py`, `pipeline_executor.py`, `pipeline_resume.py`

### Файлы

**Новые:**
- `rag-backend/app/services/context_engine/__init__.py` — публичный API
- `rag-backend/app/services/context_engine/assembly.py` — `build_chat_context()`
- `rag-backend/app/services/context_engine/scene_memory.py` — `compose_scene_block()`
- `rag-backend/app/services/context_engine/migration.py` — шимы

**Изменённые:**
- `rag-backend/app/services/effective_context.py` → фасад
- `rag-backend/app/api/chat.py` — импорты через `context_engine`
- `rag-backend/app/services/pipeline_executor.py` — импорты через `context_engine`
- `rag-backend/app/api/pipeline_resume.py` — импорты через `context_engine`

### Публичный API context_engine (после Фазы 1)

```python
# rag-backend/app/services/context_engine/__init__.py
from .assembly import build_chat_context, build_chat_context_with_state, build_state_block_only
from .scene_memory import compose_scene_block, read_scene_state, merge_scene_state_patch

__all__ = [
    "build_chat_context",
    "build_chat_context_with_state",
    "build_state_block_only",
    "compose_scene_block",
    "read_scene_state",
    "merge_scene_state_patch",
]
```

### Критерии готовности

- ✅ Все существующие тесты проходят без изменений
- ✅ `effective_context.py` остаётся как re-export фасад (deprecated, но не удаляется)
- ✅ Никаких изменений в БД, Redis, фронтенде
- ✅ Manual smoke-test: `POST /chat/{id}/send_stream` работает идентично

---

## Фаза 2а: Drift-модель инфраструктура

**Цель:** drift-модель как полноценная сущность рядом с `generation_models`, `embedding_models`, `rerank_models`. Может быть локальной (по умолчанию — Qwen2.5-3B через pdf-sidecar) или внешней (openai_compatible).

### Задачи

1. Расширить `pdf-sidecar` эндпоинтом `POST /drift` (ленивая загрузка модели)
2. Создать ORM-модель `DriftModel` (по аналогии с `RerankModel`)
3. Миграция `0013_drift_models` — таблица + seed (одна активная по умолчанию — host sidecar)
4. `drift_model_service.py` — CRUD активной модели (как `rerank_model_service`)
5. Settings роутер `drift_models.py` — CRUD + activate + check
6. Провайдеры `drift/` — `base.py`, `host_sidecar.py`, `openai_compatible.py`
7. Frontend: секция Drift Models в `ModelsTab.tsx`

### Файлы

**Новые:**
- `rag-backend/migrations/versions/0013_drift_models.py`
- `rag-backend/app/services/drift_model_service.py`
- `rag-backend/app/api/settings/drift_models.py`
- `rag-backend/app/providers/drift/__init__.py`
- `rag-backend/app/providers/drift/base.py`
- `rag-backend/app/providers/drift/host_sidecar.py`
- `rag-backend/app/providers/drift/openai_compatible.py`
- `pdf-sidecar/drift.py`

**Изменённые:**
- `rag-backend/app/db/models.py` — `+ DriftModel`
- `rag-backend/app/main.py` — `+ include_router(drift_models_router)`
- `rag-backend/app/api/settings/__init__.py` — `+ drift_models_router`
- `rag-backend/app/static/frontend/src/components/settings/tabs/ModelsTab.tsx` — Drift Models секция
- `pdf-sidecar/main.py` — `+ /drift` endpoint
- `pdf-sidecar/start.sh` — `+ DRIFT_MODEL_PATH` env

### ORM DriftModel

```python
# rag-backend/app/db/models.py (добавить)
class DriftModel(Base):
    __tablename__ = "drift_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)  # "host_sidecar" | "openai_compatible"
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        Index("uq_drift_models_active", "is_active", unique=True, postgresql_where=(is_active == True)),
    )
```

### Миграция 0013

```python
# alembic upgrade head
def upgrade():
    op.create_table(
        "drift_models",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("model_id", sa.String(128), unique=True, nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("model_name", sa.String(256), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_drift_models_active",
        "drift_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    # Seed: default local model
    op.execute("""
        INSERT INTO drift_models (id, model_id, provider, model_name, is_active, enabled, display_name)
        VALUES (gen_random_uuid(), 'drift-local-default', 'host_sidecar', 'qwen2.5-3b-instruct-q4_k_m', true, true, 'Qwen2.5-3B (local)')
    """)
```

### Провайдер host_sidecar

```python
# rag-backend/app/providers/drift/host_sidecar.py
import httpx
from .base import DriftProvider, DriftUnavailableError, DriftInvalidResponseError

class HostSidecarDriftProvider(DriftProvider):
    def __init__(self, base_url: str, model_name: str, timeout_seconds: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = httpx.Timeout(float(timeout_seconds))

    async def detect_drift(
        self,
        *,
        messages: list[dict[str, str]],  # [{"role": "user|assistant", "content": str}]
        current_state: str,             # скомпилированный Campaign State блок
        schema_hint: str | None = None,  # описание полей для hint generation
    ) -> list[dict]:
        """Вызвать pdf-sidecar /drift, вернуть list of hint dicts."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/drift",
                    json={
                        "model": self.model_name,
                        "messages": messages,
                        "current_state": current_state,
                        "schema_hint": schema_hint,
                    },
                )
                resp.raise_for_status()
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            raise DriftUnavailableError(f"drift sidecar unreachable: {exc}")

        try:
            payload = resp.json()
            hints = payload["hints"]
            if not isinstance(hints, list):
                raise DriftInvalidResponseError("hints must be a list")
            return hints
        except (KeyError, ValueError) as exc:
            raise DriftInvalidResponseError(f"invalid drift response: {exc}")
```

### pdf-sidecar /drift endpoint

```python
# pdf-sidecar/drift.py
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel

from .model_loader import lazy_load_drift_model

router = APIRouter()

class DriftRequest(BaseModel):
    model: str
    messages: list[dict[str, str]]
    current_state: str
    schema_hint: str | None = None

class DriftHint(BaseModel):
    fact: str
    contradicts_field: str | None = None  # field_key
    adds_field: str | None = None         # field_key
    msg_ref: str | None = None            # message index
    confidence: float

class DriftResponse(BaseModel):
    hints: list[DriftHint]

_SYSTEM_PROMPT = """You are a context drift detector. Given recent chat messages and the current campaign state, identify facts that:
1. Contradict the current state (something happened that makes existing state wrong)
2. Add to the current state (new entity, location, event not in state)
3. Are relevant for active list-items (new list item appears)

Output JSON: {"hints": [{"fact": "...", "contradicts_field": "key_or_null", "adds_field": "key_or_null", "msg_ref": "msg_index_or_null", "confidence": 0.0-1.0}]}

Only include hints with confidence >= 0.5. Be conservative — false positives are worse than missed drift."""

@router.post("/drift", response_model=DriftResponse)
async def detect_drift(req: DriftRequest) -> DriftResponse:
    model = await lazy_load_drift_model(req.model)
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.append({
        "role": "user",
        "content": f"## Campaign State:\n{req.current_state}\n\n"
                   f"{'## Schema:\n' + req.schema_hint if req.schema_hint else ''}\n\n"
                   f"## Recent Messages:\n" + "\n".join(
                       f"[{m.get('role', '?')}] {m.get('content', '')}"
                       for m in req.messages
                   )
    })
    raw = await model.complete(messages, json_mode=True, max_tokens=512)
    parsed = json.loads(raw)
    return DriftResponse(**parsed)
```

### Критерии готовности

- ✅ Миграция применяется, таблица создана, seed активная запись
- ✅ `GET /api/settings/models/drift` возвращает список (1 запись — host_sidecar default)
- ✅ `POST /api/settings/models/drift` создаёт запись
- ✅ `POST /api/settings/models/drift/{model_id}/activate` переключает активную
- ✅ `POST /api/settings/models/drift/{model_id}/check` проверяет доступность
- ✅ Frontend `ModelsTab.tsx` показывает секцию Drift Models с CRUD
- ✅ pdf-sidecar `POST /drift` принимает запрос и возвращает hints (manual test)

---

## Фаза 2b: DriftDetector + background loop

**Цель:** запускать drift-detection после каждого сообщения с cooldown 30 сек. Писать hints в `chat.metadata.scene_state.drift`.

### Задачи

1. Расширить `context_engine/scene_memory.py` — добавить под-пространство `drift`
2. Создать `context_engine/drift.py` — `DriftDetector`
3. Создать `context_engine/loop.py` — `DriftLoop` с cooldown 30 сек
4. Интегрировать вызов `drift_loop.trigger_for_chat` в `chat.py` после финального SSE event
5. Зарегистрировать `drift_loop.run_idle_scan` в FastAPI lifespan

### Файлы

**Новые:**
- `rag-backend/app/services/context_engine/drift.py`
- `rag-backend/app/services/context_engine/loop.py`

**Изменённые:**
- `rag-backend/app/services/context_engine/scene_memory.py` — `+ write_drift`, `+ clear_drift`
- `rag-backend/app/services/agent_loop.py` — `update_scene_state` пишет в `scene_state.explicit`
- `rag-backend/app/services/context_engine/assembly.py` — `compose_scene_block` рендерит обе секции
- `rag-backend/app/api/chat.py` — вызов `drift_loop.trigger_for_chat` после turn-а
- `rag-backend/app/main.py` — старт `drift_loop.run_idle_scan` в lifespan

### scene_state структура

```python
# chat.metadata_json
{
    "scene_state": {
        "explicit": {                          # пишет большая LLM через update_scene_state tool
            "current_location": "Таверна",
            "active_npcs": ["Бехолдер"],
            "current_act": "Глава 3",
        },
        "drift": {                             # пишет DriftDetector (auto, low-confidence)
            "_hints": [
                {
                    "fact": "Дракон помирился с нами",
                    "contradicts_field": None,
                    "adds_field": "current_allies",
                    "msg_ref": "msg-uuid-or-index",
                    "confidence": 0.85,
                },
            ],
            "_ts": "2026-08-31T18:00:00Z",
            "_chat_id": "uuid",
        }
    }
}
```

### scene_memory.py

```python
# rag-backend/app/services/context_engine/scene_memory.py
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SCENE_STATE_MAX_CHARS = 4 * 1024  # лимит для prompt (как раньше)


def compose_scene_block(scene_state: dict[str, Any] | None) -> str:
    """Рендерит блок «Текущая сцена» + «Дрейф контекста» для system_prompt.

    Пустой / None → пустая строка.
    Превышение _SCENE_STATE_MAX_CHARS → обрезается с WARNING-меткой.
    """
    if not scene_state or not isinstance(scene_state, dict):
        return ""

    explicit = scene_state.get("explicit") or {}
    drift = scene_state.get("drift") or {}
    hints = drift.get("_hints") or []

    parts = []

    if explicit:
        try:
            explicit_text = json.dumps(explicit, ensure_ascii=False, indent=2)
            parts.append(f"## Текущая сцена\n{explicit_text}")
        except (TypeError, ValueError):
            logger.warning("compose_scene_block: explicit is not JSON-serialisable, skipping")

    if hints:
        try:
            hint_lines = []
            for h in hints[:8]:  # cap drift hints в prompt
                conf = h.get("confidence", 0.0)
                fact = h.get("fact", "")
                hint_lines.append(f"- [conf={conf:.2f}] {fact}")
            drift_text = "\n".join(hint_lines)
            parts.append(f"## Дрейф контекста (авто, может быть ошибочным)\n{drift_text}")
        except Exception as exc:
            logger.warning("compose_scene_block: drift hints render failed: %s", exc)

    full = "\n\n".join(parts)
    if len(full) > _SCENE_STATE_MAX_CHARS:
        full = full[:_SCENE_STATE_MAX_CHARS] + "\n…(truncated)"
        logger.warning(
            "compose_scene_block: scene_state exceeded %d chars, truncated for prompt",
            _SCENE_STATE_MAX_CHARS,
        )
    return full


async def read_scene_state(chat_id: str, db: AsyncSession) -> dict[str, Any]:
    """Прочитать scene_state из chat.metadata_json. Возвращает {} если нет."""
    from app.db.models import Chat
    try:
        chat = await db.get(Chat, _uuid.UUID(chat_id))
    except (ValueError, TypeError):
        return {}
    if chat is None:
        return {}
    return dict(chat.metadata_json.get("scene_state") or {})


async def merge_explicit(chat_id: str, patch: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    """Мердж explicit patch (от update_scene_state tool) с существующим scene_state."""
    from app.db.models import Chat
    chat = await db.get(Chat, _uuid.UUID(chat_id))
    if chat is None:
        return {}

    current = dict(chat.metadata_json or {})
    scene = dict(current.get("scene_state") or {})
    explicit = dict(scene.get("explicit") or {})

    applied: list[str] = []
    removed: list[str] = []
    for key, value in patch.items():
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
    await db.commit()
    await db.refresh(chat)
    return scene


async def write_drift(chat_id: str, hints: list[dict[str, Any]], db: AsyncSession) -> None:
    """Записать drift hints в scene_state.drift. Перезаписывает _hints полностью."""
    from app.db.models import Chat
    chat = await db.get(Chat, _uuid.UUID(chat_id))
    if chat is None:
        return

    current = dict(chat.metadata_json or {})
    scene = dict(current.get("scene_state") or {})
    scene["drift"] = {
        "_hints": hints,
        "_ts": datetime.now(timezone.utc).isoformat(),
        "_chat_id": chat_id,
    }
    current["scene_state"] = scene
    chat.metadata_json = current
    await db.commit()


async def clear_drift(chat_id: str, db: AsyncSession) -> None:
    """Очистить drift под-пространство (при accept/reject)."""
    from app.db.models import Chat
    chat = await db.get(Chat, _uuid.UUID(chat_id))
    if chat is None:
        return

    current = dict(chat.metadata_json or {})
    scene = dict(current.get("scene_state") or {})
    scene.pop("drift", None)
    current["scene_state"] = scene
    chat.metadata_json = current
    await db.commit()
```

### drift.py

```python
# rag-backend/app/services/context_engine/drift.py
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.drift.base import DriftProvider
from app.providers.drift.host_sidecar import HostSidecarDriftProvider
from app.providers.drift.openai_compatible import OpenAICompatibleDriftProvider
from app.services.campaign_state_compiler import compile_campaign_state
from app.services.campaign_state_value_service import campaign_state_value_service
from app.services.drift_model_service import drift_model_service
from app.services.settings_service import settings_service
from .scene_memory import write_drift

logger = logging.getLogger(__name__)

_DRIFT_CONFIDENCE_THRESHOLD_KEY = "drift.confidence_threshold"
_DRIFT_MAX_MESSAGES_KEY = "drift.max_messages"
_DRIFT_DEFAULT_CONFIDENCE_THRESHOLD = 0.5
_DRIFT_DEFAULT_MAX_MESSAGES = 10


class DriftDetector:
    """Детектор рассинхрона между chat messages и campaign state."""

    def __init__(self, db_factory, redis_client):
        self.db_factory = db_factory
        self.redis = redis_client

    async def detect(self, chat_id: str) -> list[dict[str, Any]] | None:
        """Запустить drift-detection для одного чата.

        Возвращает hints (list of dict) если успешно, None если пропущено (cooldown/disabled).
        """
        async with self.db_factory() as db:
            # 1. Прочитать активную drift-модель
            try:
                drift_config = await drift_model_service.get_active_model(db)
            except Exception as exc:
                logger.warning("drift: no active drift model: %s", exc)
                return None

            # 2. Прочитать последние N сообщений
            max_messages = await self._get_max_messages(db)
            messages = await self._read_last_messages(chat_id, db, n=max_messages)
            if not messages:
                return None

            # 3. Прочитать current campaign state
            from app.db.models import Chat
            chat = await db.get(Chat, chat_id)
            if chat is None or not chat.campaign_id:
                return None

            try:
                version = await campaign_state_value_service.get_active_state(
                    db, chat.campaign_id
                )
                fields = await campaign_state_value_service.list_enabled_fields_ordered(
                    db, chat.campaign_id
                )
                block = compile_campaign_state(version, fields, budget_tokens=2000)
                current_state_text = block.text or "(empty state)"
            except Exception as exc:
                logger.warning("drift: failed to compile state: %s", exc)
                current_state_text = "(failed to compile state)"

            # 4. Создать провайдер
            provider = self._build_provider(drift_config)
            if provider is None:
                return None

            # 5. Вызвать провайдер
            try:
                hints_raw = await provider.detect_drift(
                    messages=[
                        {"role": m["role"], "content": m["content"]}
                        for m in messages
                    ],
                    current_state=current_state_text,
                    schema_hint=None,  # TODO: добавить если нужен
                )
            except Exception as exc:
                logger.warning("drift: provider failed: %s", exc)
                return None

            # 6. Фильтрация по threshold
            threshold = await self._get_confidence_threshold(db)
            hints = [h for h in hints_raw if h.get("confidence", 0.0) >= threshold]
            if not hints:
                logger.info("drift: no hints above threshold chat_id=%s", chat_id)
                return []

            # 7. Записать в scene_state.drift
            await write_drift(chat_id, hints, db)
            logger.info(
                "drift: %d hints written chat_id=%s threshold=%.2f",
                len(hints), chat_id, threshold,
            )
            return hints

    async def _read_last_messages(self, chat_id: str, db: AsyncSession, *, n: int) -> list[dict]:
        from sqlalchemy import select
        from app.db.models import Message
        stmt = (
            select(Message)
            .where(Message.chat_id == _uuid.UUID(chat_id))
            .order_by(Message.created_at.desc())
            .limit(n)
        )
        result = await db.execute(stmt)
        msgs = list(result.scalars().all())
        return [{"role": m.role, "content": m.content} for m in reversed(msgs)]

    def _build_provider(self, drift_config):
        provider_name = drift_config.provider
        if provider_name == "host_sidecar":
            return HostSidecarDriftProvider(
                base_url=drift_config.base_url or "http://host.docker.internal:8765",
                model_name=drift_config.model_name,
                timeout_seconds=drift_config.timeout_seconds,
            )
        if provider_name == "openai_compatible":
            return OpenAICompatibleDriftProvider(
                base_url=drift_config.base_url,
                model_name=drift_config.model_name,
                api_key=drift_config.api_key,  # decrypted
                timeout_seconds=drift_config.timeout_seconds,
            )
        logger.warning("drift: unknown provider=%s", provider_name)
        return None

    async def _get_confidence_threshold(self, db):
        try:
            return await settings_service.get(_DRIFT_CONFIDENCE_THRESHOLD_KEY, db) or _DRIFT_DEFAULT_CONFIDENCE_THRESHOLD
        except Exception:
            return _DRIFT_DEFAULT_CONFIDENCE_THRESHOLD

    async def _get_max_messages(self, db):
        try:
            return await settings_service.get(_DRIFT_MAX_MESSAGES_KEY, db) or _DRIFT_DEFAULT_MAX_MESSAGES
        except Exception:
            return _DRIFT_DEFAULT_MAX_MESSAGES


import uuid as _uuid  # noqa: E402  (для chat_id conversion)
```

### loop.py

```python
# rag-backend/app/services/context_engine/loop.py
import asyncio
import logging
from typing import Any

import redis.asyncio as aioredis

from .drift import DriftDetector

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 30
_COOLDOWN_KEY = "drift:cooldown:{chat_id}"


class DriftLoop:
    """Background loop с cooldown для drift-detection.

    Cooldown: не чаще чем раз в 30 сек для одного чата.
    Idle scan: каждые 60 сек проверяет 'chat:dirty' ключи в Redis.
    """

    def __init__(self, detector: DriftDetector, redis: aioredis.Redis):
        self.detector = detector
        self.redis = redis
        self._idle_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()

    async def trigger_for_chat(self, chat_id: str) -> None:
        """Fire-and-forget вызов drift для чата. Cooldown через Redis SETNX."""
        # Cooldown check
        key = _COOLDOWN_KEY.format(chat_id=chat_id)
        try:
            acquired = await self.redis.set(key, "1", ex=_COOLDOWN_SECONDS, nx=True)
        except Exception as exc:
            logger.warning("drift_loop: redis setnx failed: %s", exc)
            acquired = True  # fallback: пропускаем cooldown

        if not acquired:
            logger.debug("drift_loop: cooldown active for chat_id=%s, skip", chat_id)
            return

        # Mark as dirty для idle-scan fallback
        try:
            await self.redis.sadd("drift:dirty", chat_id)
        except Exception as exc:
            logger.warning("drift_loop: redis sadd failed: %s", exc)

        # Fire-and-forget task
        asyncio.create_task(self._run_detect(chat_id))

    async def _run_detect(self, chat_id: str) -> None:
        try:
            hints = await self.detector.detect(chat_id)
            if hints:
                # Триггерим drafter (Фаза 3)
                from .draft import CampaignStateDrafter
                # NOTE: drafter создаётся lazily в Фазе 3, пока None
                # drafter = getattr(app.state, "drafter", None)
                # if drafter:
                #     await drafter.plan_draft(chat_id)
                pass
        except Exception as exc:
            logger.exception("drift_loop: detect failed for chat_id=%s: %s", chat_id, exc)

    async def run_idle_scan(self) -> None:
        """Каждые 60 сек сканирует drift:dirty и запускает detect для каждого."""
        while not self._shutdown.is_set():
            try:
                dirty_ids = await self.redis.smembers("drift:dirty")
                for chat_id in dirty_ids:
                    await self.trigger_for_chat(chat_id)
            except Exception as exc:
                logger.warning("drift_loop: idle_scan failed: %s", exc)
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    def shutdown(self) -> None:
        self._shutdown.set()
        if self._idle_task:
            self._idle_task.cancel()
```

### chat.py integration

```python
# rag-backend/app/api/chat.py — в plain_stream после финального SSE event
# (после yield AgentEvent(type="final", ...))

# Триггерим drift-detection (fire-and-forget, с cooldown)
try:
    drift_loop = request.app.state.drift_loop
    if drift_loop:
        await drift_loop.trigger_for_chat(str(chat.id))
except Exception as exc:
    logger.warning("plain_stream: drift trigger failed: %s", exc)
```

### main.py lifespan

```python
# rag-backend/app/main.py lifespan
async def lifespan(app: FastAPI):
    setup_logging("backend")
    await run_migrations()
    setup_logging("backend")
    # ... existing setup ...

    # Drift loop
    from app.services.context_engine.drift import DriftDetector
    from app.services.context_engine.loop import DriftLoop

    redis_client = app.state.redis
    session_factory = SessionLocal  # async session factory

    detector = DriftDetector(db_factory=session_factory, redis_client=redis_client)
    drift_loop = DriftLoop(detector=detector, redis=redis_client)
    app.state.drift_loop = drift_loop

    drift_loop._idle_task = asyncio.create_task(drift_loop.run_idle_scan())
    logger.info("Drift loop started")

    try:
        yield
    finally:
        drift_loop.shutdown()
        # ... existing cleanup ...
```

### Критерии готовности

- ✅ `chat.metadata.scene_state.drift` заполняется после turn-а (manual smoke-test)
- ✅ Cooldown работает: 2 turn-а подряд → drift вызывается только 1 раз в 30 сек
- ✅ scene_state.explicit (от update_scene_state tool) не перезаписывается drift
- ✅ Prompt рендерит обе секции с разными заголовками
- ✅ Если drift провайдер недоступен — логируется warning, chat не падает
- ✅ Settings: `drift.confidence_threshold`, `drift.max_messages` читаются из platform_settings

---

## Фаза 3: CampaignStateDrafter

**Цель:** планировать auto-draft для campaign state, используя drift + последние сообщения. Большая модель.

### Задачи

1. Создать `context_engine/draft.py` — `CampaignStateDrafter`
2. Логика пересоздания draft (только если новый drift отличается от текущего)
3. Сохранение в Redis `draft:campaign:{campaign_id}:chat:{chat_id}`, TTL 3 часа
4. Hook в `loop.py::_run_detect` — после drift срабатывает drafter

### Файлы

**Новые:**
- `rag-backend/app/services/context_engine/draft.py`

**Изменённые:**
- `rag-backend/app/services/context_engine/loop.py` — вызов drafter после drift

### draft.py

```python
# rag-backend/app/services/context_engine/draft.py
import hashlib
import json
import logging
import uuid as _uuid
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.generation.base import GenerationProvider
from app.services.campaign_state_compiler import compile_campaign_state
from app.services.campaign_state_value_service import campaign_state_value_service
from app.services.scene_memory import read_scene_state

logger = logging.getLogger(__name__)

_DRAFT_REDIS_KEY = "draft:campaign:{campaign_id}:chat:{chat_id}"
_DRAFT_TTL_SECONDS = 3 * 60 * 60  # 3 часа

_SYSTEM_PROMPT = """You are a Campaign State drafter. Given recent chat messages, current campaign state, and detected drift hints, propose MINIMAL state_patch operations to update the campaign state.

Allowed operations (state_patch only, NO schema changes, NO file changes):
- replace_single {field_key, text, reason, source_refs}
- clear_single {field_key, reason}
- add_list_item {field_key, text, reason, source_refs}
- update_list_item {field_key, item_key, text, reason}
- resolve_list_item {field_key, item_key, reason}
- remove_list_item {field_key, item_key, reason}

Output JSON: {"state_patch": [{"type": "...", "field_key": "...", ...}], "summary": "short user-facing description"}

Rules:
- Be conservative — only propose what is clearly supported by drift hints.
- NEVER propose schema changes (create_field/update_field) — too risky without user review.
- NEVER propose file_changes — handled separately.
- If no clear updates are needed, return {"state_patch": [], "summary": "No changes needed"}.
"""


class CampaignStateDrafter:
    """Планирует draft campaign state на основе drift + messages."""

    def __init__(self, db_factory, redis_client, generation_provider_factory):
        self.db_factory = db_factory
        self.redis = redis_client
        self.generation_provider_factory = generation_provider_factory

    async def plan_draft(self, chat_id: str) -> dict | None:
        """Спланировать draft. Возвращает draft dict или None если пропущено."""
        async with self.db_factory() as db:
            from app.db.models import Chat
            try:
                chat = await db.get(Chat, _uuid.UUID(chat_id))
            except (ValueError, TypeError):
                return None
            if chat is None or not chat.campaign_id:
                return None

            campaign_id = str(chat.campaign_id)

            # 1. Прочитать drift из scene_state
            scene_state = await read_scene_state(chat_id, db)
            drift = scene_state.get("drift") or {}
            hints = drift.get("_hints") or []
            if not hints:
                logger.debug("draft: no drift hints, skip chat_id=%s", chat_id)
                return None

            # 2. Сравнить с существующим draft — если drift не изменился, skip
            new_drift_hash = self._hash_hints(hints)
            redis_key = _DRAFT_REDIS_KEY.format(campaign_id=campaign_id, chat_id=chat_id)
            existing = await self._read_existing(redis_key)
            if existing and existing.get("drift_hash") == new_drift_hash:
                logger.debug("draft: drift unchanged, skip chat_id=%s", chat_id)
                return existing

            # 3. Прочитать last messages + state
            messages = await self._read_last_messages(chat_id, db)
            try:
                version = await campaign_state_value_service.get_active_state(
                    db, chat.campaign_id
                )
                fields = await campaign_state_value_service.list_enabled_fields_ordered(
                    db, chat.campaign_id
                )
                block = compile_campaign_state(version, fields, budget_tokens=2000)
                state_text = block.text or "(empty state)"
            except Exception as exc:
                logger.warning("draft: state compile failed: %s", exc)
                return None

            # 4. Вызвать большую модель
            provider = self.generation_provider_factory()
            if provider is None:
                logger.warning("draft: no generation provider available")
                return None

            user_prompt = (
                f"## Campaign State:\n{state_text}\n\n"
                f"## Drift Hints:\n" + json.dumps(hints, ensure_ascii=False, indent=2) + "\n\n"
                f"## Recent Messages:\n" + "\n".join(
                    f"[{m['role']}] {m['content']}" for m in messages
                )
            )

            try:
                response = await provider.generate_complete(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    json_mode=True,
                    max_tokens=2000,
                )
            except Exception as exc:
                logger.warning("draft: generation failed: %s", exc)
                return None

            # 5. Парсинг и сохранение
            try:
                parsed = json.loads(response)
                state_patch = parsed.get("state_patch", [])
                summary = parsed.get("summary", "")
            except (ValueError, KeyError) as exc:
                logger.warning("draft: parse failed: %s", exc)
                return None

            if not state_patch:
                logger.info("draft: empty patch from model, skip chat_id=%s", chat_id)
                return None

            draft = {
                "chat_id": chat_id,
                "campaign_id": campaign_id,
                "state_patch": state_patch,
                "summary": summary,
                "drift_hash": new_drift_hash,
                "drift_hints": hints,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=_DRAFT_TTL_SECONDS)
                ).isoformat(),
            }

            # 6. Сохранить в Redis
            await self.redis.setex(
                redis_key, _DRAFT_TTL_SECONDS, json.dumps(draft, ensure_ascii=False)
            )
            logger.info(
                "draft: saved %d ops for chat_id=%s campaign_id=%s",
                len(state_patch), chat_id, campaign_id,
            )
            return draft

    def _hash_hints(self, hints: list[dict]) -> str:
        canonical = json.dumps(hints, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    async def _read_existing(self, redis_key: str) -> dict | None:
        try:
            raw = await self.redis.get(redis_key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("draft: redis read failed: %s", exc)
            return None

    async def _read_last_messages(self, chat_id, db):
        from sqlalchemy import select
        from app.db.models import Message
        stmt = (
            select(Message)
            .where(Message.chat_id == _uuid.UUID(chat_id))
            .order_by(Message.created_at.desc())
            .limit(10)
        )
        result = await db.execute(stmt)
        msgs = list(result.scalars().all())
        return [{"role": m.role, "content": m.content} for m in reversed(msgs)]
```

### loop.py integration

```python
# rag-backend/app/services/context_engine/loop.py — расширить _run_detect
async def _run_detect(self, chat_id: str) -> None:
    try:
        hints = await self.detector.detect(chat_id)
        if hints:
            # Триггерим drafter
            from .draft import CampaignStateDrafter
            drafter = getattr(self, "drafter", None)
            if drafter:
                await drafter.plan_draft(chat_id)
    except Exception as exc:
        logger.exception("drift_loop: detect+draft failed for chat_id=%s: %s", chat_id, exc)
```

### main.py lifespan — добавить drafter

```python
# rag-backend/app/main.py lifespan — расширить
from app.services.context_engine.draft import CampaignStateDrafter

def generation_provider_factory():
    return settings_service.get_active_provider()  # GenerationProvider instance

drafter = CampaignStateDrafter(
    db_factory=session_factory,
    redis_client=redis_client,
    generation_provider_factory=generation_provider_factory,
)
drift_loop.drafter = drafter
app.state.drafter = drafter
```

### Критерии готовности

- ✅ После drift с непустыми hints — Redis-ключ `draft:campaign:{cid}:chat:{chatid}` появляется
- ✅ TTL = 3 часа
- ✅ Если новый drift hash совпадает с существующим — draft не пересоздаётся
- ✅ Draft содержит только state_patch operations (НЕ field_changes, НЕ file_changes)
- ✅ Если большая модель недоступна — warning, draft не создаётся

---

## Фаза 4: API + UI

**Цель:** API для работы с draft, UI карточка `ContextDraftCard` в окне чата.

### Задачи

1. `GET /api/chats/{chat_id}/context-draft` — получить draft
2. `POST /api/chats/{chat_id}/context-draft/accept` — применить state_patch
3. `POST /api/chats/{chat_id}/context-draft/reject` — удалить
4. `POST /api/chats/{chat_id}/context-draft/check-files` — запустить Update Mode с state_patch_context (см. Фазу 5)
5. `ContextDraftCard.tsx` — UI компонент по аналогии с `UpdateModePanel`
6. Интеграция в `ChatContextBar.tsx` (badge) и `ChatArea.tsx` (рендер карточки)

### Файлы

**Новые:**
- `rag-backend/app/api/context_draft.py`
- `rag-backend/app/static/frontend/src/components/chat/ContextDraftCard.tsx`

**Изменённые:**
- `rag-backend/app/main.py` — `+ include_router(context_draft_router)`
- `rag-backend/app/static/frontend/src/api/client.ts` — `+ getContextDraft`, `+ acceptContextDraft`, etc.
- `rag-backend/app/static/frontend/src/components/chat/ChatContextBar.tsx` — badge
- `rag-backend/app/static/frontend/src/components/chat/ChatArea.tsx` — рендер карточки

### context_draft.py

```python
# rag-backend/app/api/context_draft.py
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Chat
from app.services.campaign_state_value_service import campaign_state_value_service
from shared_contracts.models import CampaignStatePatchOperation, CampaignStatePatchRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chats/{chat_id}/context-draft", tags=["context-draft"])


@router.get("")
async def get_context_draft(chat_id: str, request: Request):
    """Получить текущий draft для чата."""
    redis = request.app.state.redis
    key = f"draft:campaign:{{campaign_id}}:chat:{chat_id}"
    raw = await redis.get(key)
    if raw is None:
        return {"draft": None}
    return {"draft": json.loads(raw)}


@router.post("/accept")
async def accept_context_draft(chat_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Применить draft: state_patch operations + очистить drift."""
    redis = request.app.state.redis
    chat = await db.get(Chat, _uuid.UUID(chat_id))
    if chat is None or not chat.campaign_id:
        raise HTTPException(404, "chat_not_found")

    redis_key = f"draft:campaign:{chat.campaign_id}:chat:{chat_id}"
    raw = await redis.get(redis_key)
    if raw is None:
        raise HTTPException(404, "draft_not_found")
    draft = json.loads(raw)

    # Применяем state_patch
    operations = [CampaignStatePatchOperation(**op) for op in draft["state_patch"]]
    try:
        version = await campaign_state_value_service.get_active_state(db, chat.campaign_id)
        patch_req = CampaignStatePatchRequest(
            base_state_version=version.summary.state_version,
            config_version=version.summary.config_version,
            operations=operations,
        )
        result = await campaign_state_value_service.apply_patch(db, chat.campaign_id, patch_req)
    except Exception as exc:
        logger.warning("accept draft failed: %s", exc)
        raise HTTPException(409, f"apply_failed: {exc}")

    # Очищаем draft и drift
    await redis.delete(redis_key)
    from app.services.context_engine.scene_memory import clear_drift
    await clear_drift(chat_id, db)

    # Audit log
    audit = AuditLog(
        action="context_draft_accepted",
        entity_type="chat",
        entity_id=chat_id,
        payload={
            "campaign_id": str(chat.campaign_id),
            "applied_state_version": result.state_version,
            "operations_count": len(operations),
        },
    )
    db.add(audit)
    await db.commit()

    return {"applied_state_version": result.state_version, "operations_count": len(operations)}


@router.post("/reject")
async def reject_context_draft(chat_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Отклонить draft: удалить из Redis, очистить drift."""
    redis = request.app.state.redis
    chat = await db.get(Chat, _uuid.UUID(chat_id))
    if chat is None:
        raise HTTPException(404, "chat_not_found")
    if not chat.campaign_id:
        raise HTTPException(422, "campaign_required")

    redis_key = f"draft:campaign:{chat.campaign_id}:chat:{chat_id}"
    await redis.delete(redis_key)

    from app.services.context_engine.scene_memory import clear_drift
    await clear_drift(chat_id, db)

    audit = AuditLog(
        action="context_draft_rejected",
        entity_type="chat",
        entity_id=chat_id,
        payload={"campaign_id": str(chat.campaign_id)},
    )
    db.add(audit)
    await db.commit()

    return {"status": "rejected"}


@router.post("/check-files")
async def check_files_after_draft(chat_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Запустить Update Mode с принятыми state_patch как контекстом (Фаза 5)."""
    redis = request.app.state.redis
    chat = await db.get(Chat, _uuid.UUID(chat_id))
    if chat is None or not chat.campaign_id:
        raise HTTPException(404, "chat_not_found")

    redis_key = f"draft:campaign:{chat.campaign_id}:chat:{chat_id}"
    raw = await redis.get(redis_key)
    if raw is None:
        raise HTTPException(404, "draft_not_found")
    draft = json.loads(raw)

    # Создаём Update Mode session с state_patch_context
    from app.services.update_mode_executor import UpdateModeExecutor
    from app.services.indexer_client import indexer_client
    from app.services.update_mode_store import update_mode_store
    from shared_contracts.models import ContextUpdateProposal, ContextFieldChange

    proposal = ContextUpdateProposal(
        field_changes=[],
        state_patch=draft["state_patch"],
        file_changes=[],  # Будет сгенерирован большой моделью с state_patch_context
        confidence=1.0,  # Уже принято пользователем
        reason=draft["summary"],
    )

    executor = UpdateModeExecutor(db=db, store=update_mode_store, indexer_client=indexer_client)
    session = await executor.start_from_proposal(
        chat_id=chat_id,
        redis=redis,
        proposal=proposal,
        state_patch_context=draft["state_patch"],
    )

    audit = AuditLog(
        action="context_draft_check_files",
        entity_type="chat",
        entity_id=chat_id,
        payload={"session_id": session.session_id, "campaign_id": str(chat.campaign_id)},
    )
    db.add(audit)
    await db.commit()

    return {"session_id": session.session_id}
```

### ContextDraftCard.tsx (скелет)

```tsx
// rag-backend/app/static/frontend/src/components/chat/ContextDraftCard.tsx
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';

interface Props {
  chatId: string;
  draft: ContextDraft;
  onClose: () => void;
}

export function ContextDraftCard({ chatId, draft, onClose }: Props) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  const acceptMutation = useMutation({
    mutationFn: () => api.acceptContextDraft(chatId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['context-draft', chatId] });
      onClose();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => api.rejectContextDraft(chatId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['context-draft', chatId] });
      onClose();
    },
  });

  const checkFilesMutation = useMutation({
    mutationFn: () => api.checkFilesFromContextDraft(chatId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['update-mode-session', chatId] });
      onClose();
    },
  });

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 p-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-amber-900 dark:text-amber-100">
            Контекст требует обновления ({draft.state_patch.length} операций)
          </h3>
          <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
            {draft.summary}
          </p>
        </div>
        <button onClick={onClose} className="text-amber-700">×</button>
      </div>

      <button
        onClick={() => setExpanded(!expanded)}
        className="mt-2 text-sm text-amber-700 underline"
      >
        {expanded ? 'Скрыть детали' : 'Показать детали'}
      </button>

      {expanded && (
        <ul className="mt-2 space-y-1 text-sm">
          {draft.state_patch.map((op, i) => (
            <li key={i} className="border-l-2 border-amber-300 pl-2">
              <span className="font-mono text-xs">{op.type}</span>{' '}
              <span className="font-mono text-xs">[{op.field_key}]</span>
              {op.text && <div className="text-xs opacity-75">{op.text}</div>}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => acceptMutation.mutate()}
          disabled={acceptMutation.isPending}
          className="px-3 py-1 rounded bg-amber-600 text-white text-sm hover:bg-amber-700"
        >
          Применить
        </button>
        <button
          onClick={() => rejectMutation.mutate()}
          disabled={rejectMutation.isPending}
          className="px-3 py-1 rounded border border-amber-600 text-amber-700 text-sm hover:bg-amber-100"
        >
          Отклонить
        </button>
        <button
          onClick={() => checkFilesMutation.mutate()}
          disabled={checkFilesMutation.isPending}
          className="px-3 py-1 rounded border border-amber-600 text-amber-700 text-sm hover:bg-amber-100"
        >
          Применить и проверить файлы
        </button>
      </div>
    </div>
  );
}
```

### Критерии готовности

- ✅ `GET /api/chats/{chat_id}/context-draft` возвращает draft (или null)
- ✅ `POST /accept` применяет state_patch, пишет AuditLog, очищает drift
- ✅ `POST /reject` удаляет draft, очищает drift, пишет AuditLog
- ✅ `POST /check-files` создаёт Update Mode session (через state_patch_context из Фазы 5)
- ✅ `ChatContextBar` показывает badge когда draft есть
- ✅ `ContextDraftCard` рендерится в `ChatArea` рядом с `UpdateModePanel`
- ✅ Все три кнопки работают, optimistic updates в TanStack Query

---

## Фаза 5: Update Mode с state_patch_context

**Цель:** file-check кнопка передаёт принятые state_patch как обязательный контекст в Update Mode.

### Задачи

1. Расширить `UpdateModeExecutor.start_from_proposal` параметром `state_patch_context`
2. Расширить `UpdateModeExecutor.start` параметром `state_patch_context`
3. Если параметр задан: LLM получает инструкцию "state_patch уже применён", генерирует только file_changes
4. Тесты для нового flow

### Файлы

**Изменённые:**
- `rag-backend/app/services/update_mode_executor.py` — `+ state_patch_context` параметр
- `rag-backend/app/services/update_mode_executor.py` — `_build_llm_prompt` учитывает контекст

### Правки в update_mode_executor.py

```python
# rag-backend/app/services/update_mode_executor.py — расширить start_from_proposal
async def start_from_proposal(
    self,
    *,
    chat_id: str,
    redis: aioredis.Redis,
    proposal: ContextUpdateProposal,
    state_patch_context: list[dict] | None = None,  # НОВОЕ
) -> UpdateModeSession:
    """Создать Update Mode session из proposal.

    Если state_patch_context задан — генерируются ТОЛЬКО file_changes,
    state_patch операции не генерируются повторно.
    """
    # ... existing validation ...

    if state_patch_context:
        # Пропускаем state_patch генерацию, контекст уже применён
        state_patch_operations = []
        state_field_snapshot = await self._build_field_snapshot(db, chat_id)
    else:
        # Стандартный flow с state_patch генерацией
        state_patch_operations, state_field_snapshot = await self._generate_state_patch(...)

    # File changes всегда генерируются, но с учётом state_patch_context
    file_changes = await self._generate_file_changes(
        db=db,
        chat_id=chat_id,
        note=proposal.reason or "",
        state_patch_context=state_patch_context,  # передаётся в prompt
    )

    # ... existing resolve → session creation ...


async def _generate_file_changes(
    self,
    *,
    db: AsyncSession,
    chat_id: str,
    note: str,
    state_patch_context: list[dict] | None = None,
) -> list[UpdateModeIntent]:
    """Сгенерировать file_changes с учётом state_patch_context (если задан)."""
    # ... retrieval → full docs ...

    if state_patch_context:
        state_context_text = (
            "## Already-applied state_patch (FACT, не предлагай повторно):\n"
            + json.dumps(state_patch_context, ensure_ascii=False, indent=2)
            + "\n\n"
            "The above state_patch operations have ALREADY been applied to the campaign state. "
            "Generate file_changes that reflect THESE accepted facts in the .md documents. "
            "Do NOT propose state_patch operations — only file_changes."
        )
    else:
        state_context_text = ""

    # LLM prompt с state_context_text
    # ... rest of method ...
```

### Критерии готовности

- ✅ `UpdateModeExecutor.start_from_proposal(state_patch_context=[...])` создаёт session
- ✅ В session только file_changes (state_patch пустой)
- ✅ LLM получает инструкцию "state_patch уже применён"
- ✅ Manual test: check-files из draft → открывается UpdateModePanel с готовыми file_changes

---

## Настройки platform_settings

Новые ключи для добавления в seed (миграция или отдельная):

| Ключ | Тип | Default | Описание |
|---|---|---|---|
| `drift.confidence_threshold` | float | 0.5 | Минимальный confidence для drift hint |
| `drift.max_messages` | int | 10 | Сколько последних сообщений читать для drift |
| `drift.cooldown_seconds` | int | 30 | Cooldown между drift вызовами для одного чата |
| `draft.ttl_seconds` | int | 10800 | TTL draft в Redis (3 часа) |

---

## Тесты (общие для всех фаз)

### Фаза 1

- `test_context_engine_assembly.py` — проверка `build_chat_context` идентичности с `_compose_full_system_prompt`
- Существующие тесты проходят без изменений

### Фаза 2а

- `test_drift_model_service.py` — CRUD активной модели
- `test_drift_providers.py` — host_sidecar + openai_compatible (с mock)
- Manual integration test: добавить модель через API, активировать, проверить через /check

### Фаза 2b

- `test_drift_detector.py` — с mock провайдером, проверка записи в scene_state.drift
- `test_drift_loop.py` — cooldown через mock Redis
- `test_scene_memory.py` — разделение explicit/drift

### Фаза 3

- `test_campaign_state_drafter.py` — проверка draft содержит только state_patch
- `test_draft_redis_key.py` — TTL = 3 часа, content hash

### Фаза 4

- `test_context_draft_api.py` — GET/POST endpoints с mock Redis
- `test_context_draft_card.py` — frontend vitest

### Фаза 5

- `test_update_mode_state_patch_context.py` — start_from_proposal с context, file_changes генерируются без state_patch

---

## Порядок запуска фаз

Каждая фаза катится **отдельно**. Контекст для модели:

```
Фаза 1: context/plan-context-engine.md (этот файл) + context/architecture.md + context/effective_context.py (старая версия)
Фаза 2а: context/plan-context-engine.md (этот файл) + context/db_schema.md + context/api_routes.md
Фаза 2b: context/plan-context-engine.md (этот файл) + rag-backend/app/services/context_engine/* (после Фазы 1)
Фаза 3: context/plan-context-engine.md (этот файл) + Фаза 2b файлы
Фаза 4: context/plan-context-engine.md (этот файл) + context/frontend.md + Фаза 3 файлы
Фаза 5: context/plan-context-engine.md (этот файл) + context/campaign-update-mode.md
```

**После каждой фазы — smoke test:**

1. Backend стартует без ошибок (`make up` или `docker compose up`)
2. Существующие тесты проходят (`make test` или pytest)
3. Manual: отправить сообщение в чат, проверить логи

---

## Открытые вопросы для будущих итераций

- Cooldown per-chat vs global queue
- Multi-chat batch processing в drafter (сейчас один chat = один draft)
- Drift hints archival (хранить ли в БД, или только в scene_state?)
- Settings для пользовательского выбора: "drift вкл/выкл", "draft вкл/выкл"