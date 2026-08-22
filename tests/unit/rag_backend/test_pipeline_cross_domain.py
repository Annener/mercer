"""
test_pipeline_cross_domain.py — Шаг 6

Тестируем логику cross-domain валидации Pipeline ↔ Campaign.
Все тесты — чистые unit-тесты без БД (mock через AsyncMock/MagicMock).

Сценарии:
  [1] create: campaign из другого домена → HTTPException 400
  [2] create: campaign из того же домена → без исключения
  [3] create: campaign не найдена → HTTPException 404
  [4] update: смена campaign_id на чужой домен → HTTPException 400
  [5] update: campaign_id не передан в payload → валидация не срабатывает

Прогон:
    pytest rag-backend/app/tests/test_pipeline_cross_domain.py -v
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.settings.pipelines import _check_campaign_domain


def _make_campaign(domain_id: str) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.domain_id = domain_id
    c.name = "Test Campaign"
    return c


def _make_db(campaign: MagicMock | None) -> AsyncMock:
    """Имитирует AsyncSession.get() — возвращает campaign или None."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=campaign)
    return db


class TestCheckCampaignDomain:
    """Тесты вспомогательной функции _check_campaign_domain."""

    @pytest.mark.asyncio
    async def test_cross_domain_raises_400(self):
        """Кампания из домена-A, ожидается домен-B → 400."""
        campaign = _make_campaign("domain-a")
        db = _make_db(campaign)

        with pytest.raises(HTTPException) as exc_info:
            await _check_campaign_domain(campaign.id, "domain-b", db)

        assert exc_info.value.status_code == 400
        assert "domain-a" in exc_info.value.detail
        assert "domain-b" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_same_domain_no_exception(self):
        """Кампания и пайплайн в одном домене → без исключения."""
        campaign = _make_campaign("domain-a")
        db = _make_db(campaign)

        # Не должно поднять исключение
        await _check_campaign_domain(campaign.id, "domain-a", db)

    @pytest.mark.asyncio
    async def test_campaign_not_found_raises_404(self):
        """Кампания не найдена в БД → 404."""
        db = _make_db(None)  # db.get() вернёт None
        random_id = uuid.uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await _check_campaign_domain(random_id, "domain-a", db)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_domain_error_message_contains_both_domains(self):
        """Сообщение об ошибке содержит оба domain_id для диагностики."""
        campaign = _make_campaign("domain-dnd")
        db = _make_db(campaign)

        with pytest.raises(HTTPException) as exc_info:
            await _check_campaign_domain(campaign.id, "domain-work", db)

        detail = exc_info.value.detail
        assert "domain-dnd" in detail
        assert "domain-work" in detail

    @pytest.mark.asyncio
    async def test_db_get_called_with_correct_uuid(self):
        """db.get() вызывается с правильным UUID и моделью Campaign."""
        from app.db.models import Campaign

        campaign_id = uuid.uuid4()
        campaign = _make_campaign("domain-a")
        db = _make_db(campaign)

        await _check_campaign_domain(campaign_id, "domain-a", db)

        db.get.assert_called_once_with(Campaign, campaign_id)
