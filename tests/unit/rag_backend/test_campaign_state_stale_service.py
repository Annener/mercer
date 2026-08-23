"""Tests for campaign_state_stale_service.py — Stage 7 stale-detection.

Стратегия: fakes для db (AsyncMock) и redis (in-memory dict-like).
Покрывает compute_stale_status, audit transition logic и PDF-защиту.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from app.services.campaign_state_stale_service import (
    CampaignStateStaleError,
    CampaignNotFoundError,
    _detect_stale_documents,
    _maybe_log_stale_transition,
    _parse_file_refs,
    _should_log_transition,
    campaign_state_stale_service,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Простой in-memory fake Redis (только нужные команды)."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.audit_payloads: list[dict[str, Any]] = []
        self.audit_commits: int = 0
        self._fail_on_hgetall: bool = False

    async def hgetall(self, key: str) -> dict[str, str]:
        if self._fail_on_hgetall:
            raise RuntimeError("redis down")
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str] | None = None, **_kw: Any) -> None:
        bucket = self.hashes.setdefault(key, {})
        if mapping:
            bucket.update(mapping)

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value
        if ex is not None:
            self.expirations[key] = ex

    async def exists(self, key: str) -> int:
        return 1 if key in self.strings or key in self.hashes else 0


class _FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeDocument:
    def __init__(
        self,
        *,
        doc_id: str,
        vault_id: str,
        source_path: str,
        md5: str = "md5_default",
        status: str = "indexed",
    ) -> None:
        self.id = uuid.UUID(doc_id)
        self.vault_id = vault_id
        self.source_path = source_path
        self.md5 = md5
        self.status = status


class _FakeVersion:
    def __init__(self, state_version: int, campaign_id: str) -> None:
        self.id = uuid.uuid4()
        self.campaign_id = uuid.UUID(campaign_id)
        self.state_version = state_version
        self.config_version = 1


class _FakeDb:
    """Минимальный AsyncMock fake с execute/commit/rollback/get."""

    def __init__(
        self,
        *,
        campaign_exists: bool = True,
        version: _FakeVersion | None = None,
        values_source_refs: list[list[str]] | None = None,
        items_source_refs: list[list[str]] | None = None,
        documents: list[_FakeDocument] | None = None,
        audit_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        self._campaign_exists = campaign_exists
        self._version = version
        self._values_source_refs = values_source_refs or []
        self._items_source_refs = items_source_refs or []
        self._documents = documents or []
        self._audit_payloads = audit_payloads if audit_payloads is not None else []
        self.commits = 0
        self.rollbacks = 0

        self._call_count = 0

    async def get(self, model: Any, pk: Any) -> Any:
        if not self._campaign_exists:
            return None
        # Любой PK кампании возвращаем объект, имитирующий Campaign ORM.
        return object()

    async def execute(self, stmt: Any) -> _FakeExecuteResult:
        self._call_count += 1

        # Heuristic: разные запросы дают разные данные, на основе стейта fake-db.
        # Используем id() выражения stmt + последовательность вызовов.
        n = self._call_count

        # 1-й execute: latest_version select
        if n == 1:
            return _FakeExecuteResult([self._version] if self._version else [])

        # 2-й и 3-й: source_refs values/items
        if n == 2:
            return _FakeExecuteResult(self._values_source_refs)
        if n == 3:
            return _FakeExecuteResult(self._items_source_refs)

        # 4-й: documents by ids
        if n == 4:
            return _FakeExecuteResult(self._documents)

        # далее: insert AuditLog
        return _FakeExecuteResult(self._audit_payloads)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# _parse_file_refs
# ---------------------------------------------------------------------------


def test_parse_file_refs_basic() -> None:
    refs = [
        f"file:{uuid.uuid4()}:sha:abc123",
        f"file:{uuid.uuid4()}:sha:def456",
    ]
    result = _parse_file_refs(refs)
    assert len(result) == 2
    for r in result:
        assert r.startswith("file:") is False  # doc_id без префикса


def test_parse_file_refs_filters_non_file() -> None:
    refs = [
        f"file:{uuid.uuid4()}:sha:abc123",
        f"chat:{uuid.uuid4()}",
        "garbage",
        f"file:{uuid.uuid4()}",  # нет :sha: → отбрасывается
    ]
    result = _parse_file_refs(refs)
    assert len(result) == 1


def test_parse_file_refs_handles_empty() -> None:
    assert _parse_file_refs([]) == set()


# ---------------------------------------------------------------------------
# compute_stale_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_state_version_returns_false() -> None:
    db = _FakeDb(campaign_exists=True, version=None)
    redis = _FakeRedis()
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.uuid4(),
    )
    assert result.potentially_stale is False
    assert result.stale_documents == []
    assert result.active_state_version is None


@pytest.mark.asyncio
async def test_no_source_refs_returns_false() -> None:
    campaign_id = str(uuid.uuid4())
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(1, campaign_id),
        values_source_refs=[[]],
        items_source_refs=[[]],
    )
    redis = _FakeRedis()
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is False
    assert result.active_state_version == 1


@pytest.mark.asyncio
async def test_md5_match_returns_false() -> None:
    """Indexed.md5 == Document.md5 → fresh."""
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="abc123",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:abc123"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    redis = _FakeRedis()
    redis.hashes["vault:vault-1:files"] = {
        "session.md": json.dumps({
            "md5": "abc123",
            "index_status": "indexed",
            "indexed_md5": "abc123",
        }),
    }
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is False
    assert result.stale_documents == []


@pytest.mark.asyncio
async def test_md5_mismatch_returns_true() -> None:
    """Indexed.md5 != Document.md5 → stale."""
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="newhash",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:oldhash"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    redis = _FakeRedis()
    redis.hashes["vault:vault-1:files"] = {
        "session.md": json.dumps({
            "md5": "oldhash",
            "index_status": "indexed",
            "indexed_md5": "oldhash",
        }),
    }
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is True
    assert doc_id in result.stale_documents


@pytest.mark.asyncio
async def test_pending_status_returns_true() -> None:
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="abc123",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:abc123"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    redis = _FakeRedis()
    redis.hashes["vault:vault-1:files"] = {
        "session.md": json.dumps({
            "md5": "",
            "index_status": "pending",
            "indexed_md5": "abc123",
        }),
    }
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is True
    assert doc_id in result.stale_documents


@pytest.mark.asyncio
async def test_deleted_status_returns_true() -> None:
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="abc123",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:abc123"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    redis = _FakeRedis()
    redis.hashes["vault:vault-1:files"] = {
        "session.md": json.dumps({
            "md5": "abc123",
            "index_status": "deleted",
            "indexed_md5": "abc123",
        }),
    }
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is True


@pytest.mark.asyncio
async def test_pdf_skipped_even_if_stale() -> None:
    """PDF в source_refs — защитный случай: не считается stale."""
    campaign_id = str(uuid.uuid4())
    pdf_id = str(uuid.uuid4())
    pdf = _FakeDocument(
        doc_id=pdf_id,
        vault_id="vault-1",
        source_path="manual.pdf",
        md5="pdfmd5",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{pdf_id}:sha:pdfmd5"]],
        items_source_refs=[[]],
        documents=[pdf],
    )
    redis = _FakeRedis()
    # PDF помечен stale в Redis — должен быть проигнорирован.
    redis.hashes["vault:vault-1:files"] = {
        "manual.pdf": json.dumps({
            "md5": "old",
            "index_status": "stale",
            "indexed_md5": "old",
        }),
    }
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is False
    assert pdf_id not in result.stale_documents


@pytest.mark.asyncio
async def test_multiple_files_only_stale_one_returned() -> None:
    campaign_id = str(uuid.uuid4())
    fresh_id = str(uuid.uuid4())
    stale_id = str(uuid.uuid4())
    fresh = _FakeDocument(
        doc_id=fresh_id,
        vault_id="vault-1",
        source_path="fresh.md",
        md5="fresha",
        status="indexed",
    )
    stale = _FakeDocument(
        doc_id=stale_id,
        vault_id="vault-1",
        source_path="stale.md",
        md5="stalea",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(3, campaign_id),
        values_source_refs=[[f"file:{fresh_id}:sha:fresha"]],
        items_source_refs=[[f"file:{stale_id}:sha:stalea"]],
        documents=[fresh, stale],
    )
    redis = _FakeRedis()
    redis.hashes["vault:vault-1:files"] = {
        "fresh.md": json.dumps({
            "md5": "fresha",
            "index_status": "indexed",
            "indexed_md5": "fresha",
        }),
        "stale.md": json.dumps({
            "md5": "old",
            "index_status": "indexed",
            "indexed_md5": "old",
        }),
    }
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is True
    assert stale_id in result.stale_documents
    assert fresh_id not in result.stale_documents


@pytest.mark.asyncio
async def test_missing_redis_key_no_false_positive() -> None:
    """Redis-ключ отсутствует (cold start) → не сигнализируем."""
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="abc",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:abc"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    redis = _FakeRedis()
    # vault:{vault_id}:files отсутствует.
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is False


@pytest.mark.asyncio
async def test_document_status_not_indexed_returns_true() -> None:
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="abc",
        status="pending",  # НЕ indexed
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:abc"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    redis = _FakeRedis()
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=redis, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is True
    assert doc_id in result.stale_documents


@pytest.mark.asyncio
async def test_campaign_not_found_raises() -> None:
    db = _FakeDb(campaign_exists=False)
    redis = _FakeRedis()
    with pytest.raises(CampaignNotFoundError):
        await campaign_state_stale_service.compute_stale_status(
            db=db, redis=redis, campaign_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_no_redis_returns_empty() -> None:
    """Redis=None → potentially_stale=False (не падаем)."""
    campaign_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    doc = _FakeDocument(
        doc_id=doc_id,
        vault_id="vault-1",
        source_path="session.md",
        md5="abc",
        status="indexed",
    )
    db = _FakeDb(
        campaign_exists=True,
        version=_FakeVersion(2, campaign_id),
        values_source_refs=[[f"file:{doc_id}:sha:abc"]],
        items_source_refs=[[]],
        documents=[doc],
    )
    result = await campaign_state_stale_service.compute_stale_status(
        db=db, redis=None, campaign_id=uuid.UUID(campaign_id),
    )
    assert result.potentially_stale is False


# ---------------------------------------------------------------------------
# _should_log_transition
# ---------------------------------------------------------------------------


def test_should_log_no_prev_and_stale() -> None:
    status = _status(stale=True, docs=["a"])
    assert _should_log_transition(None, status) is True


def test_should_log_no_prev_and_not_stale() -> None:
    status = _status(stale=False, docs=[])
    assert _should_log_transition(None, status) is False


def test_should_log_prev_false_to_true() -> None:
    prev = {"potentially_stale": False, "stale_documents": []}
    status = _status(stale=True, docs=["a"])
    assert _should_log_transition(prev, status) is True


def test_should_log_prev_true_same_docs() -> None:
    prev = {"potentially_stale": True, "stale_documents": ["a"]}
    status = _status(stale=True, docs=["a"])
    assert _should_log_transition(prev, status) is False


def test_should_log_prev_true_new_docs() -> None:
    prev = {"potentially_stale": True, "stale_documents": ["a"]}
    status = _status(stale=True, docs=["a", "b"])
    assert _should_log_transition(prev, status) is True


def test_should_log_prev_true_to_false() -> None:
    prev = {"potentially_stale": True, "stale_documents": ["a"]}
    status = _status(stale=False, docs=[])
    assert _should_log_transition(prev, status) is False


# ---------------------------------------------------------------------------
# _maybe_log_stale_transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_stale_logs_audit() -> None:
    """Первый переход false→true → пишем AuditLog."""
    campaign_id = uuid.uuid4()
    redis = _FakeRedis()
    db = _FakeDb(campaign_exists=True, version=_FakeVersion(1, str(campaign_id)))
    status = _status(stale=True, docs=["doc-1"], active_version=1)

    await _maybe_log_stale_transition(
        redis=redis,
        db=db,
        campaign_id=campaign_id,
        status=status,
    )

    assert db.commits == 1
    assert await redis.get(f"campaign:{campaign_id}:prev_stale") is not None


@pytest.mark.asyncio
async def test_repeat_stale_no_log() -> None:
    """Тот же stale_documents — не пишем."""
    campaign_id = uuid.uuid4()
    redis = _FakeRedis()
    redis.strings[f"campaign:{campaign_id}:prev_stale"] = json.dumps({
        "potentially_stale": True,
        "stale_documents": ["doc-1"],
    })
    db = _FakeDb(campaign_exists=True, version=_FakeVersion(1, str(campaign_id)))
    status = _status(stale=True, docs=["doc-1"], active_version=1)

    await _maybe_log_stale_transition(
        redis=redis,
        db=db,
        campaign_id=campaign_id,
        status=status,
    )

    assert db.commits == 0


@pytest.mark.asyncio
async def test_new_stale_doc_logs_audit() -> None:
    """Появился новый stale — пишем."""
    campaign_id = uuid.uuid4()
    redis = _FakeRedis()
    redis.strings[f"campaign:{campaign_id}:prev_stale"] = json.dumps({
        "potentially_stale": True,
        "stale_documents": ["doc-1"],
    })
    db = _FakeDb(campaign_exists=True, version=_FakeVersion(2, str(campaign_id)))
    status = _status(stale=True, docs=["doc-1", "doc-2"], active_version=2)

    await _maybe_log_stale_transition(
        redis=redis,
        db=db,
        campaign_id=campaign_id,
        status=status,
    )

    assert db.commits == 1


@pytest.mark.asyncio
async def test_not_stale_no_log() -> None:
    campaign_id = uuid.uuid4()
    redis = _FakeRedis()
    db = _FakeDb(campaign_exists=True, version=_FakeVersion(1, str(campaign_id)))
    status = _status(stale=False, docs=[], active_version=1)

    await _maybe_log_stale_transition(
        redis=redis,
        db=db,
        campaign_id=campaign_id,
        status=status,
    )

    assert db.commits == 0
    # prev обнуляется при non-stale.
    assert await redis.get(f"campaign:{campaign_id}:prev_stale") is not None


@pytest.mark.asyncio
async def test_no_redis_skips_audit() -> None:
    campaign_id = uuid.uuid4()
    db = _FakeDb(campaign_exists=True, version=_FakeVersion(1, str(campaign_id)))
    status = _status(stale=True, docs=["doc-1"], active_version=1)

    await _maybe_log_stale_transition(
        redis=None,
        db=db,
        campaign_id=campaign_id,
        status=status,
    )

    assert db.commits == 0


@pytest.mark.asyncio
async def test_audit_failure_does_not_raise() -> None:
    """Если AuditLog упал, не блокируем основной путь."""
    campaign_id = uuid.uuid4()
    redis = _FakeRedis()

    class _FailingDb(_FakeDb):
        async def execute(self, stmt: Any) -> _FakeExecuteResult:
            raise RuntimeError("db down")

        async def commit(self) -> None:
            self.commits += 1

    db = _FailingDb()
    status = _status(stale=True, docs=["doc-1"], active_version=1)

    # Не должно падать.
    await _maybe_log_stale_transition(
        redis=redis,
        db=db,
        campaign_id=campaign_id,
        status=status,
    )


# ---------------------------------------------------------------------------
# _detect_stale_documents unit (boundary redis=hgetall failure)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_redis_failure_returns_empty() -> None:
    """Если Redis hgetall упал, не падаем."""
    redis = _FakeRedis()
    redis._fail_on_hgetall = True
    docs = [_FakeDocument(doc_id=str(uuid.uuid4()), vault_id="v", source_path="x.md")]
    result = await _detect_stale_documents(redis=redis, documents=docs)
    assert result == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(
    *,
    stale: bool,
    docs: list[str],
    active_version: int | None = 1,
) -> Any:
    from shared_contracts.models import CampaignStateStaleStatus

    return CampaignStateStaleStatus(
        potentially_stale=stale,
        stale_documents=docs,
        active_state_version=active_version,
        checked_at=datetime.now(timezone.utc),
    )