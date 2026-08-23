"""Stage 8.2: tests for retrieval tool settings (PlatformSetting seeds).

We avoid pytest-alembic here because the migration uses Postgres-only
`ON CONFLICT (key) DO NOTHING` (incompatible with SQLite). Instead we
verify the migration's seed data structure and exercise `upgrade` /
`downgrade` against a captured record of SQL statements.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared_contracts.models import RetrievalPolicy

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "rag-backend"
    / "migrations"
    / "versions"
    / "0009_retrieval_tool_settings.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0009", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_revision_metadata():
    m = _load_migration()
    assert m.revision == "0009_retrieval_tool_settings"
    assert m.down_revision == "0008_campaign_state_versions"


def test_seed_rows_have_required_keys():
    m = _load_migration()
    expected_keys = {
        "retrieval.tool_enabled",
        "retrieval.policy",
        "retrieval.max_rounds_chat",
        "retrieval.max_rounds_assistive",
        "retrieval.evidence_token_budget",
    }
    actual_keys = {row["key"] for row in m._RETRIEVAL_TOOL_SETTINGS}
    assert actual_keys == expected_keys


def test_seed_rows_have_consistent_value_types():
    m = _load_migration()
    by_key = {row["key"]: row for row in m._RETRIEVAL_TOOL_SETTINGS}
    assert by_key["retrieval.tool_enabled"]["value_type"] == "bool"
    assert by_key["retrieval.tool_enabled"]["value"] == "true"
    assert by_key["retrieval.policy"]["value_type"] == "str"
    assert by_key["retrieval.policy"]["value"] == "grounded"
    assert by_key["retrieval.max_rounds_chat"]["value_type"] == "int"
    assert by_key["retrieval.max_rounds_chat"]["value"] == "2"
    assert by_key["retrieval.max_rounds_assistive"]["value_type"] == "int"
    assert by_key["retrieval.max_rounds_assistive"]["value"] == "1"
    assert by_key["retrieval.evidence_token_budget"]["value_type"] == "int"
    assert by_key["retrieval.evidence_token_budget"]["value"] == "4000"


def test_policy_enum_matches_seed_value():
    """Seed 'grounded' must round-trip through the RetrievalPolicy enum."""
    m = _load_migration()
    by_key = {row["key"]: row for row in m._RETRIEVAL_TOOL_SETTINGS}
    assert RetrievalPolicy(by_key["retrieval.policy"]["value"]) == RetrievalPolicy.GROUNDED


def test_upgrade_executes_insert_with_on_conflict():
    """upgrade() must call op.execute with an INSERT...ON CONFLICT statement
    so re-running the migration is idempotent on a populated DB."""
    m = _load_migration()
    captured: list[str] = []

    def _fake_execute(stmt):
        captured.append(str(stmt))

    with patch.object(m.op, "get_bind", return_value=MagicMock()), \
         patch.object(m.op, "execute", side_effect=_fake_execute):
        m.upgrade()

    inserts = [s for s in captured if "INSERT INTO platform_settings" in s]
    assert len(inserts) == len(m._RETRIEVAL_TOOL_SETTINGS), (
        f"Expected {len(m._RETRIEVAL_TOOL_SETTINGS)} inserts, got {len(inserts)}"
    )
    for s in inserts:
        assert "ON CONFLICT (key) DO NOTHING" in s, (
            "upgrade() must be idempotent — INSERT without ON CONFLICT will fail "
            "on re-run against an existing DB"
        )


def test_downgrade_executes_delete_for_all_seeded_keys():
    m = _load_migration()
    captured: list[str] = []

    def _fake_execute(stmt):
        captured.append(str(stmt))

    with patch.object(m.op, "get_bind", return_value=MagicMock()), \
         patch.object(m.op, "execute", side_effect=_fake_execute):
        m.downgrade()

    deletes = [s for s in captured if "DELETE FROM platform_settings" in s]
    assert len(deletes) == 1
    assert "WHERE key = ANY" in deletes[0]
