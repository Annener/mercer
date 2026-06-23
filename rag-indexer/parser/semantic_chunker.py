"""
SemanticChunker — разбивка документа на чанки по семантическим границам.

Алгоритм:
1. Разбить текст на предложения (regex — без nltk).
2. Вычислить эмбеддинги одним батч-запросом.
3. Найти косинусное расстояние между соседними эмбеддингами.
4. Там, где расстояние > threshold — граница чанка.
5. Жёсткие границы по Markdown-заголовкам (переиспользуем extract_markdown_headers).
6. Heading-aware guard: если в документе есть заголовки — объединять блоки
   внутри одной секции (между заголовками), чтобы «1 секция = 1 чанк».
   Для документов без заголовков используется MIN_CHUNK_SENTENCES guard.
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

# Паттерн для разбивки текста по Markdown-заголовкам (с сохранением самих заголовков).
# re.split с capture-группой возвращает заголовки как отдельные элементы списка.
_HEADING_SPLIT_RE = re.compile(r'^(#{1,6}\s+.+)$', re.MULTILINE)

# Паттерн конца предложения для мягкого сплита: точка/!/?/… вне аббревиатур.
_SENTENCE_END_RE = re.compile(r'[.!?…](?=\s|$)')


def _split_sentences(text: str) -> list[str]:
    """Разбить текст на предложения без тяжёлых NLP-зависимостей.

    Алгоритм:
    1. Сначала разбиваем по MD-заголовкам (_HEADING_SPLIT_RE) — каждый заголовок
       становится отдельным sentence независимо от того, есть ли вокруг него
       пустые строки. Это гарантирует жёсткую границу чанка перед каждой секцией.
    2. Для нешаголовочных сегментов: разбиваем по абзацам (\\n\\n+), потом
       каждый абзац — по концу предложения + пробел + заглавная буква.
    """
    if not text.strip():
        return []

    parts: list[str] = []

    # Шаг 1: разбиваем по заголовкам (capture-группа сохраняет сам заголовок).
    segments = _HEADING_SPLIT_RE.split(text)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # Если сегмент целиком является заголовком — отдельный sentence.
        if _HEADING_RE.match(seg) and '\n' not in seg:
            parts.append(seg)
            continue

        # Нешаголовочный сегмент: разбиваем по абзацам, затем по предложениям.
        for para in re.split(r'\n{2,}', seg):
            para = para.strip()
            if not para:
                continue
            # Если абзац оказался заголовком (без пустой строки вокруг него) —
            # обрабатываем отдельно, не разбиваем по предложениям внутри.
            if _HEADING_RE.match(para):
                parts.append(para)
                continue
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


def _soft_split(text: str, max_chars: int, soft_threshold: int, search_window: int) -> list[str]:
    """Дробить строку на куски ≤ max_chars с мягким поиском границы предложения.

    Логика для каждого куска:
    1. Если len(text) ≤ max_chars — возвращаем как есть.
    2. Если len > soft_threshold — ищем конец предложения ([.!?…]) в окне
       [soft_threshold - search_window .. soft_threshold + search_window].
       Разрезаем сразу после найденного знака препинания.
    3. Fallback: ищем последний пробел в пределах max_chars.
    4. Жёсткий fallback: режем ровно по max_chars.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    while len(text) > max_chars:
        split_at: int = -1

        # Фаза 1: мягкий поиск конца предложения вокруг soft_threshold
        window_start = max(0, soft_threshold - search_window)
        window_end = min(max_chars, soft_threshold + search_window)
        # Ищем последнее вхождение знака конца предложения в окне
        for match in _SENTENCE_END_RE.finditer(text, window_start, window_end):
            split_at = match.end()  # включаем знак препинания в текущий чанк

        # Фаза 2: fallback на последний пробел в пределах max_chars
        if split_at == -1:
            split_at = text.rfind(' ', 0, max_chars)

        # Фаза 3: жёсткий fallback
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
    # При достижении SOFT_THRESHOLD начинаем искать конец предложения
    SOFT_THRESHOLD: int = 2500
    # Окно поиска конца предложения (±символов от SOFT_THRESHOLD)
    SENTENCE_SEARCH_WINDOW: int = 400

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
            chunks = _soft_split(
                sentences[0],
                self.MAX_CHUNK_CHARS,
                self.SOFT_THRESHOLD,
                self.SENTENCE_SEARCH_WINDOW,
            )
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

        # 7. Guard: объединение блоков внутри одной секции.
        # Если документ содержит MD-заголовки — используем heading-aware guard:
        # все семантические под-блоки между двумя заголовками склеиваются обратно
        # в один чанк, так что «1 секция (заголовок) = 1 чанк» до MAX_CHUNK_CHARS.
        # Для документов без заголовков — стандартный MIN_CHUNK_SENTENCES guard.
        if heading_indices:
            merged_blocks = _apply_heading_guard(raw_blocks)
        else:
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
            final_chunks.extend(
                _soft_split(
                    chunk,
                    self.MAX_CHUNK_CHARS,
                    self.SOFT_THRESHOLD,
                    self.SENTENCE_SEARCH_WINDOW,
                )
            )

        result = [c for c in final_chunks if c.strip()]
        logger.debug(
            "SemanticChunker: sentences=%d → chunks=%d (threshold=%.2f, heading_mode=%s)",
            len(sentences),
            len(result),
            self._threshold,
            bool(heading_indices),
        )
        return result


def _apply_heading_guard(blocks: list[list[str]]) -> list[list[str]]:
    """Объединить семантические под-блоки внутри одной MD-секции.

    Принцип: если блок НЕ начинается с заголовка — он является продолжением
    предыдущей секции и присоединяется к ней. Новый чанк открывается только
    тогда, когда блок начинается с MD-заголовка (#{1,6}).

    Таким образом гарантируется «1 заголовок-секция = 1 чанк», а все
    семантические под-разрывы внутри секции (от threshold) игнорируются.
    MAX_CHUNK_CHARS guard на следующем шаге всё равно применится, если
    секция окажется слишком длинной.
    """
    if not blocks:
        return blocks

    result: list[list[str]] = []
    for block in blocks:
        # Блок открывает новую секцию, если его первый sentence — заголовок
        if block and _HEADING_RE.match(block[0].strip()):
            result.append(list(block))
        else:
            # Продолжение предыдущей секции — присоединяем
            if result:
                result[-1].extend(block)
            else:
                # Контент до первого заголовка (преамбула документа)
                result.append(list(block))

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
