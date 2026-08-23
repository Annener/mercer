from __future__ import annotations

import logging
import re

from shared_contracts.models import ChatMessage

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """\
Проблема с domain_description
Проблема понятна — LLM буквально копирует слова из {domain_description} в запрос, потому что промт говорит «учитывай контекст базы знаний», но не говорит «не используй его слова».

Правка одна — переформулировать инструкцию про domain_description:

text
Ты — препроцессор запросов для семантического поиска в векторной базе знаний.
Твой вывод используется как поисковый запрос, НЕ как ответ пользователю.

Тематика базы знаний (для понимания контекста, НЕ для копирования в запрос):
{domain_description}

История диалога:
{history}

Запрос пользователя: "{query}"

Задача: сформируй одну поисковую фразу из ключевых сущностей запроса.

Правила:
- Выдели конкретные сущности: имена, места, события, предметы, даты
- Убери глаголы-команды ("напиши", "расскажи"), вежливости
- НЕ включай название системы или тематики из контекста базы знаний — 
  оно не встречается в документах и засоряет запрос
- Замени "последняя/первая/предыдущая сессия" на конкретный номер из истории,
  если известен; иначе используй "сессия лог кампании"
- Сохрани язык запроса
- 3-8 слов максимум

Верни ТОЛЬКО поисковую фразу — без объяснений, без точки в конце.
"""

RETRIEVAL_REWRITE_PROMPT = """\
Ты — препроцессор запросов для семантического поиска в векторной базе знаний.
Твой вывод используется как поисковый запрос, НЕ как ответ пользователю.

Задание для поиска:
{step_prompt}

Задача: извлечь из задания ключевые сущности и сформировать короткую поисковую фразу.

Правила:
- Фраза должна быть короткой: 3-10 слов
- Выдели конкретные сущности: имена, места, предметы, события, термины
- Убери глаголы-команды ("выгрузи", "найди", "определи", "получи информацию о")
- Убери вежливости и служебные слова
- Сохрани язык задания

Верни ТОЛЬКО поисковую фразу — без объяснений, без знаков препинания в конце.
"""


# ---------------------------------------------------------------------------
# Cross-language: detect + translate non-RU queries to Russian
# ---------------------------------------------------------------------------


_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")


def _cyrillic_ratio(text: str) -> float:
    """Return the share of cyrillic letters in `text` (0..1).

    Cheap heuristic that doesn't need any NLP model — sufficient to tell
    "mostly English" from "mostly Russian" / "mixed". A query like
    "Beholder stats" has ratio 0, "Бехолдер характеристики" has ratio ≈1.
    """
    if not text:
        return 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for c in letters if _CYRILLIC_RE.match(c))
    return cyr / len(letters)


def is_cyrillic_query(text: str, threshold: float = 0.4) -> bool:
    """True if `text` looks like a Russian-language query.

    Threshold of 0.4 means "at least 40% of letters are cyrillic". This
    tolerates queries that mix D&D transliterations ("Бехолдер Beholder")
    with native Russian words.
    """
    return _cyrillic_ratio(text) >= threshold


# Короткий промпт для перевода — отдельная LLM-операция, дешёвая (≤80 токенов на выходе).
# Тривиальный fallback: если перевод не удался, используем только оригинал.
RU_TRANSLATE_PROMPT = """\
Ты — переводчик с любого языка на русский для поисковых запросов.

Исходный запрос: "{query}"

Задача: переведи запрос на русский язык, сохранив:
- имена собственные (Beholder → Бехолдер, Dragons → Драконы, и т.п.);
- технические термины, которые в русскоязычной базе знаний уже переведены
  (например, "armor class" → "класс брони", "fireball" → "огненный шар");
- смысл и сущности.

Ограничения:
- 1-8 слов;
- БЕЗ пояснений, БЕЗ точки в конце, БЕЗ кавычек;
- Если запрос уже на русском — верни его БЕЗ изменений.

Верни ТОЛЬКО перевод.
"""


class QueryRewriter:
    async def rewrite(
        self,
        original_query: str,
        history: list[ChatMessage],
        provider,  # активный GenerationProvider
        domain_description: str | None = None,
    ) -> str:
        # Пропускаем rewriting если история пустая — переписывать нечего
        if not history:
            return original_query

        history_text = "\n".join(
            f"{m.role}: {m.content[:120]}" for m in history[-4:]
        ) or "нет"

        prompt = REWRITE_PROMPT.format(
            domain_description=domain_description or "общая система поиска по документам",
            history=history_text,
            query=original_query,
        )
        try:
            rewritten = await provider.generate([
                {"role": "user", "content": prompt}
            ])
            rewritten = rewritten.strip()
            if rewritten:
                logger.debug(
                    "QueryRewriter: '%s' → '%s'",
                    original_query[:80],
                    rewritten[:80],
                )
                return rewritten
            return original_query
        except Exception:
            logger.warning("QueryRewriter failed, using original query", exc_info=True)
            return original_query  # fallback — не ломаем пайплайн

    async def rewrite_for_retrieval(
        self,
        step_prompt: str,
        provider,  # активный GenerationProvider
    ) -> str:
        """Формирует поисковый запрос для retrieval-шага пайплайна.

        Используется ТОЛЬКО в PipelineExecutor._retrieve_for_step_dag().
        Для обычного чата без пайплайна используется rewrite() выше.

        Получает готовый step_prompt — system_prompt шага с уже подставленными
        переменными (в т.ч. {query} если она была в шаблоне).
        Задача: извлечь из него ключевые сущности в короткую поисковую фразу.
        ctx.query намеренно не передаётся — смешивание источников здесь некорректно.
        """
        prompt = RETRIEVAL_REWRITE_PROMPT.format(
            step_prompt=step_prompt[:500],  # не перегружаем контекст модели
        )
        try:
            rewritten = await provider.generate([
                {"role": "user", "content": prompt}
            ])
            rewritten = rewritten.strip()
            if rewritten:
                logger.debug(
                    "RetrievalRewrite: '%s' → '%s'",
                    step_prompt[:60],
                    rewritten[:60],
                )
                return rewritten
            return step_prompt
        except Exception:
            logger.warning("rewrite_for_retrieval failed, fallback to step_prompt", exc_info=True)
            return step_prompt  # fallback — не ломаем пайплайн

    async def build_search_queries(
        self,
        original_query: str,
        provider=None,
        *,
        max_queries: int = 4,
    ) -> list[str]:
        """Cross-language query expansion for retrieval.

        Returns a list of queries to feed into `search_knowledge`. When the
        user wrote in English (or any non-Russian language) we additionally
        generate a Russian translation so bge-m3 can match the (mostly
        Russian) corpus more reliably.

        Order of operations:
        1. Always include the original query (verbatim).
        2. If query is not already Russian, call the provider once with
           RU_TRANSLATE_PROMPT to get a Russian translation. The translation
           is added ONLY if it differs from the original (case-folded,
           whitespace-collapsed dedup).
        3. If anything fails (provider unavailable, bad response), return
           just [original_query] — never break the host pipeline.

        `max_queries` caps the output so the model can't blow up the
        evidence budget by emitting 50 translations.
        """
        if not original_query or not original_query.strip():
            return []
        out: list[str] = [original_query.strip()]
        seen_norm = {self._normalise(original_query)}

        if is_cyrillic_query(original_query) or provider is None:
            return out[:max_queries]

        try:
            ru = await provider.generate([
                {"role": "user", "content": RU_TRANSLATE_PROMPT.format(query=original_query)}
            ])
            ru = (ru or "").strip().strip('"').strip("'")
            if not ru:
                return out[:max_queries]
            if self._normalise(ru) in seen_norm:
                return out[:max_queries]
            out.append(ru)
            seen_norm.add(self._normalise(ru))
        except Exception:
            logger.warning(
                "build_search_queries: RU translation failed, falling back to original",
                exc_info=True,
            )

        return out[:max_queries]

    @staticmethod
    def _normalise(text: str) -> str:
        """Lowercase + collapse whitespace — used as dedup key."""
        return re.sub(r"\s+", " ", text or "").strip().lower()


query_rewriter = QueryRewriter()
