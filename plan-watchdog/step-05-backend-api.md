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

`rag-backend/app/db.py` уже содержит `get_db()` — возвращает `asyncpg.Connection`
через `Depends`. Те же зависимости используем здесь.

Уточнить название dependency через MCPдо реализации.

## Что нужно создать

### `rag-backend/app/api/watchdog_settings.py`

```python
"""API настройки watchdog и pending-files."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.db import get_db  # уточнить импорт перед реализацией

router = APIRouter(prefix="/api/v1", tags=["watchdog"])

SETTING_KEY = "watchdog_auto_index_extensions"


# ------------------------------------------------------------------
# Pydantic-схемы
# ------------------------------------------------------------------

class WatchdogSettings(BaseModel):
    """Payload and response for watchdog settings."""
    auto_index_extensions: list[str]
    """Ordered list of extensions, e.g. [".md", ".pdf"]"""

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
    db: Annotated[object, Depends(get_db)],
) -> WatchdogSettings:
    """Returns current watchdog auto-index extensions from PostgreSQL."""
    row = await db.fetchrow(
        "SELECT value FROM platform_settings WHERE key = $1",
        SETTING_KEY,
    )
    raw: str = row["value"] if row else ".md,.pdf"
    return WatchdogSettings(auto_index_extensions=raw)


# ------------------------------------------------------------------
# PATCH /api/v1/settings/watchdog
# ------------------------------------------------------------------

@router.patch("/settings/watchdog", response_model=WatchdogSettings)
async def update_watchdog_settings(
    payload: WatchdogSettings,
    db: Annotated[object, Depends(get_db)],
) -> WatchdogSettings:
    """Upserts watchdog setting in PostgreSQL.

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
        """
        INSERT INTO platform_settings (key, value)
        VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        SETTING_KEY,
        payload.to_db_value(),
    )
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

```
tests/rag_backend/test_watchdog_api.py
```

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    app.state.redis = r
    return r


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


async def test_get_watchdog_settings_default(mock_redis, mock_db, monkeypatch):
    mock_db.fetchrow.return_value = None
    monkeypatch.setattr("app.api.watchdog_settings.get_db", lambda: mock_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/settings/watchdog")
    assert r.status_code == 200
    data = r.json()
    assert set(data["auto_index_extensions"]) == {".md", ".pdf"}


async def test_patch_watchdog_settings(mock_redis, mock_db, monkeypatch):
    mock_db.execute = AsyncMock()
    monkeypatch.setattr("app.api.watchdog_settings.get_db", lambda: mock_db)

    payload = {"auto_index_extensions": [".md", ".txt"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch("/api/v1/settings/watchdog", json=payload)
    assert r.status_code == 200
    assert ".txt" in r.json()["auto_index_extensions"]


async def test_patch_invalid_extension(mock_redis, mock_db, monkeypatch):
    mock_db.execute = AsyncMock()
    monkeypatch.setattr("app.api.watchdog_settings.get_db", lambda: mock_db)

    payload = {"auto_index_extensions": ["md"]}  # без точки
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch("/api/v1/settings/watchdog", json=payload)
    assert r.status_code == 422


async def test_get_pending_files(mock_redis):
    mock_redis.hgetall.return_value = {
        "notes.md": json.dumps({"index_status": "pending", "md5": "abc"}),
        "report.pdf": json.dumps({"index_status": "indexed", "md5": "def"}),
        "new.txt": json.dumps({"index_status": "pending", "md5": ""}),
        "__empty__": "1",
    }
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
- [ ] `GET /api/v1/vaults/{vault_id}/pending-files` — читает Redis, игнорирует `__empty__`
- [ ] unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 5 → ✅
