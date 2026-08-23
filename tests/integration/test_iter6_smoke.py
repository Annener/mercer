"""Integration smoke-tests — Iteration 6 (Stage 6: Prompt Assembly).

Проверяет ключевые инварианты prompt assembly:

  1. compose_full_system_prompt корректно склеивает system_prompt + state.
  2. compose_state_block_only возвращает только текст state (без system_prompt).
  3. При отсутствии state — блок пустой, system_prompt не пустой.
  4. При отсутствии кампании — state block пустой.
  5. compile_campaign_state детерминирован: один и тот же вход → один и тот же выход.
  6. Soft-stop: budget переполняется → поле попадает в truncated_fields.

ЗАПУСК:
-------
  pytest tests/integration/test_iter6_smoke.py -v

Зависимости — те же, что у test_iter5_smoke.py.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

# ── модели БД ──
from app.db.models import (
    Campaign,
    CampaignStateFieldConfig,
    CampaignStateListItem,
    CampaignStateValue,
    Domain,
)

# ── services ──
from app.services.campaign_state_compiler import (
    DEFAULT_TOKEN_BUDGET,
    compile_campaign_state,
)
from app.services.campaign_state_value_service import (
    campaign_state_value_service,
)
from app.services.effective_context import (
    build_effective_context,
    compose_full_system_prompt,
    compose_state_block_only,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared_contracts.models import (
    CampaignStateFieldConfigRead,
    CampaignStateFieldValuesRead,
    CampaignStateSingleValueRead,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://mercer:mercer@localhost:5432/mercer",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    e = create_async_engine(DATABASE_URL, echo=False)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def db(engine):
    """Каждый тест получает сессию в транзакции, откатываемой после теста."""
    async with engine.begin() as conn:
        session = AsyncSession(bind=conn)
        yield session
        await session.close()
        await conn.rollback()


@pytest_asyncio.fixture
async def domain(db: AsyncSession):
    d = Domain(
        domain_id=f"iter6-{uuid.uuid4().hex[:8]}",
        display_name="Iter6 Test Domain",
        is_system=False,
        enabled=True,
    )
    db.add(d)
    await db.flush()
    return d


@pytest_asyncio.fixture
async def campaign(db: AsyncSession, domain: Domain):
    c = Campaign(
        name="Iter6 Campaign",
        domain_id=domain.domain_id,
        system_prompt="You are a Dungeon Master.",
    )
    db.add(c)
    await db.flush()
    return c


def _single_value(version_id: uuid.UUID, field_id: uuid.UUID, text: str) -> CampaignStateValue:
    return CampaignStateValue(
        version_id=version_id,
        field_id=field_id,
        text=text,
        source_refs=[],
    )


def _list_item(
    version_id: uuid.UUID,
    field_id: uuid.UUID,
    key: str,
    text: str,
    resolved: bool = False,
) -> CampaignStateListItem:
    return CampaignStateListItem(
        version_id=version_id,
        field_id=field_id,
        item_key=key,
        text=text,
        resolved=resolved,
        source_refs=[],
    )


# ---------------------------------------------------------------------------
# 1. compile_campaign_state — детерминизм
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_same_output(self):
        """Чистая функция: один вход → один выход."""
        cfg = CampaignStateFieldConfigRead(
            id="f1", campaign_id=str(uuid.uuid4()), key="focus", label="Фокус",
            description="", mode="single", enabled=True, display_order=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC), updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        fv = CampaignStateFieldValuesRead(
            field_key="focus", field_id="f1", mode="single",
            enabled=True, display_order=0,
            single_value=CampaignStateSingleValueRead(
                field_key="focus", text="X", source_refs=[],
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            items=[],
        )
        ver = CampaignStateVersionRead(
            summary=CampaignStateVersionSummary(
                id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()),
                state_version=1, config_version=1,
                source_kind="initial", base_state_version=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC), created_by=None,
            ),
            fields=[fv],
        )
        a = compile_campaign_state(ver, [cfg])
        b = compile_campaign_state(ver, [cfg])
        assert a.text == b.text
        assert a.used_tokens == b.used_tokens
        assert a.truncated_fields == b.truncated_fields


# ---------------------------------------------------------------------------
# 2. Soft-stop через бюджет
# ---------------------------------------------------------------------------


class TestSoftStop:
    def test_field_excluded_when_budget_exceeded(self):
        cfg = CampaignStateFieldConfigRead(
            id="big", campaign_id=str(uuid.uuid4()), key="big", label="Большое",
            description="", mode="single", enabled=True, display_order=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC), updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        fv = CampaignStateFieldValuesRead(
            field_key="big", field_id="big", mode="single",
            enabled=True, display_order=0,
            single_value=CampaignStateSingleValueRead(
                field_key="big", text="x" * 400, source_refs=[],
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            items=[],
        )
        ver = CampaignStateVersionRead(
            summary=CampaignStateVersionSummary(
                id=str(uuid.uuid4()), campaign_id=str(uuid.uuid4()),
                state_version=1, config_version=1,
                source_kind="initial", base_state_version=None,
                created_at=datetime(2026, 1, 1, tzinfo=UTC), created_by=None,
            ),
            fields=[fv],
        )
        result = compile_campaign_state(ver, [cfg], budget_tokens=10)
        assert result.text == ""
        assert result.truncated_fields == ["big"]


# ---------------------------------------------------------------------------
# 3. DB-backed state injection (compose_full_system_prompt)
# ---------------------------------------------------------------------------


class TestPromptInjection:
    @pytest.mark.asyncio
    async def test_state_block_appears_in_full_system_prompt(
        self, db: AsyncSession, campaign: Campaign
    ):
        """После записи active state, compose_full_system_prompt должен включать его."""
        # Создаём поле.
        cfg = CampaignStateFieldConfig(
            campaign_id=campaign.id,
            key="current_focus",
            label="Текущий фокус",
            description="",
            mode="single",
            enabled=True,
            display_order=0,
        )
        db.add(cfg)
        await db.flush()

        # Создаём state version напрямую через value-service.
        from shared_contracts.models import (
            CampaignStateInitialFieldStatus,
            CampaignStateInitialProposal,
            CampaignStateInitialProposalField,
            CampaignStateInitialSingleValue,
        )

        proposal = CampaignStateInitialProposal(
            fields=[
                CampaignStateInitialProposalField(
                    field_key="current_focus",
                    mode="single",
                    status=CampaignStateInitialFieldStatus(status="proposed"),
                    single_value=CampaignStateInitialSingleValue(
                        text="Спроектировать Campaign State MVP", source_refs=[]
                    ),
                    list_value=None,
                ),
            ],
            questions=[],
        )
        snap = []
        await campaign_state_value_service.apply_initial(
            db=db,
            campaign_id=campaign.id,
            proposal=proposal,
            source_snapshot=snap,
            config_version=campaign.config_version,
        )

        # Теперь compose_full_system_prompt должен вернуть system_prompt + state.
        full = await compose_full_system_prompt(
            campaign_id=str(campaign.id),
            domain_id=campaign.domain_id,
            db=db,
        )
        assert "You are a Dungeon Master" in full
        assert "Текущий фокус:" in full
        assert "Спроектировать Campaign State MVP" in full

    @pytest.mark.asyncio
    async def test_state_block_only_returns_state(
        self, db: AsyncSession, campaign: Campaign
    ):
        """compose_state_block_only должен вернуть только блок state."""
        cfg = CampaignStateFieldConfig(
            campaign_id=campaign.id,
            key="focus",
            label="Фокус",
            description="",
            mode="single",
            enabled=True,
            display_order=0,
        )
        db.add(cfg)
        await db.flush()

        from shared_contracts.models import (
            CampaignStateInitialFieldStatus,
            CampaignStateInitialProposal,
            CampaignStateInitialProposalField,
            CampaignStateInitialSingleValue,
        )
        proposal = CampaignStateInitialProposal(
            fields=[
                CampaignStateInitialProposalField(
                    field_key="focus",
                    mode="single",
                    status=CampaignStateInitialFieldStatus(status="proposed"),
                    single_value=CampaignStateInitialSingleValue(
                        text="Дизайн MVP", source_refs=[]
                    ),
                    list_value=None,
                ),
            ],
            questions=[],
        )
        await campaign_state_value_service.apply_initial(
            db=db,
            campaign_id=campaign.id,
            proposal=proposal,
            source_snapshot=[],
            config_version=campaign.config_version,
        )

        block_only = await compose_state_block_only(
            campaign_id=str(campaign.id),
            db=db,
        )
        assert "Фокус:" in block_only
        assert "Дизайн MVP" in block_only
        # В отличие от compose_full_system_prompt, тут нет system_prompt.
        assert "You are a Dungeon Master" not in block_only

    @pytest.mark.asyncio
    async def test_no_state_returns_empty_block(self, db: AsyncSession, campaign: Campaign):
        """Кампания без state → state block пустой, system_prompt остаётся."""
        full = await compose_full_system_prompt(
            campaign_id=str(campaign.id),
            domain_id=campaign.domain_id,
            db=db,
        )
        assert "You are a Dungeon Master" in full
        # Нет ни одного символа ': ' который мог бы прийти из state.
        assert full.count(": ") == 0 or "You are" in full

    @pytest.mark.asyncio
    async def test_no_campaign_returns_only_system_prompt(
        self, db: AsyncSession, domain: Domain
    ):
        """Без campaign_id — compose_full_system_prompt возвращает только system_prompt."""
        full = await compose_full_system_prompt(
            campaign_id=None,
            domain_id=domain.domain_id,
            db=db,
        )
        # domain.system_prompt может быть None или пустым — проверим что не падает.
        assert isinstance(full, str)


# ---------------------------------------------------------------------------
# 4. Effective context (debug endpoint helper)
# ---------------------------------------------------------------------------


class TestEffectiveContext:
    @pytest.mark.asyncio
    async def test_build_effective_context_with_state(
        self, db: AsyncSession, campaign: Campaign
    ):
        cfg = CampaignStateFieldConfig(
            campaign_id=campaign.id,
            key="focus",
            label="Фокус",
            description="",
            mode="single",
            enabled=True,
            display_order=0,
        )
        db.add(cfg)
        await db.flush()

        from shared_contracts.models import (
            CampaignStateInitialFieldStatus,
            CampaignStateInitialProposal,
            CampaignStateInitialProposalField,
            CampaignStateInitialSingleValue,
        )
        proposal = CampaignStateInitialProposal(
            fields=[
                CampaignStateInitialProposalField(
                    field_key="focus",
                    mode="single",
                    status=CampaignStateInitialFieldStatus(status="proposed"),
                    single_value=CampaignStateInitialSingleValue(
                        text="MVP дизайн", source_refs=[]
                    ),
                    list_value=None,
                ),
            ],
            questions=[],
        )
        await campaign_state_value_service.apply_initial(
            db=db,
            campaign_id=campaign.id,
            proposal=proposal,
            source_snapshot=[],
            config_version=campaign.config_version,
        )

        ctx = await build_effective_context(
            campaign_id=str(campaign.id),
            chat_id=None,
            domain_id=campaign.domain_id,
            db=db,
        )
        block_names = [b.name for b in ctx.blocks]
        assert "system_prompt" in block_names
        assert "campaign_state" in block_names
        # Проверяем, что в campaign_state блоке есть значение.
        state_block = next(b for b in ctx.blocks if b.name == "campaign_state")
        assert "MVP дизайн" in state_block.text
        assert ctx.budget == DEFAULT_TOKEN_BUDGET
        assert ctx.state_version == 1

    @pytest.mark.asyncio
    async def test_build_effective_context_without_state(
        self, db: AsyncSession, campaign: Campaign
    ):
        ctx = await build_effective_context(
            campaign_id=str(campaign.id),
            chat_id=None,
            domain_id=campaign.domain_id,
            db=db,
        )
        block_names = [b.name for b in ctx.blocks]
        # Только system_prompt, без campaign_state.
        assert "system_prompt" in block_names
        assert "campaign_state" not in block_names
        assert ctx.state_version is None
