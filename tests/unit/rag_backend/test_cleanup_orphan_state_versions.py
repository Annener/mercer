"""Tests for cleanup_orphan_state_versions.py script.

Проверяем, что скрипт:
    1. По умолчанию dry-run — не удаляет.
    2. С --apply удаляет все patch versions.
    3. НЕ трогает initial versions.
    4. Идемпотентен (повторный запуск не падает).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from app.db.models import (
    Base,
    Campaign,
    CampaignStateListItem,
    CampaignStateVersion,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture()
async def db_with_patches():
    """Создаёт in-memory-эквивалент: файл-SQLite с кампанией, у которой
    есть 2 patch versions (один пустой, один с list_items) и 1 initial.
    """
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            campaign = Campaign(
                id=uuid.uuid4(),
                name="Test Cleanup",
                domain_id="dnd",
                config_version=1,
            )
            session.add(campaign)
            await session.flush()

            # patch version 1 — empty.
            v_patch1 = CampaignStateVersion(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                state_version=2,
                config_version=1,
                source_kind="patch",
            )
            # patch version 2 — с list_items.
            v_patch2 = CampaignStateVersion(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                state_version=3,
                config_version=1,
                source_kind="patch",
            )
            # initial version — НЕ должен удаляться.
            v_initial = CampaignStateVersion(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                state_version=1,
                config_version=1,
                source_kind="initial",
            )
            session.add_all([v_patch1, v_patch2, v_initial])
            await session.flush()

            # list_items только в patch2.
            list_item = CampaignStateListItem(
                id=uuid.uuid4(),
                version_id=v_patch2.id,
                field_id=uuid.uuid4(),
                item_key="li-1",
                text="some item",
                source_refs=[],
            )
            session.add(list_item)
            await session.commit()

        yield db_path, [v_patch1.id, v_patch2.id], v_initial.id
    finally:
        await engine.dispose()
        if os.path.exists(db_path):
            os.unlink(db_path)


def _run_script(db_path: str, apply: bool) -> subprocess.CompletedProcess:
    """Запустить cleanup-скрипт как subprocess."""
    # tests/unit/rag_backend/ → repo_root = ../../../
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    script_path = repo_root / "scripts" / "cleanup_orphan_state_versions.py"
    assert script_path.exists(), f"Script not found: {script_path}"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    cmd = [sys.executable, str(script_path)]
    if apply:
        cmd.append("--apply")
    return subprocess.run(
        cmd,
        env=env,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _count_versions(db_path: str) -> dict[str, int]:
    """Сколько versions каждого типа в БД."""
    import asyncio

    async def _inner():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT source_kind, COUNT(*) FROM campaign_state_versions GROUP BY source_kind")
                )
                return {row[0]: row[1] for row in result}
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_dry_run_does_not_delete_anything(db_with_patches) -> None:
    """Dry-run (по умолчанию) НЕ удаляет ни одной version."""
    db_path, _patch_ids, _initial_id = db_with_patches

    result = _run_script(db_path, apply=False)

    assert result.returncode == 0, (
        f"Script failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "Dry-run mode" in result.stdout

    counts = _count_versions(db_path)
    assert counts == {"patch": 2, "initial": 1}, (
        f"Expected 2 patches + 1 initial after dry-run, got {counts}"
    )


def test_apply_deletes_all_patch_versions(db_with_patches) -> None:
    """С --apply удаляет все patch versions, оставляя initial."""
    db_path, _patch_ids, _initial_id = db_with_patches

    result = _run_script(db_path, apply=True)

    assert result.returncode == 0, (
        f"Script failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "DELETING" in result.stdout
    assert "Done. Deleted 2 patch version(s)" in result.stdout

    counts = _count_versions(db_path)
    assert counts == {"initial": 1}, (
        f"Expected only initial after apply, got {counts}"
    )

    # Cascade FK: list_items в patch2 тоже должны быть удалены.
    import asyncio

    async def _count_list_items():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT COUNT(*) FROM campaign_state_list_items")
                )
                return result.scalar()
        finally:
            await engine.dispose()

    list_items_count = asyncio.run(_count_list_items())
    assert list_items_count == 0, (
        f"Expected list_items to be cascade-deleted, got {list_items_count}"
    )


def test_apply_is_idempotent(db_with_patches) -> None:
    """Повторный --apply после первого не падает (и нечего удалять)."""
    db_path, _patch_ids, _initial_id = db_with_patches

    # Первый apply удаляет patches.
    first = _run_script(db_path, apply=True)
    assert first.returncode == 0, first.stderr

    # Второй apply — patches уже удалены, скрипт должен корректно отработать.
    second = _run_script(db_path, apply=True)
    assert second.returncode == 0, second.stderr
    assert "No patch versions found" in second.stdout

    counts = _count_versions(db_path)
    assert counts == {"initial": 1}
