from __future__ import annotations

import logging

from shared_contracts.models import ChatMessage

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """\
Ты — помощник для улучшения поисковых запросов.

Контекст системы: {domain_description}

История диалога (последние сообщения):
{history}

Новый запрос пользователя: "{query}"

Задача: перепиши запрос так, чтобы он был самодостаточным — понятным без контекста истории.
Правила:
- Замени местоимения и указания ("это", "он", "там", "второй пункт") на конкретные сущности из истории
- Сохрани исходный смысл и язык запроса
- Не добавляй информацию, которой нет в запросе или истории
- Не отвечай на вопрос — только перепиши его

Верни ТОЛЬКО переформулированный запрос, без объяснений.
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


query_rewriter = QueryRewriter()
