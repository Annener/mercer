"""Tests for Campaign Update Mode Pydantic contracts."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeAnchor,
    UpdateModeApplyChange,
    UpdateModeApplyRequest,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveRequest,
    UpdateModeReviewRequest,
    UpdateModeSession,
)
from datetime import datetime, timezone
import uuid


# ---------------------------------------------------------------------------
# UpdateModeIntent validators
# ---------------------------------------------------------------------------

class TestUpdateModeIntent:
    def _create_intent(self, **overrides) -> UpdateModeIntent:
        defaults = dict(
            change_id="c1",
            action=UpdateModeAction.CREATE,
            description="add new note",
            operation=UpdateModeOperation.CREATE_FILE,
            suggested_filename="_campaign_notes/note.md",
            content="# Note\nContent here",
        )
        defaults.update(overrides)
        return UpdateModeIntent(**defaults)

    def test_create_valid(self):
        i = self._create_intent()
        assert i.change_id == "c1"
        assert i.action == UpdateModeAction.CREATE

    def test_create_requires_suggested_filename(self):
        with pytest.raises(ValidationError, match="suggested_filename"):
            self._create_intent(suggested_filename=None)

    def test_create_must_not_have_document_id(self):
        with pytest.raises(ValidationError, match="document_id"):
            self._create_intent(document_id="some-doc-id")

    def test_create_must_not_have_anchor(self):
        with pytest.raises(ValidationError, match="anchor"):
            self._create_intent(
                anchor=UpdateModeAnchor(kind="markdown_heading", value="# Intro")
            )

    def test_update_valid_append_to_file(self):
        i = UpdateModeIntent(
            change_id="u1",
            action=UpdateModeAction.UPDATE,
            description="append to file",
            document_id="doc-123",
            operation=UpdateModeOperation.APPEND_TO_FILE,
            content="new content",
        )
        assert i.anchor is None

    def test_update_append_after_section_requires_heading_anchor(self):
        with pytest.raises(ValidationError, match="anchor"):
            UpdateModeIntent(
                change_id="u2",
                action=UpdateModeAction.UPDATE,
                description="append after section",
                document_id="doc-123",
                operation=UpdateModeOperation.APPEND_AFTER_SECTION,
                content="new content",
                # missing anchor
            )

    def test_update_replace_unique_text_requires_exact_text_anchor(self):
        with pytest.raises(ValidationError, match="anchor"):
            UpdateModeIntent(
                change_id="u3",
                action=UpdateModeAction.UPDATE,
                description="replace text",
                document_id="doc-123",
                operation=UpdateModeOperation.REPLACE_UNIQUE_TEXT,
                content="replacement",
                # missing anchor
            )

    def test_update_requires_document_id(self):
        with pytest.raises(ValidationError, match="document_id"):
            UpdateModeIntent(
                change_id="u4",
                action=UpdateModeAction.UPDATE,
                description="no doc id",
                operation=UpdateModeOperation.APPEND_TO_FILE,
                content="x",
            )

    def test_self_referential_change_id_not_tested_here(self):
        # change_id uniqueness is validated at batch level
        i = self._create_intent(change_id="same")
        assert i.change_id == "same"


# ---------------------------------------------------------------------------
# UpdateModeResolveRequest validators
# ---------------------------------------------------------------------------

class TestUpdateModeResolveRequest:
    def _base(self, **overrides):
        defaults = dict(
            chat_id="chat-1",
            campaign_id="camp-1",
            domain_id="domain-1",
            vault_ids=["vault-a"],
            intents=[
                UpdateModeIntent(
                    change_id="c1",
                    action=UpdateModeAction.CREATE,
                    description="note",
                    operation=UpdateModeOperation.CREATE_FILE,
                    suggested_filename="_campaign_notes/note.md",
                    content="content",
                )
            ],
            default_vault_id="vault-a",
        )
        defaults.update(overrides)
        return UpdateModeResolveRequest(**defaults)

    def test_valid(self):
        r = self._base()
        assert r.default_vault_id == "vault-a"

    def test_default_vault_must_be_in_vault_ids(self):
        with pytest.raises(ValidationError, match="default_vault_id must be in vault_ids"):
            self._base(default_vault_id="vault-z")

    def test_empty_vault_ids_rejected(self):
        with pytest.raises(ValidationError):
            self._base(vault_ids=[])


# ---------------------------------------------------------------------------
# UpdateModeApplyChange validators
# ---------------------------------------------------------------------------

class TestUpdateModeApplyChange:
    def test_update_requires_sha(self):
        with pytest.raises(ValidationError, match="expected_sha256"):
            UpdateModeApplyChange(
                change_id="c1",
                vault_id="v1",
                file_path="notes/note.md",
                action=UpdateModeAction.UPDATE,
                proposed_content="new content",
                expected_sha256=None,
            )

    def test_create_must_not_have_sha(self):
        with pytest.raises(ValidationError, match="expected_sha256"):
            UpdateModeApplyChange(
                change_id="c1",
                vault_id="v1",
                file_path="_campaign_notes/note.md",
                action=UpdateModeAction.CREATE,
                proposed_content="content",
                expected_sha256="abc123",
            )

    def test_create_valid(self):
        c = UpdateModeApplyChange(
            change_id="c1",
            vault_id="v1",
            file_path="_campaign_notes/note.md",
            action=UpdateModeAction.CREATE,
            proposed_content="content",
        )
        assert c.expected_sha256 is None

    def test_update_valid(self):
        c = UpdateModeApplyChange(
            change_id="c1",
            vault_id="v1",
            file_path="notes/note.md",
            action=UpdateModeAction.UPDATE,
            proposed_content="new content",
            expected_sha256="deadbeef",
        )
        assert c.expected_sha256 == "deadbeef"


# ---------------------------------------------------------------------------
# UpdateModeApplyRequest validators
# ---------------------------------------------------------------------------

class TestUpdateModeApplyRequest:
    def _change(self, change_id="c1", vault_id="v1", file_path="_campaign_notes/a.md"):
        return UpdateModeApplyChange(
            change_id=change_id,
            vault_id=vault_id,
            file_path=file_path,
            action=UpdateModeAction.CREATE,
            proposed_content="content",
        )

    def test_valid(self):
        r = UpdateModeApplyRequest(
            apply_id="apply-1",
            chat_id="chat-1",
            campaign_id="camp-1",
            accepted_changes=[self._change()],
        )
        assert r.apply_id == "apply-1"

    def test_duplicate_change_ids_rejected(self):
        with pytest.raises(ValidationError, match="change_id must be unique"):
            UpdateModeApplyRequest(
                apply_id="a",
                chat_id="c",
                campaign_id="cp",
                accepted_changes=[self._change("same"), self._change("same")],
            )

    def test_duplicate_vault_path_pairs_rejected(self):
        with pytest.raises(ValidationError, match="vault_id.*file_path.*unique"):
            UpdateModeApplyRequest(
                apply_id="a",
                chat_id="c",
                campaign_id="cp",
                accepted_changes=[
                    self._change("c1", "v1", "_campaign_notes/a.md"),
                    self._change("c2", "v1", "_campaign_notes/a.md"),
                ],
            )


# ---------------------------------------------------------------------------
# UpdateModeReviewRequest validators
# ---------------------------------------------------------------------------

class TestUpdateModeReviewRequest:
    def test_valid_accept_only(self):
        r = UpdateModeReviewRequest(accepted_change_ids=["c1"])
        assert r.accepted_change_ids == ["c1"]

    def test_valid_reject_only(self):
        r = UpdateModeReviewRequest(rejected_change_ids=["c1"])
        assert r.rejected_change_ids == ["c1"]

    def test_empty_both_rejected(self):
        with pytest.raises(ValidationError, match="at least one"):
            UpdateModeReviewRequest()

    def test_overlap_rejected(self):
        with pytest.raises(ValidationError, match="cannot be both"):
            UpdateModeReviewRequest(
                accepted_change_ids=["c1"],
                rejected_change_ids=["c1"],
            )


# ---------------------------------------------------------------------------
# ResolvedUpdateModeChange
# ---------------------------------------------------------------------------

class TestResolvedUpdateModeChange:
    def test_default_status_pending(self):
        c = ResolvedUpdateModeChange(
            change_id="c1",
            action=UpdateModeAction.CREATE,
            description="note",
        )
        assert c.status == UpdateModeChangeStatus.PENDING

    def test_resolution_failed(self):
        c = ResolvedUpdateModeChange(
            change_id="c2",
            action=UpdateModeAction.UPDATE,
            description="update",
            status=UpdateModeChangeStatus.RESOLUTION_FAILED,
            error_code="document_not_found",
            error_message="doc-x not found",
        )
        assert c.error_code == "document_not_found"
