"""Tests for migration 0013_state_values_composite_pkey.

Migration changes campaign_state_values PK from single-column (version_id)
to composite (version_id, field_id). This is the schema-level fix for
the bug where multi-row INSERT failed with `Key (version_id) already
exists` when apply_initial had multiple single-fields.

We don't run the migration against a real DB (no Postgres in CI for
unit tests) — we verify the SQL emitted is correct.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "rag-backend"
    / "migrations"
    / "versions"
    / "0013_state_values_composite_pkey.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0013", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_revision_metadata():
    m = _load_migration()
    assert m.revision == "0013_state_values_composite_pkey"
    assert m.down_revision == "0012_grounded_knobs"


def test_upgrade_drops_old_pkey_and_creates_composite():
    """upgrade() must DROP old single-column PK and ADD composite PK."""
    m = _load_migration()
    captured: list[str] = []

    def _fake_execute(stmt):
        captured.append(str(stmt))

    with patch.object(m.op, "get_bind", return_value=MagicMock()), \
         patch.object(m.op, "execute", side_effect=_fake_execute):
        m.upgrade()

    drop_stmt = next(
        (s for s in captured if "DROP CONSTRAINT campaign_state_values_pkey" in s),
        None,
    )
    assert drop_stmt is not None, (
        "upgrade() must DROP CONSTRAINT campaign_state_values_pkey. "
        f"Captured: {captured}"
    )

    add_stmt = next(
        (s for s in captured if "ADD PRIMARY KEY" in s and "version_id" in s and "field_id" in s),
        None,
    )
    assert add_stmt is not None, (
        "upgrade() must ADD PRIMARY KEY (version_id, field_id) — composite. "
        f"Captured: {captured}"
    )
    assert "(version_id, field_id)" in add_stmt, (
        f"Expected composite PK on (version_id, field_id), got: {add_stmt}"
    )


def test_downgrade_restores_single_column_pk():
    """downgrade() must restore the original (broken) single-column PK.

    This is intentional — downgrade allows rollback but the single-column
    PK reintroduces the original bug. The migration comment warns about this.
    """
    m = _load_migration()
    captured: list[str] = []

    def _fake_execute(stmt):
        captured.append(str(stmt))

    with patch.object(m.op, "get_bind", return_value=MagicMock()), \
         patch.object(m.op, "execute", side_effect=_fake_execute):
        m.downgrade()

    add_stmt = next(
        (s for s in captured if "ADD PRIMARY KEY" in s),
        None,
    )
    assert add_stmt is not None, f"downgrade() must ADD PRIMARY KEY, got: {captured}"
    # Downgrade restores single-column PK on version_id.
    assert "version_id)" in add_stmt or "(version_id " in add_stmt, (
        f"downgrade() should restore single-column PK on version_id, got: {add_stmt}"
    )
