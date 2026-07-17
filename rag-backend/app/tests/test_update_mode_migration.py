"""Migration tests for 0005_campaign_update_git_identity.

Uses pytest-alembic (alembic_runner fixture) to run upgrade/downgrade
against a real in-process SQLite database so no Postgres is needed.

The test verifies:
1. upgrade   — git_author_name and git_author_email columns are added to
                the `vaults` table.
2. downgrade — both columns are removed.

Setup requirements (already in requirements-dev.txt or equivalent):
  pytest-alembic
  alembic
  sqlalchemy[asyncio] (sync engine for pytest-alembic is fine)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# pytest-alembic fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def alembic_config(tmp_path):
    """Return alembic config dict for pytest-alembic.

    pytest-alembic accepts either a dict or an alembic.config.Config object.
    We override `script_location` and `sqlalchemy.url` so the tests are
    self-contained and don’t touch a real Postgres instance.
    """
    import os
    from pathlib import Path

    # Find alembic.ini relative to this file (rag-backend/)
    backend_root = Path(__file__).parents[2]  # rag-backend/
    ini_path = backend_root / "alembic.ini"

    return {
        "file": str(ini_path),
        "script_location": str(backend_root / "alembic"),
        "sqlalchemy.url": "sqlite:///" + str(tmp_path / "test_migration.db"),
    }


@pytest.fixture()
def alembic_engine(alembic_config):
    """Provide a synchronous SQLAlchemy engine for pytest-alembic."""
    from sqlalchemy import create_engine

    engine = create_engine(alembic_config["sqlalchemy.url"])
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_columns(engine, table: str) -> set[str]:
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    return {col["name"] for col in inspector.get_columns(table)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_upgrade_adds_git_identity_columns(alembic_runner, alembic_engine):
    """After upgrading to head the vaults table must have the git identity columns."""
    alembic_runner.migrate_up_to("head")
    cols = _get_columns(alembic_engine, "vaults")
    assert "git_author_name" in cols, "git_author_name column missing after upgrade"
    assert "git_author_email" in cols, "git_author_email column missing after upgrade"


def test_downgrade_removes_git_identity_columns(alembic_runner, alembic_engine):
    """After downgrading past 0005 the git identity columns must be removed."""
    alembic_runner.migrate_up_to("head")
    # Downgrade one step from head (= revert 0005)
    alembic_runner.migrate_down_to("-1")
    cols = _get_columns(alembic_engine, "vaults")
    assert "git_author_name" not in cols, "git_author_name column still present after downgrade"
    assert "git_author_email" not in cols, "git_author_email column still present after downgrade"


def test_upgrade_is_idempotent(alembic_runner, alembic_engine):
    """Running upgrade twice (up → down → up) must leave the schema in a
    consistent state (no duplicate columns, no errors)."""
    alembic_runner.migrate_up_to("head")
    alembic_runner.migrate_down_to("-1")
    alembic_runner.migrate_up_to("head")
    cols = _get_columns(alembic_engine, "vaults")
    assert "git_author_name" in cols
    assert "git_author_email" in cols
