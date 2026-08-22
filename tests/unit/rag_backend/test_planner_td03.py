"""
test_planner_td03.py — TD-03

Проверяем, что класс Planner (который остаётся) работает корректно
после удаления мёртвого класса LLMRAGPlanner из planner.py.

Тесты:
  TestPlannerMissingFields
    [1] короткий запрос (< 3 слов) → поле "topic" в missing_fields
    [2] длинный запрос без триггеров → пустой список
    [3] запрос с триггером "класс" → поле "subject"
    [4] несколько триггеров → каждый добавляется один раз (no duplicates)

  TestPlannerDecide
    [5] retrieval.enabled=False → strategy="none", clarification_needed=False
    [6] retrieval.enabled=True, vault_id указан, vault есть в БД → strategy="semantic"
    [7] retrieval.enabled=True, vault_id=None, domain без vaults → strategy="none"
    [8] LLMRAGPlanner не импортируется из planner (класс удалён)
"""
from __future__ import annotations

import importlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.planner import Planner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(
    *,
    vault_enabled: bool = True,
    vault_chunk_count: int = 10,
    domain_vault_count: int = 1,
    clarification_fields: list[dict] | None = None,
) -> AsyncMock:
    """Возвращает AsyncSession-мок с настроенными execute-ответами."""
    db = AsyncMock()

    vault = MagicMock()
    vault.enabled = vault_enabled
    vault.chunk_count = vault_chunk_count

    # scalar_one_or_none → для _strategy_for_vault
    scalar_vault_result = MagicMock()
    scalar_vault_result.scalar_one_or_none = MagicMock(return_value=vault if vault_enabled else None)

    # scalar → для _strategy_for_domain (count)
    scalar_count_result = MagicMock()
    scalar_count_result.scalar = MagicMock(return_value=domain_vault_count)

    # scalars().all() → для _missing_fields_for_domain (clarification fields)
    fields = clarification_fields if clarification_fields is not None else []
    domain_service_mock_result = MagicMock()
    domain_service_mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=fields)))

    db.execute = AsyncMock(side_effect=[scalar_vault_result, scalar_count_result])
    return db


def _make_settings_svc(retrieval_enabled: bool = True, max_clarification_turns: int = 3) -> MagicMock:
    svc = MagicMock()

    async def _get(key: str, db):  # noqa: ARG001
        if key == "retrieval.enabled":
            return retrieval_enabled
        if key == "chat.max_clarification_turns":
            return max_clarification_turns
        return None

    svc.get = _get
    return svc


# ---------------------------------------------------------------------------
# TestPlannerMissingFields — статический метод, без БД
# ---------------------------------------------------------------------------

class TestPlannerMissingFields:
    """Unit-тесты Planner._missing_fields — без БД и моков."""

    def test_short_query_returns_topic(self):
        """Запрос короче 3 слов → ['topic']."""
        result = Planner._missing_fields("расскажи")
        assert result == ["topic"]

    def test_long_query_no_triggers_returns_empty(self):
        """Длинный запрос без триггеров → пустой список."""
        result = Planner._missing_fields("расскажи мне про историю магии в этом мире")
        assert result == []

    def test_trigger_klass_adds_subject(self):
        """Триггер 'класс' → поле 'subject' в missing."""
        result = Planner._missing_fields("какой класс лучше выбрать для мага")
        assert "subject" in result

    def test_multiple_triggers_no_duplicates(self):
        """Несколько триггеров одного поля → поле добавляется один раз."""
        result = Planner._missing_fields("класс или раса — что важнее для мага")
        assert result.count("subject") == 1


# ---------------------------------------------------------------------------
# TestPlannerDecide — async, с моками БД и settings_service
# ---------------------------------------------------------------------------

class TestPlannerDecide:
    """Интеграционные тесты Planner.decide() с замоканными зависимостями."""

    @pytest.mark.asyncio
    async def test_retrieval_disabled_gives_none_strategy(self):
        """retrieval.enabled=False → strategy='none', clarification_needed=False."""
        planner = Planner()
        db = AsyncMock()

        with (
            patch("app.services.planner.settings_service", _make_settings_svc(retrieval_enabled=False)),
            patch("app.services.planner.domain_service") as mock_domain_svc,
        ):
            mock_domain_svc.get_clarification_fields = AsyncMock(return_value=[])
            decision, missing = await planner.decide(
                db=db, query="длинный запрос без ответа", vault_id=None, domain_id="default"
            )

        assert decision.retrieval_strategy == "none"
        assert decision.clarification_needed is False
        assert missing == []

    @pytest.mark.asyncio
    async def test_vault_with_chunks_gives_semantic_strategy(self):
        """vault_id указан, vault.chunk_count > 0 → strategy='semantic'."""
        planner = Planner()

        vault = MagicMock()
        vault.enabled = True
        vault.chunk_count = 5

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=vault)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.services.planner.settings_service", _make_settings_svc(retrieval_enabled=True)),
            patch("app.services.planner.domain_service") as mock_domain_svc,
        ):
            mock_domain_svc.get_clarification_fields = AsyncMock(return_value=[])
            decision, _ = await planner.decide(
                db=db, query="расскажи про магию в этом мире", vault_id="vault-123", domain_id="default"
            )

        assert decision.retrieval_strategy == "semantic"

    @pytest.mark.asyncio
    async def test_domain_without_vaults_gives_none_strategy(self):
        """domain_id задан, но vaults нет → strategy='none'."""
        planner = Planner()

        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=0)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("app.services.planner.settings_service", _make_settings_svc(retrieval_enabled=True)),
            patch("app.services.planner.domain_service") as mock_domain_svc,
        ):
            mock_domain_svc.get_clarification_fields = AsyncMock(return_value=[])
            decision, _ = await planner.decide(
                db=db, query="расскажи про магию в этом мире", vault_id=None, domain_id="default"
            )

        assert decision.retrieval_strategy == "none"

    def test_llmrag_planner_not_importable_from_planner(self):
        """LLMRAGPlanner не должен быть доступен после удаления из planner.py."""
        import app.services.planner as planner_module
        assert not hasattr(planner_module, "LLMRAGPlanner"), (
            "LLMRAGPlanner всё ещё присутствует в planner.py — TD-03 не закрыт"
        )
