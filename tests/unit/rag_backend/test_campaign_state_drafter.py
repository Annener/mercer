"""Unit-тесты для CampaignStateDrafter (Phase 3).

Проверяем:

  * happy path: drift hints есть → LLM вернул patch → Redis-ключ записан
    с TTL = 3 часа;
  * hash-match: тот же drift → возвращён existing draft, LLM не вызывается;
  * no drift hints → None, ключ не создаётся;
  * no active provider → None + warning;
  * LLM вернул ``state_patch=[]`` → None;
  * invalid op type (``delete_field`` и т.п.) → фильтруется; если
    после фильтра пусто → None;
  * TTL = 10800 секунд.

БД и Redis мокаются на границах ``db_factory`` / ``redis_client`` —
``read_scene_state``, ``_read_last_messages``, ``_compile_state_text``
патчатся для контроля возвратов. Это даёт фокус на оркестраторе
(фильтрация, hash, TTL, save), без подъёма полного SQLAlchemy.
"""
from __future__ import annotations

import json
from contextlib import ExitStack, asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.context_engine.draft import (
    CampaignStateDrafter,
    _DRAFT_TTL_SECONDS,
)


CHAT_ID = "11111111-1111-1111-1111-111111111111"
CAMPAIGN_ID = "22222222-2222-2222-2222-222222222222"

HINTS = [
    {
        "fact": "Дракон помирился с нами",
        "adds_field": "current_allies",
        "confidence": 0.85,
    },
    {
        "fact": "Бехолдер ушёл из таверны",
        "contradicts_field": "active_npcs",
        "confidence": 0.7,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat(*, has_campaign: bool = True) -> MagicMock:
    chat = MagicMock()
    chat.campaign_id = CAMPAIGN_ID if has_campaign else None
    return chat


def _make_provider(
    parsed: dict | None = None, *, raises: Exception | None = None
) -> MagicMock:
    provider = MagicMock()
    if raises is not None:
        provider.generate_json = AsyncMock(side_effect=raises)
    else:
        provider.generate_json = AsyncMock(return_value=parsed or {})
    return provider


def _make_redis() -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.srem = AsyncMock(return_value=1)
    redis.sadd = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    return redis


@asynccontextmanager
async def _fake_db_session(chat: MagicMock):
    """Async context manager, возвращающий мок-сессию с одним Chat."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=chat)
    yield session


def _make_db_factory(chat: MagicMock | None):
    factory = MagicMock()

    @asynccontextmanager
    async def _ctx():
        if chat is None:
            yield AsyncMock()
        else:
            async with _fake_db_session(chat) as session:
                yield session

    factory.return_value = _ctx()
    return factory


def _patch_drafter_helpers(
    *,
    messages: list | None = None,
    state_text: str = "(empty state)",
    drift_hints: list | None = None,
):
    """Context manager, патчащий helpers drafter-а.

    Удобно для happy-path тестов: ``read_scene_state`` (module-level),
    ``CampaignStateDrafter._read_last_messages`` (staticmethod),
    ``CampaignStateDrafter._compile_state_text`` (staticmethod).
    """
    @contextmanager
    def _stack():
        with ExitStack() as es:
            es.enter_context(
                patch(
                    "app.services.context_engine.draft.read_scene_state",
                    new=AsyncMock(
                        return_value={
                            "drift": {"_hints": drift_hints if drift_hints is not None else HINTS}
                        }
                    ),
                )
            )
            es.enter_context(
                patch.object(
                    CampaignStateDrafter,
                    "_read_last_messages",
                    new=AsyncMock(return_value=list(messages or [])),
                )
            )
            es.enter_context(
                patch.object(
                    CampaignStateDrafter,
                    "_compile_state_text",
                    new=AsyncMock(return_value=state_text),
                )
            )
            yield es

    return _stack()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCampaignStateDrafter:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        chat = _make_chat()
        redis = _make_redis()
        provider = _make_provider(
            parsed={
                "state_patch": [
                    {
                        "type": "replace_single",
                        "field_key": "current_allies",
                        "text": "Дракон",
                        "reason": "помирился с нами",
                    },
                ],
                "summary": "Добавили дракона в союзники",
            }
        )

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers(
            messages=[{"role": "user", "content": "..."}]
        ):
            result = await drafter.plan_draft(CHAT_ID)

        assert result is not None
        assert result["chat_id"] == CHAT_ID
        assert result["campaign_id"] == CAMPAIGN_ID
        assert len(result["state_patch"]) == 1
        assert result["state_patch"][0]["type"] == "replace_single"
        assert result["summary"] == "Добавили дракона в союзники"
        assert isinstance(result["drift_hash"], str) and len(result["drift_hash"]) == 16
        assert result["drift_hints"] == HINTS
        assert "created_at" in result
        assert "expires_at" in result

        # TTL=3 часа, ключ формата draft:campaign:{cid}:chat:{chatid}.
        redis.setex.assert_awaited_once()
        args, _ = redis.setex.call_args
        key, ttl, payload = args[0], args[1], args[2]
        assert key == f"draft:campaign:{CAMPAIGN_ID}:chat:{CHAT_ID}"
        assert ttl == _DRAFT_TTL_SECONDS
        assert ttl == 10800
        # payload — JSON строкой; round-trip должен дать обратно dict.
        roundtrip = json.loads(payload)
        assert roundtrip["drift_hash"] == result["drift_hash"]

    @pytest.mark.asyncio
    async def test_hash_match_returns_existing_without_calling_llm(self):
        chat = _make_chat()
        redis = _make_redis()

        drift_hash = CampaignStateDrafter._hash_hints(HINTS)
        existing = {
            "chat_id": CHAT_ID,
            "campaign_id": CAMPAIGN_ID,
            "state_patch": [{"type": "replace_single"}],
            "summary": "old",
            "drift_hash": drift_hash,
            "drift_hints": HINTS,
        }
        redis.get = AsyncMock(return_value=json.dumps(existing))

        provider = _make_provider(parsed={"state_patch": [], "summary": "noop"})

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers():
            result = await drafter.plan_draft(CHAT_ID)

        assert result == existing
        provider.generate_json.assert_not_awaited()
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_drift_hints_returns_none(self):
        chat = _make_chat()
        redis = _make_redis()
        provider = _make_provider()

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers(drift_hints=[]):
            result = await drafter.plan_draft(CHAT_ID)

        assert result is None
        provider.generate_json.assert_not_awaited()
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_provider_returns_none(self):
        chat = _make_chat()
        redis = _make_redis()

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: None,
        )

        with _patch_drafter_helpers():
            result = await drafter.plan_draft(CHAT_ID)

        assert result is None
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_patch_returns_none(self):
        chat = _make_chat()
        redis = _make_redis()
        provider = _make_provider(parsed={"state_patch": [], "summary": "noop"})

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers():
            result = await drafter.plan_draft(CHAT_ID)

        assert result is None
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_op_type_filtered(self):
        chat = _make_chat()
        redis = _make_redis()

        provider = _make_provider(
            parsed={
                "state_patch": [
                    {
                        "type": "replace_single",
                        "field_key": "current_location",
                        "text": "Таверна",
                        "reason": "r",
                    },
                    {"type": "delete_field", "field_key": "x"},  # bad
                    "not-a-dict",  # bad
                ],
                "summary": "filtered",
            }
        )

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers():
            result = await drafter.plan_draft(CHAT_ID)

        assert result is not None
        assert len(result["state_patch"]) == 1
        assert result["state_patch"][0]["type"] == "replace_single"

    @pytest.mark.asyncio
    async def test_all_ops_invalid_returns_none(self):
        chat = _make_chat()
        redis = _make_redis()
        provider = _make_provider(
            parsed={
                "state_patch": [
                    {"type": "delete_field", "field_key": "x"},
                    {"type": "create_field", "field_key": "y"},
                ],
                "summary": "all bad",
            }
        )

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers():
            result = await drafter.plan_draft(CHAT_ID)

        assert result is None
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_provider_failure_returns_none(self):
        chat = _make_chat()
        redis = _make_redis()
        provider = _make_provider(raises=RuntimeError("LLM unreachable"))

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers():
            result = await drafter.plan_draft(CHAT_ID)

        assert result is None
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_chat_without_campaign_returns_none(self):
        redis = _make_redis()
        provider = _make_provider()

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(_make_chat(has_campaign=False)),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        result = await drafter.plan_draft(CHAT_ID)
        assert result is None
        provider.generate_json.assert_not_awaited()
        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ttl_is_3_hours(self):
        chat = _make_chat()
        redis = _make_redis()
        provider = _make_provider(
            parsed={
                "state_patch": [
                    {
                        "type": "add_list_item",
                        "field_key": "active_npcs",
                        "text": "Дракон",
                        "reason": "r",
                    },
                ],
                "summary": "add",
            }
        )

        drafter = CampaignStateDrafter(
            db_factory=_make_db_factory(chat),
            redis_client=redis,
            generation_provider_factory=lambda: provider,
        )

        with _patch_drafter_helpers():
            await drafter.plan_draft(CHAT_ID)

        assert _DRAFT_TTL_SECONDS == 10800
        call = redis.setex.call_args
        assert call.args[1] == 10800


class TestCampaignStateDrafterHelpers:
    def test_hash_hints_is_deterministic(self):
        # Дважды один и тот же список → одинаковый hash.
        h1 = CampaignStateDrafter._hash_hints(HINTS)
        h2 = CampaignStateDrafter._hash_hints(list(HINTS))
        assert h1 == h2
        assert len(h1) == 16

    def test_hash_hints_differs_on_different_data(self):
        h1 = CampaignStateDrafter._hash_hints(HINTS)
        h2 = CampaignStateDrafter._hash_hints(
            [dict(HINTS[0], confidence=0.1)]
        )
        assert h1 != h2

    def test_hash_hints_differs_on_reorder(self):
        # Hash чувствителен к порядку (как и сам list hints).
        h1 = CampaignStateDrafter._hash_hints(HINTS)
        h2 = CampaignStateDrafter._hash_hints(list(reversed(HINTS)))
        assert h1 != h2

    def test_filter_allowed_ops(self):
        raw = [
            {"type": "replace_single", "x": 1},
            {"type": "delete_field", "x": 2},
            {"type": "create_field", "x": 3},
            {"type": "add_list_item", "x": 4},
            "string",
            {"type": "remove_list_item", "x": 5},
        ]
        cleaned = CampaignStateDrafter._filter_allowed_ops(raw)
        assert {op["type"] for op in cleaned} == {
            "replace_single",
            "add_list_item",
            "remove_list_item",
        }
        assert len(cleaned) == 3
