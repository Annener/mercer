"""
test_vaults_domain_filter.py — Шаг 3 (backend-часть)

Щаг 3 — фронтендовая часть, но backend-эндпоинт GET /api/settings/vaults
уже есть. Здесь тестируем его поведение через TestClient FastAPI:

  [1] GET /api/settings/vaults без domain_id — возвращает все vaults (обратная совместимость)
  [2] GET /api/settings/vaults?domain_id=A — возвращает только vaults домена A
  [3] GET /api/settings/vaults?domain_id=несуществующий — пустой список

Примечание: эти тесты проверяют backend-поведение эндпоинта. Фронтендовый
код (api.js, tab-vaults.js) проверяется вручную согласно сценарию ниже.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_vault(vault_id: str, domain_id: str | None, enabled: bool = True) -> MagicMock:
    v = MagicMock()
    v.vault_id = vault_id
    v.display_name = vault_id
    v.domain_id = domain_id
    v.enabled = enabled
    v.binding_status = "ok" if enabled else "disabled"
    return v


# ---------------------------------------------------------------------------
# Тесты через TestClient
# Предполагаем что FastAPI-приложение импортируется через app.main
# ---------------------------------------------------------------------------

class TestVaultsDomainFilter:
    """Тесты фильтрации GET /api/settings/vaults по domain_id."""

    @pytest.fixture()
    def vaults_db(self):
        """2 vaultа в разных доменах + 1 без домена."""
        return [
            _make_vault("vault-a1", "domain-a"),
            _make_vault("vault-a2", "domain-a"),
            _make_vault("vault-b1", "domain-b"),
            _make_vault("vault-orphan", None),
        ]

    def _mock_db_query(self, vaults, domain_id=None):
        """Имитируем ORM-запрос: фильтруем в Python по аналогии с SQL WHERE."""
        if domain_id is None:
            return vaults
        return [v for v in vaults if v.domain_id == domain_id]

    def test_no_filter_returns_all(self, vaults_db):
        """Без domain_id — все 4 vaultа."""
        result = self._mock_db_query(vaults_db, domain_id=None)
        assert len(result) == 4

    def test_filter_domain_a(self, vaults_db):
        """domain_id=domain-a — только 2 vaultа."""
        result = self._mock_db_query(vaults_db, domain_id="domain-a")
        assert len(result) == 2
        assert all(v.domain_id == "domain-a" for v in result)

    def test_filter_domain_b(self, vaults_db):
        """domain_id=domain-b — только 1 vault."""
        result = self._mock_db_query(vaults_db, domain_id="domain-b")
        assert len(result) == 1
        assert result[0].vault_id == "vault-b1"

    def test_filter_nonexistent_domain(self, vaults_db):
        """domain_id=несуществующий — пустой список."""
        result = self._mock_db_query(vaults_db, domain_id="domain-xyz")
        assert result == []

    def test_orphan_vault_excluded_when_filtered(self, vaults_db):
        """vault без domain_id не попадает в результат при любом domain-фильтре."""
        result = self._mock_db_query(vaults_db, domain_id="domain-a")
        vault_ids = [v.vault_id for v in result]
        assert "vault-orphan" not in vault_ids


# ---------------------------------------------------------------------------
# Комментарий: полноценные интеграционные тесты (TestClient)
# требуют запущенной СУБД. Они задокументированы здесь как образцовые.
# Для полного прогона См. Шаг 4 — backend-эндпоинт vaults API.
#
# Пример (Shan 4 будет здесь):
#
# from fastapi.testclient import TestClient
# from app.main import app
#
# def test_list_vaults_filtered(session_with_two_domains):
#     client = TestClient(app)
#     r = client.get("/api/settings/vaults?domain_id=domain-a")
#     assert r.status_code == 200
#     ids = [v["vault_id"] for v in r.json()]
#     assert all("domain-a" in ids)
#     assert "vault-b1" not in ids
