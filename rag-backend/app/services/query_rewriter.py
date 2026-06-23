from __future__ import annotations

import logging

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

Задача: извлеки из задания ключевые сущности и сформируй короткую поисковую фразу.

Правила:
- Фраза должна быть короткой: 3-10 слов
- Выдели конкретные сущности: имена, места, предметы, события, термины
- Убери глаголы-команды ("выгрузи", "найди", "определи", "получи информацию о")
- Убери вежливости и служебные слова
- Сохрани язык задания

Верни ТОЛЬКО поисковую фразу — без объяснений, без знаков препинания в конце.
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


query_rewriter = QueryRewriter()
