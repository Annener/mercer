"""
test_chat_vault_domain.py — Шаг 7

Тестируем логику cross-domain валидации Chat.vault_id.
Все тесты — чистые unit-тесты без БД (mock через AsyncMock/MagicMock).

Сценарии:
  [1] vault из другого домена → HTTPException 400
  [2] vault из того же домена → без исключения
  [3] vault не найден → HTTPException 404
  [4] vault_id=None → валидация не срабатывает (пропуск)
  [5] сообщение об ошибке содержит оба domain_id и vault_id

Прогон:
    pytest rag-backend/app/tests/test_chat_vault_domain.py -v
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.chat import _check_vault_domain


def _make_vault(domain_id: str | None, vault_id: str = "vault-1") -> MagicMock:
    v = MagicMock()
    v.vault_id = vault_id
    v.domain_id = domain_id
    v.display_name = "Test Vault"
    return v


def _make_db(vault: MagicMock | None) -> AsyncMock:
    """Имитирует AsyncSession: execute() → scalars().first() → vault или None."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = vault
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    return db


class TestCheckVaultDomain:
    """Тесты вспомогательной функции _check_vault_domain."""

    @pytest.mark.asyncio
    async def test_cross_domain_raises_400(self):
        """Vault из домена-A, чат в домене-B → 400."""
        vault = _make_vault("domain-a", "vault-123")
        db = _make_db(vault)

        with pytest.raises(HTTPException) as exc_info:
            await _check_vault_domain("vault-123", "domain-b", db)

        assert exc_info.value.status_code == 400
        assert "domain-a" in exc_info.value.detail
        assert "domain-b" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_same_domain_no_exception(self):
        """Vault и чат в одном домене → без исключения."""
        vault = _make_vault("domain-a", "vault-123")
        db = _make_db(vault)

        # Не должно поднять исключение
        await _check_vault_domain("vault-123", "domain-a", db)

    @pytest.mark.asyncio
    async def test_vault_not_found_raises_404(self):
        """Vault не найден в БД → 404."""
        db = _make_db(None)

        with pytest.raises(HTTPException) as exc_info:
            await _check_vault_domain("vault-nonexistent", "domain-a", db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_vault_id_none_skips_check(self):
        """vault_id=None → функция завершается без обращения к БД."""
        db = _make_db(None)

        # Не должно поднять исключение и не должно обращаться к БД
        await _check_vault_domain(None, "domain-a", db)

        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_message_contains_vault_and_domains(self):
        """Сообщение об ошибке содержит vault_id и оба domain_id для диагностики."""
        vault = _make_vault("domain-dnd", "vault-dnd-lore")
        db = _make_db(vault)

        with pytest.raises(HTTPException) as exc_info:
            await _check_vault_domain("vault-dnd-lore", "domain-work", db)

        detail = exc_info.value.detail
        assert "domain-dnd" in detail
        assert "domain-work" in detail

    @pytest.mark.asyncio
    async def test_vault_domain_id_none_raises_400(self):
        """Vault с domain_id=None считается бесхозным — 400 при попытке привязки к конкретному домену."""
        vault = _make_vault(None, "vault-orphan")
        db = _make_db(vault)

        with pytest.raises(HTTPException) as exc_info:
            await _check_vault_domain("vault-orphan", "domain-a", db)

        assert exc_info.value.status_code == 400
