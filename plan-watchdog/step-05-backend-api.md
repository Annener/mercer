# Этап 5 — rag-backend: API настроек + pending-files

## Цель

Добавить два эндпоинта в `rag-backend`:
- `GET  /api/v1/settings/watchdog` — читает настройку из PG
- `PATCH /api/v1/settings/watchdog` — сохраняет настройку в PG
- `GET  /api/v1/vaults/{vault_id}/pending-files` — читает `vault:{vault_id}:files` из Redis
  и возвращает файлы со статусом `pending`

## Контекст из кодовой базы

### `rag-backend` работает с Redis напрямую

`rag-backend/app/main.py` содержит:
```python
app.state.redis  # redis.asyncio.Redis, decode_responses=True
```

Не импортировать `RedisStateManager` из `rag-indexer` — работаем с Redis через
`request.app.state.redis` напрямую.

### PG в `rag-backend`

`rag-backend/app/db/session.py` содержит `get_db()` — возвращает **`AsyncSession` (SQLAlchemy)**
через `Depends`. Импорт:

```python
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
```

> ⚠️ Это **не** `asyncpg.Connection`. Запросы выполняются через `db.execute(text(...), {...})`.
> После модифицирующих операций обязателен `await db.commit()`.

### Предупреждение: существующий `settings_router`

В `main.py` уже зарегистрирован:
```python
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
```
Новый `watchdog_router` использует `prefix="/api/v1"` — конфликта нет.
Перед регистрацией проверьте: нет ли в `settings_router` маршрута `/watchdog`.

## Что нужно создать

### `rag-backend/app/api/watchdog_settings.py`

```python
"""API настройки watchdog и pending-files."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["watchdog"])

SETTING_KEY = "watchdog_auto_index_extensions"


# ------------------------------------------------------------------
# Pydantic-схемы
# ------------------------------------------------------------------

class WatchdogSettings(BaseModel):
    """Payload and response for watchdog settings."""
    auto_index_extensions: list[str]
    """Ордеред лист расширений, e.g. [".md", ".pdf"]"""

    @field_validator("auto_index_extensions", mode="before")
    @classmethod
    def _normalise(cls, v: object) -> list[str]:
        """Accepts a list or a comma-separated string."""
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",") if ext.strip()]
        return [str(e).strip() for e in v if str(e).strip()]

    def to_db_value(self) -> str:
        return ",".join(self.auto_index_extensions)


class PendingFilesResponse(BaseModel):
    vault_id: str
    pending_files: list[str]
    total: int


# ------------------------------------------------------------------
# GET /api/v1/settings/watchdog
# ------------------------------------------------------------------

@router.get("/settings/watchdog", response_model=WatchdogSettings)
async def get_watchdog_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WatchdogSettings:
    """Returns current watchdog auto-index extensions from PostgreSQL."""
    result = await db.execute(
        text("SELECT value FROM platform_settings WHERE key = :key"),
        {"key": SETTING_KEY},
    )
    row = result.fetchone()
    raw: str = row[0] if row else ".md,.pdf"
    return WatchdogSettings(auto_index_extensions=raw)


# ------------------------------------------------------------------
# PATCH /api/v1/settings/watchdog
# ------------------------------------------------------------------

@router.patch("/settings/watchdog", response_model=WatchdogSettings)
async def update_watchdog_settings(
    payload: WatchdogSettings,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WatchdogSettings:
    """Упсертит watchdog setting в PostgreSQL.

    Validation: at least one extension must be provided.
    Extension must start with '.'
    """
    exts = payload.auto_index_extensions
    if not exts:
        raise HTTPException(status_code=422, detail="At least one extension required.")
    for ext in exts:
        if not ext.startswith("."):
            raise HTTPException(
                status_code=422,
                detail=f"Extension must start with '.', got: {ext!r}",
            )

    await db.execute(
        text(
            """
            INSERT INTO platform_settings (key, value)
            VALUES (:key, :value)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """
        ),
        {"key": SETTING_KEY, "value": payload.to_db_value()},
    )
    await db.commit()  # без commit изменение не сохранится
    return payload


# ------------------------------------------------------------------
# GET /api/v1/vaults/{vault_id}/pending-files
# ------------------------------------------------------------------

@router.get("/vaults/{vault_id}/pending-files", response_model=PendingFilesResponse)
async def get_pending_files(
    vault_id: str,
    request: Request,
) -> PendingFilesResponse:
    """Returns files with index_status='pending' from Redis vault cache.

    Reads vault:{vault_id}:files HASH directly via request.app.state.redis.
    Does NOT call rag-indexer.
    """
    r = request.app.state.redis
    raw: dict[str, str] = await r.hgetall(f"vault:{vault_id}:files")

    pending: list[str] = []
    for path, value in raw.items():
        if path == "__empty__":
            continue
        try:
            entry = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue
        if entry.get("index_status") == "pending":
            pending.append(path)

    return PendingFilesResponse(
        vault_id=vault_id,
        pending_files=sorted(pending),
        total=len(pending),
    )
```

### Регистрация роутера в `rag-backend/app/main.py`

```python
from app.api.watchdog_settings import router as watchdog_router

app.include_router(watchdog_router)
```

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `rag-backend/app/api/watchdog_settings.py` | Создать |
| `rag-backend/app/main.py` | `+include_router(watchdog_router)` |

## ✅ Unit-тесты

Путь: `rag-backend/app/tests/test_watchdog_api.py`

> Правильный способ переопределить FastAPI-зависимость — `app.dependency_overrides`,
> а **не** `monkeypatch.setattr`. После каждого теста override очищается.

> ⚠️ **Важно**: при запуске `AsyncClient(transport=ASGITransport(app=app))` lifespan стартует
> и перезаписывает `app.state.redis` реальным клиентом.
> Для тестов, требующих Redis, необходимо патчить `aioredis.from_url`
> ещё до старта lifespan — пример ниже.

> ⚠️ Обязательно добавить `pytestmark = pytest.mark.asyncio` на уровне модуля,
> иначе async-тесты молча пропускаются.

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.db.session import get_db

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    return db


async def test_get_watchdog_settings_default(mock_db):
    # fetchone() возвращает None — должен вернуть значения по умолчанию
    result_mock = MagicMock()
    result_mock.fetchone.return_value = None
    mock_db.execute.return_value = result_mock

    mock_redis = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/api/v1/settings/watchdog")
        assert r.status_code == 200
        data = r.json()
        assert set(data["auto_index_extensions"]) == {".md", ".pdf"}
    finally:
        app.dependency_overrides.clear()


async def test_patch_watchdog_settings(mock_db):
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_redis = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            payload = {"auto_index_extensions": [".md", ".txt"]}
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.patch("/api/v1/settings/watchdog", json=payload)
        assert r.status_code == 200
        assert ".txt" in r.json()["auto_index_extensions"]
        mock_db.commit.assert_awaited_once()  # commit должен быть вызван
    finally:
        app.dependency_overrides.clear()


async def test_patch_invalid_extension(mock_db):
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_redis = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            payload = {"auto_index_extensions": ["md"]}  # без точки
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.patch("/api/v1/settings/watchdog", json=payload)
        assert r.status_code == 422
        mock_db.commit.assert_not_awaited()  # commit не должен вызываться при ошибке
    finally:
        app.dependency_overrides.clear()


async def test_get_pending_files():
    mock_redis = AsyncMock()
    mock_redis.hgetall.return_value = {
        "notes.md": json.dumps({"index_status": "pending", "md5": "abc"}),
        "report.pdf": json.dumps({"index_status": "indexed", "md5": "def"}),
        "new.txt": json.dumps({"index_status": "pending", "md5": ""}),
        "__empty__": "1",
    }
    with patch("redis.asyncio.from_url", return_value=mock_redis):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/vaults/v1/pending-files")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert set(data["pending_files"]) == {"notes.md", "new.txt"}
```

## Критерий готовности

- [ ] `GET /api/v1/settings/watchdog` — 200, возвращает по умолчанию если PG пуст или ключ отсутствует
- [ ] `PATCH /api/v1/settings/watchdog` — 422 если расширение без `.`
- [ ] `PATCH` вызывает `db.commit()` после `execute`
- [ ] `GET /api/v1/vaults/{vault_id}/pending-files` — читает Redis, игнорирует `__empty__`
- [ ] unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 5 → ✅
