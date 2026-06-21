# Этап 5 — rag-backend: API настроек + pending-files

## Цель

Добавить пять эндпоинтов в `rag-backend`:
- `GET  /api/v1/settings/watchdog` — читает настройку из PG
- `PATCH /api/v1/settings/watchdog` — сохраняет настройку в PG
- `GET  /api/v1/vaults/{vault_id}/pending-files` — читает `vault:{vault_id}:files` из Redis
  и возвращает файлы со статусом `pending` (per-vault, для внутреннего использования)
- `GET  /api/v1/domains/{domain_id}/pending-files` — **агрегирующий endpoint** для фронтенда:
  суммирует `pending`-файлы по всем vault-ам домена
- `POST /api/v1/domains/{domain_id}/index` — **запускает индексацию** всех `pending`-файлов
  домена: отправляет задачи в очередь rag-indexer через Redis

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

### Механизм запуска индексации через Redis

`rag-indexer` слушает очередь `indexer:queue` (Redis List, `LPUSH` / `BRPOP`).
Каждое задание — JSON-объект:
```json
{"vault_id": "<id>", "path": "<relative/path/to/file>"}
```
Endpoint `POST /domains/{domain_id}/index` собирает все pending-файлы домена
и кладёт по одному заданию в очередь через `LPUSH indexer:queue <json>`.

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
_INDEXER_QUEUE = "indexer:queue"


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


class DomainPendingFilesResponse(BaseModel):
    domain_id: str
    total_pending: int
    vaults: list[dict]  # [{vault_id, pending_count}]


class IndexResponse(BaseModel):
    domain_id: str
    queued: int  # количество задач, отправленных в очередь


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
# GET /api/v1/vaults/{vault_id}/pending-files  (per-vault, внутренний)
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


# ------------------------------------------------------------------
# GET /api/v1/domains/{domain_id}/pending-files  (агрегирующий, для фронтенда)
# ------------------------------------------------------------------

@router.get("/domains/{domain_id}/pending-files", response_model=DomainPendingFilesResponse)
async def get_domain_pending_files(
    domain_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DomainPendingFilesResponse:
    """Aggregates pending files across ALL vaults of a domain.

    Fetches vault_ids for the domain from PostgreSQL,
    then reads each vault's Redis cache and sums pending counts.
    Used by the frontend pending-files banner in the chat.
    """
    result = await db.execute(
        text("SELECT vault_id FROM vaults WHERE domain_id = :domain_id"),
        {"domain_id": domain_id},
    )
    rows = result.fetchall()
    vault_ids = [row[0] for row in rows]

    r = request.app.state.redis
    vaults_summary = []
    total_pending = 0

    for vault_id in vault_ids:
        raw: dict[str, str] = await r.hgetall(f"vault:{vault_id}:files")
        count = 0
        for path, value in raw.items():
            if path == "__empty__":
                continue
            try:
                entry = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            if entry.get("index_status") == "pending":
                count += 1
        vaults_summary.append({"vault_id": vault_id, "pending_count": count})
        total_pending += count

    return DomainPendingFilesResponse(
        domain_id=domain_id,
        total_pending=total_pending,
        vaults=vaults_summary,
    )


# ------------------------------------------------------------------
# POST /api/v1/domains/{domain_id}/index  (запуск индексации pending-файлов)
# ------------------------------------------------------------------

@router.post("/domains/{domain_id}/index", response_model=IndexResponse)
async def trigger_domain_index(
    domain_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexResponse:
    """Queues indexing tasks for all pending files across the domain's vaults.

    For each vault in the domain:
    1. Reads vault:{vault_id}:files HASH from Redis.
    2. Collects paths with index_status='pending'.
    3. Pushes one JSON task per file to 'indexer:queue' via LPUSH.

    Returns the total number of tasks queued.
    Does NOT wait for indexing to complete — fire-and-forget.
    """
    result = await db.execute(
        text("SELECT vault_id FROM vaults WHERE domain_id = :domain_id"),
        {"domain_id": domain_id},
    )
    vault_ids = [row[0] for row in result.fetchall()]

    r = request.app.state.redis
    queued = 0

    for vault_id in vault_ids:
        raw: dict[str, str] = await r.hgetall(f"vault:{vault_id}:files")
        for path, value in raw.items():
            if path == "__empty__":
                continue
            try:
                entry = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                continue
            if entry.get("index_status") == "pending":
                task = json.dumps({"vault_id": vault_id, "path": path})
                await r.lpush(_INDEXER_QUEUE, task)
                queued += 1

    return IndexResponse(domain_id=domain_id, queued=queued)
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
        mock_db.commit.assert_awaited_once()
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
        mock_db.commit.assert_not_awaited()
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


async def test_get_domain_pending_files(mock_db):
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("vault-1",), ("vault-2",)]
    mock_db.execute.return_value = result_mock

    mock_redis = AsyncMock()
    async def hgetall_side(key):
        if key == "vault:vault-1:files":
            return {
                "a.md": json.dumps({"index_status": "pending"}),
                "b.md": json.dumps({"index_status": "pending"}),
                "c.md": json.dumps({"index_status": "indexed"}),
            }
        if key == "vault:vault-2:files":
            return {
                "d.md": json.dumps({"index_status": "indexed"}),
            }
        return {}
    mock_redis.hgetall.side_effect = hgetall_side

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.get("/api/v1/domains/dnd/pending-files")
        assert r.status_code == 200
        data = r.json()
        assert data["total_pending"] == 2
        assert data["domain_id"] == "dnd"
        vault_map = {v["vault_id"]: v["pending_count"] for v in data["vaults"]}
        assert vault_map["vault-1"] == 2
        assert vault_map["vault-2"] == 0
    finally:
        app.dependency_overrides.clear()


async def test_post_domain_index(mock_db):
    """POST /domains/{domain_id}/index queues tasks for pending files only."""
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [("vault-1",), ("vault-2",)]
    mock_db.execute.return_value = result_mock

    mock_redis = AsyncMock()
    async def hgetall_side(key):
        if key == "vault:vault-1:files":
            return {
                "a.md": json.dumps({"index_status": "pending"}),
                "b.md": json.dumps({"index_status": "indexed"}),
            }
        if key == "vault:vault-2:files":
            return {
                "c.md": json.dumps({"index_status": "pending"}),
                "__empty__": "1",
            }
        return {}
    mock_redis.hgetall.side_effect = hgetall_side
    mock_redis.lpush = AsyncMock()

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/api/v1/domains/dnd/index")
        assert r.status_code == 200
        data = r.json()
        assert data["queued"] == 2           # a.md + c.md
        assert data["domain_id"] == "dnd"
        assert mock_redis.lpush.await_count == 2
        # Проверяем что b.md (indexed) и __empty__ не попали в очередь
        queued_tasks = [
            json.loads(call.args[1])
            for call in mock_redis.lpush.call_args_list
        ]
        paths = {t["path"] for t in queued_tasks}
        assert paths == {"a.md", "c.md"}
    finally:
        app.dependency_overrides.clear()
```

## Критерий готовности

- [ ] `GET /api/v1/settings/watchdog` — 200, возвращает по умолчанию если PG пуст или ключ отсутствует
- [ ] `PATCH /api/v1/settings/watchdog` — 422 если расширение без `.`
- [ ] `PATCH` вызывает `db.commit()` после `execute`
- [ ] `GET /api/v1/vaults/{vault_id}/pending-files` — читает Redis, игнорирует `__empty__`
- [ ] `GET /api/v1/domains/{domain_id}/pending-files` — агрегирует по всем vault-ам домена из PG + Redis
- [ ] `POST /api/v1/domains/{domain_id}/index` — кладёт в `indexer:queue` по одной задаче на каждый pending-файл, возвращает `{queued: N}`
- [ ] `POST /index` не трогает `indexed`-файлы и не падает на `__empty__`
- [ ] unit-тесты проходят
- [ ] `STATUS.md` обновлён: этап 5 → ✅
