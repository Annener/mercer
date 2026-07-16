"""Unit tests for rag-indexer/app/update_mode/resolver.py.

Uses a mock DB client — no real Postgres or filesystem needed for most cases.
Filesystem cases use tmp_path and patch VAULT_ROOT.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "rag-indexer"))

from shared_contracts.models import (
    UpdateModeAction,
    UpdateModeAnchor,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveRequest,
)


def _make_db(doc_row=None):
    db = MagicMock()
    db._fetchrow = AsyncMock(return_value=doc_row)
    return db


def _make_request(
    intents,
    vault_ids=("vault-a",),
    default_vault_id="vault-a",
) -> UpdateModeResolveRequest:
    return UpdateModeResolveRequest(
        chat_id="chat-1",
        campaign_id="camp-1",
        domain_id="domain-1",
        vault_ids=list(vault_ids),
        intents=intents,
        default_vault_id=default_vault_id,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# CREATE action
# ---------------------------------------------------------------------------

class TestResolveCreate:
    @pytest.mark.asyncio
    async def test_create_resolves_to_pending(self, tmp_path: Path):
        from app.update_mode import resolver

        vault_dir = tmp_path / "vault-a"
        vault_dir.mkdir()
        (vault_dir / "_campaign_notes").mkdir()

        with patch.object(resolver, "VAULT_ROOT", tmp_path), \
             patch("app.update_mode.fs_git.VAULT_ROOT", tmp_path):

            intent = UpdateModeIntent(
                change_id="c1",
                action=UpdateModeAction.CREATE,
                description="new note",
                operation=UpdateModeOperation.CREATE_FILE,
                suggested_filename="_campaign_notes/session.md",
                content="# Session Note\nContent here.",
            )
            req = _make_request([intent])
            db = _make_db()

            resp = await resolver.resolve_changes(req, db)

        assert len(resp.changes) == 1
        change = resp.changes[0]
        assert change.status == UpdateModeChangeStatus.PENDING
        assert change.action == UpdateModeAction.CREATE
        assert change.vault_id == "vault-a"
        assert change.unified_diff != ""
        assert change.expected_sha256 is None

    @pytest.mark.asyncio
    async def test_create_invalid_vault_returns_failed(self, tmp_path: Path):
        from app.update_mode import resolver

        # vault dir does NOT exist
        with patch.object(resolver, "VAULT_ROOT", tmp_path), \
             patch("app.update_mode.fs_git.VAULT_ROOT", tmp_path):

            intent = UpdateModeIntent(
                change_id="c1",
                action=UpdateModeAction.CREATE,
                description="new note",
                operation=UpdateModeOperation.CREATE_FILE,
                suggested_filename="_campaign_notes/note.md",
                content="content",
            )
            req = _make_request([intent])
            db = _make_db()

            resp = await resolver.resolve_changes(req, db)

        assert resp.changes[0].status == UpdateModeChangeStatus.RESOLUTION_FAILED


# ---------------------------------------------------------------------------
# UPDATE action — document not found
# ---------------------------------------------------------------------------

class TestResolveUpdateDocNotFound:
    @pytest.mark.asyncio
    async def test_missing_doc_returns_failed(self, tmp_path: Path):
        from app.update_mode import resolver

        with patch.object(resolver, "VAULT_ROOT", tmp_path), \
             patch("app.update_mode.fs_git.VAULT_ROOT", tmp_path):

            intent = UpdateModeIntent(
                change_id="u1",
                action=UpdateModeAction.UPDATE,
                description="update",
                document_id="missing-doc",
                operation=UpdateModeOperation.APPEND_TO_FILE,
                content="addition",
            )
            req = _make_request([intent])
            db = _make_db(doc_row=None)  # simulate missing doc

            resp = await resolver.resolve_changes(req, db)

        change = resp.changes[0]
        assert change.status == UpdateModeChangeStatus.RESOLUTION_FAILED
        assert change.error_code == "document_not_found"


# ---------------------------------------------------------------------------
# UPDATE action — append_to_file
# ---------------------------------------------------------------------------

class TestResolveUpdateAppendToFile:
    @pytest.mark.asyncio
    async def test_append_to_file(self, tmp_path: Path):
        from app.update_mode import resolver

        vault_dir = tmp_path / "vault-a"
        vault_dir.mkdir()
        original_text = "# Doc\nOriginal content.\n"
        note_file = vault_dir / "note.md"
        note_file.write_text(original_text, encoding="utf-8")

        doc_row = MagicMock()
        doc_row.__getitem__ = lambda self, key: {
            "vault_id": "vault-a",
            "source_path": "note.md",
        }[key]

        with patch.object(resolver, "VAULT_ROOT", tmp_path), \
             patch("app.update_mode.fs_git.VAULT_ROOT", tmp_path):

            intent = UpdateModeIntent(
                change_id="u1",
                action=UpdateModeAction.UPDATE,
                description="append",
                document_id="doc-1",
                operation=UpdateModeOperation.APPEND_TO_FILE,
                content="Appended text.",
            )
            req = _make_request([intent])
            db = _make_db(doc_row=doc_row)

            resp = await resolver.resolve_changes(req, db)

        change = resp.changes[0]
        assert change.status == UpdateModeChangeStatus.PENDING
        assert "Appended text." in change.proposed_content
        assert change.expected_sha256 == _sha256(original_text)
        assert "+Appended text." in change.unified_diff
