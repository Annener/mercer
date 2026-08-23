"""Tests for campaign_state_initial_store.py — Redis-backed proposal store.

Используется FakeRedis (без testcontainers): store интересует только контракт
{set(key, json, ex=ttl), get(key) -> bytes|None, delete(key)}.
"""
from __future__ import annotations

import datetime as _dt

import pytest
from app.services.campaign_state_initial_store import (
    INITIAL_TTL_SECONDS,
    campaign_state_initial_store,
)

from shared_contracts.models import (
    CampaignStateInitialFieldStatus,
    CampaignStateInitialProposal,
    CampaignStateInitialProposalField,
    CampaignStateInitialProposalRead,
    DocumentSnapshot,
)

# ---------------------------------------------------------------------------
# FakeRedis
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Минимальный fake, поддерживающий set/get/delete с TTL."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, int | None]] = {}
        # Хранит последний переданный TTL для проверки в тестах.
        self.last_ttl: int | None = None
        self.last_key: str | None = None

    async def set(self, key: str, value, ex: int | None = None) -> None:
        if isinstance(value, str):
            value = value.encode("utf-8")
        self._data[key] = (value, ex)
        self.last_ttl = ex
        self.last_key = key

    async def get(self, key: str):
        entry = self._data.get(key)
        if entry is None:
            return None
        value, _ = entry
        return value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(campaign_id: str = "c-1") -> CampaignStateInitialProposalRead:
    snap = DocumentSnapshot(
        document_id="11111111-1111-1111-1111-111111111111",
        vault_id="dnd-vault",
        source_path="session-14.md",
        content_sha="a" * 32,
        estimated_tokens=100,
    )
    pf = CampaignStateInitialProposalField(
        field_key="current_focus",
        mode="single",
        status=CampaignStateInitialFieldStatus(status="empty"),
    )
    now = _dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)
    return CampaignStateInitialProposalRead(
        proposal_id="p-123",
        campaign_id=campaign_id,
        config_version=1,
        source_snapshot=[snap],
        proposal=CampaignStateInitialProposal(fields=[pf], questions=[]),
        warnings=["w1"],
        created_at=now,
        expires_at=now + _dt.timedelta(seconds=INITIAL_TTL_SECONDS),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_writes_with_ttl_3h() -> None:
    redis = _FakeRedis()
    payload = _make_payload()
    await campaign_state_initial_store.create(redis, payload)

    assert redis.last_key == "campaign_initial:c-1"
    assert redis.last_ttl == INITIAL_TTL_SECONDS
    assert INITIAL_TTL_SECONDS == 3 * 60 * 60
    assert "campaign_initial:c-1" in redis._data


@pytest.mark.asyncio
async def test_get_returns_payload_round_trip() -> None:
    redis = _FakeRedis()
    payload = _make_payload(campaign_id="c-2")
    await campaign_state_initial_store.create(redis, payload)

    out = await campaign_state_initial_store.get(redis, "c-2")
    assert out is not None
    assert out.proposal_id == payload.proposal_id
    assert out.config_version == 1
    assert out.campaign_id == "c-2"
    assert len(out.source_snapshot) == 1
    assert out.source_snapshot[0].content_sha == "a" * 32
    assert out.warnings == ["w1"]
    assert len(out.proposal.fields) == 1


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    redis = _FakeRedis()
    out = await campaign_state_initial_store.get(redis, "nonexistent")
    assert out is None


@pytest.mark.asyncio
async def test_delete_removes_key() -> None:
    redis = _FakeRedis()
    await campaign_state_initial_store.create(redis, _make_payload(campaign_id="c-3"))
    assert await campaign_state_initial_store.get(redis, "c-3") is not None

    await campaign_state_initial_store.delete(redis, "c-3")
    assert await campaign_state_initial_store.get(redis, "c-3") is None


@pytest.mark.asyncio
async def test_delete_missing_key_is_noop() -> None:
    redis = _FakeRedis()
    # Не должно бросать.
    await campaign_state_initial_store.delete(redis, "nope")
    assert await campaign_state_initial_store.get(redis, "nope") is None


@pytest.mark.asyncio
async def test_create_overwrites_existing() -> None:
    redis = _FakeRedis()
    await campaign_state_initial_store.create(redis, _make_payload(campaign_id="c-4"))
    second = _make_payload(campaign_id="c-4")
    second = second.model_copy(update={"proposal_id": "p-456"})
    await campaign_state_initial_store.create(redis, second)

    out = await campaign_state_initial_store.get(redis, "c-4")
    assert out is not None
    assert out.proposal_id == "p-456"


@pytest.mark.asyncio
async def test_get_handles_bytes_value() -> None:
    """Некоторые async-redis клиенты возвращают bytes — store должен корректно декодировать."""
    redis = _FakeRedis()
    await campaign_state_initial_store.create(redis, _make_payload(campaign_id="c-5"))
    # Внутри FakeRedis хранится bytes (мы конвертируем str→bytes в set),
    # get возвращает то же bytes. Реальный redis тоже отдаёт bytes.
    out = await campaign_state_initial_store.get(redis, "c-5")
    assert out is not None
    assert out.campaign_id == "c-5"


@pytest.mark.asyncio
async def test_get_decodes_v1_payload_as_v2_with_empty_suggested() -> None:
    """Backward-compat: proposals, сохранённые до Stage 3.v2 (без suggested_fields),
    продолжают работать — V2 Read десериализует их с suggested_fields=[].

    Сценарий: после обновления кода в Redis могут остаться старые V1 proposals
    (TTL 3 часа). apply() должен корректно прочитать их и обработать
    `payload.proposal.suggested_fields` (получит []).
    """
    import json

    from app.services.campaign_state_initial_store import campaign_state_initial_store

    now = _dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)
    # Эмулируем JSON, сериализованный CampaignStateInitialProposalRead (V1, без suggested_fields).
    v1_json = json.dumps({
        "proposal_id": "old-v1-proposal",
        "campaign_id": "c-v1",
        "config_version": 2,
        "source_snapshot": [],
        "proposal": {
            "fields": [],
            "questions": [],
            # ВАЖНО: нет suggested_fields (V1).
        },
        "warnings": [],
        "created_at": now.isoformat(),
        "expires_at": (now + _dt.timedelta(hours=3)).isoformat(),
    })

    redis = _FakeRedis()
    redis._data["campaign_initial:c-v1"] = (v1_json.encode("utf-8"), 3 * 3600)

    out = await campaign_state_initial_store.get(redis, "c-v1")
    assert out is not None
    assert out.proposal_id == "old-v1-proposal"
    # Backward-compat: V1 JSON нормализуется в V2 с пустым suggested_fields.
    assert out.proposal.suggested_fields == []
    assert hasattr(out.proposal, "suggested_fields")
