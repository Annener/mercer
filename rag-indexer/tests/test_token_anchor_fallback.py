"""Integration tests for token-anchor fallback in resolver._resolve_one().

Мокируются: _lookup_document, resolve_vault_root, resolve_file_path,
read_original_utf8 — реальная ФС и БД не используются.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.update_mode.resolver import _resolve_one
from shared_contracts.models import (
    UpdateModeAction,
    UpdateModeAnchor,
    UpdateModeChangeStatus,
    UpdateModeIntent,
    UpdateModeOperation,
    UpdateModeResolveRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(
    raw_content: str,
    anchor_value: str,
    op: UpdateModeOperation = UpdateModeOperation.REPLACE_UNIQUE_TEXT,
    new_content: str = "REPLACED",
) -> UpdateModeIntent:
    """Construct a minimal UPDATE intent for tests."""
    return UpdateModeIntent(
        change_id=str(uuid.uuid4()),
        action=UpdateModeAction.UPDATE,
        document_id="doc-001",
        description="test intent",
        operation=op,
        anchor=UpdateModeAnchor(value=anchor_value),
        content=new_content,
    )


def _make_request(vault_id: str = "vault-1") -> UpdateModeResolveRequest:
    """Construct a minimal resolve request."""
    return UpdateModeResolveRequest(
        intents=[],
        vault_ids=[vault_id],
        default_vault_id=vault_id,
    )


def _fake_vault_root() -> Path:
    return Path("/fake/vault")


def _fake_file_path() -> Path:
    return Path("/fake/vault/notes/doc.md")


# ---------------------------------------------------------------------------
# Shared mock context manager
# ---------------------------------------------------------------------------

class _ResolverMocks:
    """Patch everything resolver.py touches outside of text_ops / token_anchor."""

    def __init__(self, raw_content: str, vault_id: str = "vault-1"):
        self.raw_content = raw_content
        self.vault_id = vault_id
        self._patches: list = []

    def start(self):
        patches = [
            patch(
                "app.update_mode.resolver._lookup_document",
                new=AsyncMock(return_value={"vault_id": self.vault_id, "source_path": "notes/doc.md"}),
            ),
            patch(
                "app.update_mode.resolver.resolve_vault_root",
                return_value=_fake_vault_root(),
            ),
            patch(
                "app.update_mode.resolver.resolve_file_path",
                return_value=_fake_file_path(),
            ),
            patch(
                "app.update_mode.resolver.read_original_utf8",
                return_value=self.raw_content,
            ),
        ]
        for p in patches:
            p.start()
            self._patches.append(p)
        return self

    def stop(self):
        for p in self._patches:
            p.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.stop()


# ---------------------------------------------------------------------------
# Тест 1: якорь с \n→пробел успешно резолвится через fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_newline_to_space():
    """Anchor 'задача А задача Б' должен найтись в raw 'задача А\nзадача Б'.

    Прямой поиск завершится AnchorNotFoundError (нормализованный пробел ≠ raw \\n),
    fallback через token-anchor должен вернуть PENDING.
    """
    raw = "Список задач:\nзадача А\nзадача Б\nконец"
    anchor = "задача А задача Б"
    intent = _make_intent(raw, anchor, new_content="задача А\nзадача В")
    request = _make_request()

    db = MagicMock()

    with _ResolverMocks(raw):
        result = await _resolve_one(intent, request, db, resolve_order=0)

    assert result.status == UpdateModeChangeStatus.PENDING, (
        f"Expected PENDING, got {result.status}; error={result.error_message}"
    )


# ---------------------------------------------------------------------------
# Тест 2: якорь с em-dash успешно резолвится через fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_em_dash():
    """Anchor 'Кот - животное' должен найтись в raw 'Кот — животное'.

    CHAR_MAP нормализует em-dash (\u2014) → дефис (-),
    fallback восстанавливает сырой фрагмент с em-dash и успешно применяет op.
    """
    raw = "Кот — животное, пёс — тоже животное."
    anchor = "Кот - животное"
    intent = _make_intent(raw, anchor, new_content="Кот — млекопитающее")
    request = _make_request()

    db = MagicMock()

    with _ResolverMocks(raw):
        result = await _resolve_one(intent, request, db, resolve_order=0)

    assert result.status == UpdateModeChangeStatus.PENDING, (
        f"Expected PENDING, got {result.status}; error={result.error_message}"
    )


# ---------------------------------------------------------------------------
# Тест 3: якорь не найден вообще → RESOLUTION_FAILED anchor_not_found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_anchor_not_found():
    """Если якорь отсутствует и в raw, и в normalized — возвращается RESOLUTION_FAILED."""
    raw = "Совершенно другой текст документа без нужного фрагмента."
    anchor = "несуществующий якорь XYZ"
    intent = _make_intent(raw, anchor)
    request = _make_request()

    db = MagicMock()

    with _ResolverMocks(raw):
        result = await _resolve_one(intent, request, db, resolve_order=0)

    assert result.status == UpdateModeChangeStatus.RESOLUTION_FAILED
    assert result.error_code == "anchor_not_found"


# ---------------------------------------------------------------------------
# Тест 4: fallback находит raw_fragment, но он встречается дважды → anchor_ambiguous
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_ambiguous_raw_fragment():
    """Если raw_fragment встречается в исходном тексте дважды — AnchorAmbiguousError.

    raw содержит 'задача А задача Б' дважды, нормализованный якорь совпадёт
    с первым вхождением, но apply_op() (REPLACE_UNIQUE_TEXT) должен поднять
    AnchorAmbiguousError, которую fallback вернёт как anchor_ambiguous.
    """
    raw = (
        "задача А задача Б\n"
        "что-то посередине\n"
        "задача А задача Б\n"
    )
    # Нормализованный anchor совпадает (пробелы и так стоят в raw)
    anchor = "задача А задача Б"
    intent = _make_intent(raw, anchor)
    request = _make_request()

    db = MagicMock()

    with _ResolverMocks(raw):
        result = await _resolve_one(intent, request, db, resolve_order=0)

    assert result.status == UpdateModeChangeStatus.RESOLUTION_FAILED
    assert result.error_code in ("anchor_ambiguous", "anchor_not_unique"), (
        f"Unexpected error_code={result.error_code!r}"
    )
