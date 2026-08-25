"""Tests for create_field(commit=False) — atomic batch operations.

Применяется в apply_initial_state при создании accepted suggested_fields.
Все поля должны быть в одной транзакции с apply_initial, иначе при ошибке
поля останутся "осиротевшими" в БД.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from app.db.models import Base, Campaign, CampaignStateFieldConfig
from app.services.campaign_state_service import (
    campaign_state_field_service,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared_contracts.models import CampaignStateFieldConfigCreate


@pytest.fixture()
async def db_session():
    # Используем файл (не :memory:) чтобы разные сессии имели независимое
    # состояние транзакций. На :memory: все сессии делят один connection.
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )
        async with Session() as session:
            campaign = Campaign(
                id=uuid.uuid4(),
                name="test",
                domain_id="dnd",
                config_version=1,
            )
            session.add(campaign)
            await session.commit()
            yield session, str(campaign.id), engine
    finally:
        await engine.dispose()
        os.unlink(db_path)


def _make_payload(key: str) -> CampaignStateFieldConfigCreate:
    return CampaignStateFieldConfigCreate(
        key=key,
        label=f"Label for {key}",
        mode="single",
        enabled=True,
        display_order=0,
    )


async def test_create_field_commit_false_does_not_persist(db_session) -> None:
    """commit=False должен добавить в db.session, но НЕ коммитить.

    Проверяется через вторую сессию: дочерняя сессия не видит поле.
    """
    session, campaign_id, engine = db_session
    campaign_uuid = uuid.UUID(campaign_id)

    read = await campaign_state_field_service.create_field(
        db=session,
        campaign_id=campaign_uuid,
        payload=_make_payload("no_commit_field"),
        commit=False,
    )
    assert read.key == "no_commit_field"
    assert read.id is not None

    # Открываем НОВУЮ сессию — она не должна видеть поле (т.к. не было commit).
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as fresh:
        row = await fresh.get(CampaignStateFieldConfig, uuid.UUID(read.id))
        assert row is None, (
            "create_field(commit=False) shouldn't persist to DB"
        )


async def test_create_field_commit_true_persists_immediately(db_session) -> None:
    """commit=True (default) коммитит сразу — поле видно из другой сессии."""
    session, campaign_id, engine = db_session
    campaign_uuid = uuid.UUID(campaign_id)

    read = await campaign_state_field_service.create_field(
        db=session,
        campaign_id=campaign_uuid,
        payload=_make_payload("commit_field"),
    )
    assert read.key == "commit_field"

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as fresh:
        row = await fresh.get(CampaignStateFieldConfig, uuid.UUID(read.id))
        assert row is not None
        assert row.key == "commit_field"


async def test_create_field_commit_false_then_explicit_commit_persists(
    db_session,
) -> None:
    """commit=False + внешний commit → поле попадает в БД.

    Этот сценарий используется в apply_initial_state: create_field с
    commit=False, потом apply_initial делает общий commit.
    """
    session, campaign_id, engine = db_session
    campaign_uuid = uuid.UUID(campaign_id)

    read = await campaign_state_field_service.create_field(
        db=session,
        campaign_id=campaign_uuid,
        payload=_make_payload("manual_commit"),
        commit=False,
    )
    # Имитация внешнего commit, как делает apply_initial.
    await session.commit()

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as fresh:
        row = await fresh.get(CampaignStateFieldConfig, uuid.UUID(read.id))
        assert row is not None
        assert row.key == "manual_commit"


async def test_create_field_commit_false_rollback_drops_field(db_session) -> None:
    """commit=False + rollback → поле исчезает, не оставляя "осиротевших" записей.

    Это ключевая гарантия: если в apply_initial_state что-то упадёт ПОСЛЕ
    create_field, откат единой транзакции уберёт и поля тоже.
    """
    session, campaign_id, engine = db_session
    campaign_uuid = uuid.UUID(campaign_id)

    read = await campaign_state_field_service.create_field(
        db=session,
        campaign_id=campaign_uuid,
        payload=_make_payload("rolled_back"),
        commit=False,
    )
    # Имитация сбоя в apply_initial после создания поля.
    await session.rollback()

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as fresh:
        row = await fresh.get(CampaignStateFieldConfig, uuid.UUID(read.id))
        assert row is None, (
            "rollback should have dropped the field created with commit=False"
        )
