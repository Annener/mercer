"""
SemanticChunker — разбивка документа на чанки по семантическим границам.

Алгоритм:
1. Разбить текст на предложения (regex — без nltk).
2. Вычислить эмбеддинги одним батч-запросом.
3. Найти косинусное расстояние между соседними эмбеддингами.
4. Там, где расстояние > threshold — граница чанка.
5. Жёсткие границы по Markdown-заголовкам (переиспользуем extract_markdown_headers).
6. MIN_CHUNK_SENTENCES guard: объединить слишком короткий чанк с соседним.
7. MAX_CHUNK_CHARS guard: принудительно дробить слишком большой чанк.

Принимает ПРЕДВАРИТЕЛЬНО ОЧИЩЕННЫЙ текст (после preprocess()).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from embedding.base_provider import EmbeddingProvider

from parser.chunking.embedding_enricher import extract_markdown_headers

logger = logging.getLogger(__name__)

# Regex-паттерн для разбивки на предложения.
# Разбиваем по: точка/!/?/… + пробел + заглавная буква (или конец строки).
# Двойной перевод строки (абзацный разрыв) — всегда граница предложения.
_SENTENCE_SPLIT_RE = re.compile(
    r'(?:(?<=[.!?…])\s+(?=[A-ZА-ЯЁ"«\(])|\n{2,})'
)

# Паттерн для определения строки как Markdown-заголовка.
_HEADING_RE = re.compile(r'^#{1,6}\s+')


def _split_sentences(text: str) -> list[str]:
    """Разбить текст на предложения без тяжёлых NLP-зависимостей."""
    if not text.strip():
        return []
    # Сначала разбиваем по абзацам (\n\n+)
    parts: list[str] = []
    for para in re.split(r'\n{2,}', text):
        para = para.strip()
        if not para:
            continue
        # Если это заголовок — отдельный «sentence»
        if _HEADING_RE.match(para):
            parts.append(para)
            continue
        # Иначе разбиваем абзац по концу предложения + пробел + заглавная
        sents = _SENTENCE_SPLIT_RE.split(para)
        for s in sents:
            s = s.strip()
            if s:
                parts.append(s)
    return parts


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Косинусное расстояние [0, 2]; чем больше — тем дальше по смыслу."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0  # считаем максимально далёкими
    return 1.0 - dot / (norm_a * norm_b)


def _fixed_split(text: str, max_chars: int) -> list[str]:
    """Дробить строку на куски ≤ max_chars по пробелам (fallback для MAX guard)."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while len(text) > max_chars:
        split_at = text.rfind(' ', 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


class SemanticChunker:
    """Семантический чанкер на основе косинусного расстояния между эмбеддингами."""

    MIN_CHUNK_SENTENCES: int = 2
    MAX_CHUNK_CHARS: int = 4000

    def __init__(self, embedding_provider: "EmbeddingProvider", threshold: float = 0.3) -> None:
        self._provider = embedding_provider
        self._threshold = threshold

    async def split(self, text: str) -> list[str]:
        """
        Разбить предварительно очищенный текст на семантические чанки.

        Args:
            text: Очищенный текст документа (после preprocess()).

        Returns:
            Список текстов чанков. Пустой список для пустого входа.
        """
        if not text or not text.strip():
            return []

        # 1. Разбивка на предложения
        sentences = await asyncio.to_thread(_split_sentences, text)
        if not sentences:
            return []

        # Если одно предложение — возвращаем как один чанк
        if len(sentences) == 1:
            chunks = _fixed_split(sentences[0], self.MAX_CHUNK_CHARS)
            return [c for c in chunks if c.strip()]

        # 2. Батч-эмбеддинг всех предложений (один запрос)
        embeddings = await self._provider.embed_batch(sentences)

        # 3. Определение жёстких границ по заголовкам
        # Индексы предложений, которые являются заголовками → всегда граница
        heading_indices: set[int] = set()
        for i, sent in enumerate(sentences):
            if _HEADING_RE.match(sent.strip()):
                heading_indices.add(i)

        # 4. Вычислить косинусное расстояние между соседними эмбеддингами
        distances: list[float] = []
        for i in range(len(sentences) - 1):
            emb_a = embeddings[i]
            emb_b = embeddings[i + 1]
            if emb_a and emb_b:  # защита от пустых векторов (ошибка провайдера)
                distances.append(_cosine_distance(emb_a, emb_b))
            else:
                distances.append(0.0)  # считаем смежными

        # 5. Нарезать на семантические блоки
        # break_after[i] == True → разрыв ПОСЛЕ предложения i
        break_after: list[bool] = [False] * len(sentences)
        for i, dist in enumerate(distances):
            if dist > self._threshold:
                break_after[i] = True
        # Жёсткие границы по заголовкам: разрыв ПЕРЕД заголовком
        for idx in heading_indices:
            if idx > 0:
                break_after[idx - 1] = True

        # 6. Сборка первичных блоков
        raw_blocks: list[list[str]] = []
        current: list[str] = []
        for i, sent in enumerate(sentences):
            current.append(sent)
            if break_after[i]:
                raw_blocks.append(current)
                current = []
        if current:
            raw_blocks.append(current)

        # 7. MIN_CHUNK_SENTENCES guard: объединить слишком короткий блок с соседним
        merged_blocks = _apply_min_guard(raw_blocks, self.MIN_CHUNK_SENTENCES)

        # 8. Собрать текст каждого блока
        raw_chunks: list[str] = []
        for block in merged_blocks:
            chunk_text = ' '.join(block).strip()
            if chunk_text:
                raw_chunks.append(chunk_text)

        # 9. MAX_CHUNK_CHARS guard: принудительно дробить слишком большой чанк
        final_chunks: list[str] = []
        for chunk in raw_chunks:
            final_chunks.extend(_fixed_split(chunk, self.MAX_CHUNK_CHARS))

        result = [c for c in final_chunks if c.strip()]
        logger.debug(
            "SemanticChunker: sentences=%d → chunks=%d (threshold=%.2f)",
            len(sentences),
            len(result),
            self._threshold,
        )
        return result


def _apply_min_guard(
    blocks: list[list[str]], min_sentences: int
) -> list[list[str]]:
    """
    Объединить блоки, у которых меньше min_sentences предложений, с соседним блоком.
    Обход слева направо: короткий блок присоединяется к предыдущему (если есть),
    иначе — к следующему.
    """
    if not blocks:
        return blocks

    result: list[list[str]] = []
    for block in blocks:
        if len(block) < min_sentences and result:
            # Присоединяем к предыдущему блоку
            result[-1].extend(block)
        else:
            result.append(list(block))

    # Последний блок тоже может оказаться коротким (если он был первым и не было previous)
    # В этом случае он уже добавлен в result как есть — это приемлемо (граничный случай).
    return result
