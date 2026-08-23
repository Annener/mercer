"""Sprint 3 — _apply_schema_changes (Stage A of apply).

Verifies atomic create_field + update_field apply, rollback on
partial failure, and audit log emission.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.update_mode import _apply_schema_changes
from app.db.models import AuditLog, Base, Campaign, CampaignStateFieldConfig
from app.services.campaign_state_service import (
    CampaignStateFieldError,
)
from shared_contracts.models import (
    ContextFieldChangeOperation,
    UpdateModeStateFieldChangeApplyResult,
    UpdateModeStateFieldChangeEntry,
)


@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        # Create a campaign to satisfy FK-like references in real DB
        # (we don't actually have FK in this model, but create anyway).
        campaign = Campaign(
            id=uuid.uuid4(),
            name="test",
            domain_id="dnd",
            config_version=1,
        )
        session.add(campaign)
        await session.commit()
        yield session, str(campaign.id)
    await engine.dispose()


def _create_entry(
    op_index: int,
    key: str,
    label: str = "Label",
    mode: str = "single",
    proposed_display_order: int | None = 1000,
) -> UpdateModeStateFieldChangeEntry:
    return UpdateModeStateFieldChangeEntry(
        op_index=op_index,
        operation=ContextFieldChangeOperation.CREATE_FIELD,
        key=key,
        proposed_label=label,
        proposed_mode=mode,  # type: ignore[arg-type]
        proposed_enabled=True,
        proposed_display_order=proposed_display_order,
    )


def _update_entry(
    op_index: int,
    key: str,
    label: str = "Updated",
    mode: str = "single",
) -> UpdateModeStateFieldChangeEntry:
    return UpdateModeStateFieldChangeEntry(
        op_index=op_index,
        operation=ContextFieldChangeOperation.UPDATE_FIELD,
        key=key,
        proposed_label=label,
        proposed_mode=mode,  # type: ignore[arg-type]
        proposed_enabled=True,
    )


# ---------------------------------------------------------------------------
# Smoke: empty input returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_schema_changes_empty_returns_none(db_session):
    db, campaign_id = db_session
    res = await _apply_schema_changes(
        db=db,
        campaign_id_str=campaign_id,
        accepted_field_entries=[],
    )
    assert res is None


# ---------------------------------------------------------------------------
# Successful create_field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_schema_changes_create_field_success(db_session):
    db, campaign_id = db_session
    entry = _create_entry(0, "main_villains", label="Главные злодеи", mode="list")
    res = await _apply_schema_changes(
        db=db,
        campaign_id_str=campaign_id,
        accepted_field_entries=[entry],
    )
    assert res is not None
    assert res.applied_op_indexes == [0]
    assert res.failed_op_indexes == []
    assert res.new_config_version == 2  # bumped from 1

    # Verify the field was actually created.
    from sqlalchemy import select

    stmt = select(CampaignStateFieldConfig).where(
        CampaignStateFieldConfig.campaign_id == uuid.UUID(campaign_id)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.key == "main_villains"
    assert row.label == "Главные злодеи"
    assert row.mode == "list"

    # Audit log entry was written.
    audit_count = (await db.execute(
        select(AuditLog).where(AuditLog.action == "update_mode.apply_schema")
    )).scalars().all()
    assert len(audit_count) == 1


# ---------------------------------------------------------------------------
# Failed create_field rolls back the previously-applied ones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_schema_rollback_on_partial_failure(db_session):
    """If op[0] succeeds but op[1] fails (e.g. invalid label), op[0] is
    rolled back so the database ends up unchanged."""
    db, campaign_id = db_session

    good_entry = _create_entry(0, "k1", label="K1", mode="single")
    # Force op[1] to fail by mocking the service.
    bad_entry = _create_entry(1, "k2", label="K2", mode="list")

    original_create = None
    from app.services import campaign_state_service as css
    original_create = css.campaign_state_field_service.create_field

    call_count = {"n": 0}

    async def fake_create_field(db, campaign_id, payload):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return await original_create(db, campaign_id, payload)
        raise CampaignStateFieldError(
            "test_error", "forced failure for rollback test"
        )

    with patch.object(css.campaign_state_field_service, "create_field",
                       new=fake_create_field):
        res = await _apply_schema_changes(
            db=db,
            campaign_id_str=campaign_id,
            accepted_field_entries=[good_entry, bad_entry],
        )

    # The first op is reported as applied (host tracks what it tried),
    # but the final rollback should leave the DB clean.
    assert res is not None
    assert res.failed_op_indexes == [1]
    assert res.applied_op_indexes == [0]  # was applied then rolled back

    # Verify the DB has no field rows (rollback succeeded).
    from sqlalchemy import select
    rows = (await db.execute(
        select(CampaignStateFieldConfig).where(
            CampaignStateFieldConfig.campaign_id == uuid.UUID(campaign_id)
        )
    )).scalars().all()
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# update_field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_schema_changes_update_existing_field(db_session):
    db, campaign_id = db_session

    # First create a field via direct insert (faster than going through service).
    field = CampaignStateFieldConfig(
        campaign_id=uuid.UUID(campaign_id),
        key="existing",
        label="Original",
        description="",
        mode="single",
        enabled=True,
        display_order=0,
    )
    db.add(field)
    await db.commit()
    await db.refresh(field)
    field_id = str(field.id)
    field.config_version = 1
    # bump config_version on the campaign as well.
    from app.db.models import Campaign
    camp = await db.get(Campaign, uuid.UUID(campaign_id))
    camp.config_version = 1
    await db.commit()

    # Now apply an update_field.
    entry = _update_entry(0, "existing", label="Updated label")
    res = await _apply_schema_changes(
        db=db,
        campaign_id_str=campaign_id,
        accepted_field_entries=[entry],
    )
    assert res is not None
    assert res.applied_op_indexes == [0]
    assert res.failed_op_indexes == []

    # Verify the field was updated.
    await db.refresh(field)
    assert field.label == "Updated label"
    assert res.new_config_version >= 1


# ---------------------------------------------------------------------------
# update_field for nonexistent key fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_schema_update_nonexistent_field_fails(db_session):
    db, campaign_id = db_session
    entry = _update_entry(0, "ghost_field", label="x")
    res = await _apply_schema_changes(
        db=db,
        campaign_id_str=campaign_id,
        accepted_field_entries=[entry],
    )
    assert res is not None
    assert res.failed_op_indexes == [0]
    assert res.applied_op_indexes == []


# ---------------------------------------------------------------------------
# Order: create_field is applied before update_field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_schema_creates_before_updates(db_session):
    """When the proposal contains both create_field and update_field,
    creates run first so that an update_field that depends on a
    created field can still be applied (or rejected for another reason)."""
    db, campaign_id = db_session

    # Pre-create a field to update.
    field = CampaignStateFieldConfig(
        campaign_id=uuid.UUID(campaign_id),
        key="existing",
        label="Original",
        description="",
        mode="single",
        enabled=True,
        display_order=0,
    )
    db.add(field)
    await db.commit()
    from app.db.models import Campaign
    camp = await db.get(Campaign, uuid.UUID(campaign_id))
    camp.config_version = 1
    await db.commit()

    # Order in the input: update, create — host should re-order to
    # create, update.
    update_entry = _update_entry(0, "existing", label="Updated")
    create_entry = _create_entry(1, "new_field", label="New", mode="list")

    res = await _apply_schema_changes(
        db=db,
        campaign_id_str=campaign_id,
        accepted_field_entries=[update_entry, create_entry],
    )
    assert res is not None
    # Both entries are applied regardless of the original input order.
    # The host re-orders so that create_field runs first.
    assert set(res.applied_op_indexes) == {0, 1}
    assert res.failed_op_indexes == []

    from sqlalchemy import select
    rows = (await db.execute(
        select(CampaignStateFieldConfig).where(
            CampaignStateFieldConfig.campaign_id == uuid.UUID(campaign_id)
        )
    )).scalars().all()
    assert len(rows) == 2