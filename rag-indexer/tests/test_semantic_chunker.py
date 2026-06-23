"""
Тесты для SemanticChunker.

Все тесты используют мок EmbeddingProvider.embed_batch — без реальных HTTP-запросов.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parser.semantic_chunker import SemanticChunker, _apply_min_guard, _cosine_distance, _split_sentences


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(vectors: list[list[float]]) -> MagicMock:
    """Создаёт мок EmbeddingProvider, чей embed_batch возвращает заданные векторы."""
    provider = MagicMock()
    provider.embed_batch = AsyncMock(return_value=vectors)
    return provider


def _vec(n: float) -> list[float]:
    """Вектор [n, 0] — удобно для управления косинусным расстоянием."""
    return [n, 0.0]


# ---------------------------------------------------------------------------
# Unit-тесты вспомогательных функций
# ---------------------------------------------------------------------------

class TestCosineDistance:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert _cosine_distance(v, v) == pytest.approx(0.0, abs=1e-9)

    def test_orthogonal_vectors(self):
        assert _cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0, abs=1e-9)

    def test_opposite_vectors(self):
        assert _cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0, abs=1e-9)

    def test_zero_vector_returns_one(self):
        """Нулевой вектор — считаем максимально далёким."""
        assert _cosine_distance([0.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


class TestSplitSentences:
    def test_empty_string(self):
        assert _split_sentences("") == []

    def test_whitespace_only(self):
        assert _split_sentences("   ") == []

    def test_single_sentence(self):
        result = _split_sentences("Привет мир.")
        assert result == ["Привет мир."]

    def test_paragraph_split(self):
        text = "Первый абзац.\n\nВторой абзац."
        result = _split_sentences(text)
        assert len(result) == 2

    def test_heading_is_separate(self):
        text = "## Заголовок\n\nТекст параграфа."
        result = _split_sentences(text)
        assert result[0] == "## Заголовок"
        assert "Текст параграфа." in result


class TestApplyMinGuard:
    def test_no_short_blocks(self):
        blocks = [["A", "B"], ["C", "D"]]
        assert _apply_min_guard(blocks, 2) == [["A", "B"], ["C", "D"]]

    def test_short_block_merges_to_previous(self):
        blocks = [["A", "B"], ["C"]]
        result = _apply_min_guard(blocks, 2)
        assert result == [["A", "B", "C"]]

    def test_first_block_short_stays(self):
        """Первый блок без предыдущего — остаётся как есть."""
        blocks = [["A"], ["B", "C"]]
        result = _apply_min_guard(blocks, 2)
        # ["A"] < min → добавляется в result как есть (нет previous)
        assert len(result) == 2

    def test_empty_input(self):
        assert _apply_min_guard([], 2) == []


# ---------------------------------------------------------------------------
# Интеграционные тесты SemanticChunker.split()
# ---------------------------------------------------------------------------

class TestSemanticChunkerSplit:

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty_list(self):
        provider = _make_provider([])
        chunker = SemanticChunker(provider)
        result = await chunker.split("")
        assert result == []

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty_list(self):
        provider = _make_provider([])
        chunker = SemanticChunker(provider)
        result = await chunker.split("   \n  ")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_sentence_returns_one_chunk(self):
        """Один абзац без разрывов → один чанк. embed_batch не вызывается."""
        provider = _make_provider([])
        chunker = SemanticChunker(provider)
        text = "Это единственное предложение в документе."
        result = await chunker.split(text)
        assert len(result) == 1
        assert result[0] == text
        provider.embed_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_two_semantically_far_blocks_split_into_two_chunks(self):
        """
        Два семантически далёких блока (расстояние > threshold) → два чанка.

        Конфигурация:
        - sentences: [s1, s2, s3, s4] где s1+s2 — первая тема, s3+s4 — другая
        - vectors: s1≈s2 (маленькое расстояние), s2 далеко от s3 (> threshold)
        """
        # Вектора:
        # s1 = [1, 0], s2 = [0.99, 0.14] (похожи → dist≈0.01)
        # s3 = [0, 1],  s4 = [-0.14, 0.99] (похожи) → dist(s2,s3)≈1.0 > 0.3
        vectors = [
            [1.0, 0.0],
            [0.99, 0.14],
            [0.0, 1.0],
            [-0.14, 0.99],
        ]
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.3)

        # 4 абзаца чтобы получить 4 «предложения»
        text = (
            "Кот спал на диване.\n\n"
            "Кот любил рыбу.\n\n"
            "Фондовый рынок упал на три процента.\n\n"
            "Инвесторы были обеспокоены."
        )
        result = await chunker.split(text)
        assert len(result) == 2, f"Ожидали 2 чанка, получили {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_one_coherent_text_returns_one_chunk(self):
        """Единый связный текст (все расстояния < threshold) → один чанк."""
        # Все векторы почти одинаковые → расстояние ≈ 0
        vectors = [[1.0, 0.01 * i] for i in range(4)]
        # Нормализуем чтобы косинус был реалистичен
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.3)

        text = (
            "Python — интерпретируемый язык программирования.\n\n"
            "Он используется в науке о данных.\n\n"
            "Также Python популярен в веб-разработке.\n\n"
            "FastAPI — один из самых быстрых фреймворков на Python."
        )
        result = await chunker.split(text)
        assert len(result) == 1, f"Ожидали 1 чанк, получили {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_markdown_heading_always_creates_boundary(self):
        """
        Markdown-заголовок всегда создаёт жёсткую границу чанка,
        независимо от косинусного расстояния.
        """
        # Все векторы похожи → без заголовка был бы один чанк
        vectors = [[1.0, 0.01 * i] for i in range(4)]
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.5)  # высокий порог

        text = (
            "Введение в тему.\n\n"
            "Немного подробностей.\n\n"
            "## Новый раздел\n\n"
            "Начало нового раздела."
        )
        result = await chunker.split(text)
        # Заголовок ## делит текст на 2+ части
        assert len(result) >= 2, f"Ожидали ≥2 чанка из-за заголовка, получили {len(result)}: {result}"
        # Заголовок должен быть началом одного из чанков
        heading_in_chunk = any("## Новый раздел" in c for c in result)
        assert heading_in_chunk, f"Заголовок не найден в чанках: {result}"

    @pytest.mark.asyncio
    async def test_min_guard_merges_short_chunk(self):
        """
        Очень короткий чанк (1 предложение) объединяется с соседним.

        Конфигурация: 3 предложения, разрыв после каждого → 3 блока по 1 предложению.
        MIN_CHUNK_SENTENCES=2 → два блока объединяются.
        """
        # Большое расстояние после каждого предложения — все разрывы сработают
        vectors = [
            [1.0, 0.0],
            [0.0, 1.0],
            [-1.0, 0.0],
        ]
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.3)

        text = (
            "Первое предложение.\n\n"
            "Второе предложение.\n\n"
            "Третье предложение."
        )
        result = await chunker.split(text)
        # 3 блока по 1 предложению → MIN guard → не более 2 чанков
        assert len(result) <= 2, f"MIN guard не сработал, получили {len(result)}: {result}"

    @pytest.mark.asyncio
    async def test_max_guard_splits_very_long_chunk(self):
        """Очень длинный блок (>MAX_CHUNK_CHARS) принудительно дробится."""
        # Все предложения похожи → один блок
        long_sentence = "А " * 500  # ~1000 символов на предложение
        # 5 похожих абзацев × ~1000 символов = ~5000 символов > MAX_CHUNK_CHARS=4000
        paragraphs = [long_sentence.strip() for _ in range(5)]
        text = "\n\n".join(paragraphs)

        # Все векторы идентичны → нет семантических разрывов → один блок
        num_sentences = len(text.split("\n\n"))  # приблизительно
        vectors = [[1.0, 0.0]] * num_sentences
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.3)

        result = await chunker.split(text)
        # Должен разбиться, т.к. суммарный текст > 4000 символов
        assert len(result) > 1, "MAX guard не сработал для большого чанка"
        for chunk in result:
            assert len(chunk) <= SemanticChunker.MAX_CHUNK_CHARS, (
                f"Чанк превышает MAX_CHUNK_CHARS: {len(chunk)} символов"
            )

    @pytest.mark.asyncio
    async def test_embed_batch_called_exactly_once(self):
        """embed_batch должен вызываться ровно один раз на весь документ."""
        vectors = [[1.0, 0.01 * i] for i in range(4)]
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.3)

        text = (
            "Первое предложение.\n\n"
            "Второе предложение.\n\n"
            "Третье предложение.\n\n"
            "Четвёртое предложение."
        )
        await chunker.split(text)
        provider.embed_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_batch_called_with_all_sentences(self):
        """embed_batch получает список всех предложений документа."""
        vectors = [[1.0, 0.01 * i] for i in range(3)]
        provider = _make_provider(vectors)
        chunker = SemanticChunker(provider, threshold=0.3)

        text = "Абзац один.\n\nАбзац два.\n\nАбзац три."
        await chunker.split(text)

        call_args = provider.embed_batch.call_args
        sentences_passed = call_args[0][0]  # первый позиционный аргумент
        assert len(sentences_passed) == 3
