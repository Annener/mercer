# TD-05 — Дублирование логики в методе decide() PipelineRouter

**Приоритет:** 🟡 Серьёзный  
**Файл:** `rag-backend/app/routers/pipeline_router.py`, метод `decide()`

## Проблема

Метод `decide()` содержит почти идентичный код LLM-роутинга что и метод `select()`:
- Тот же `PROMPT_TEMPLATE`
- Та же логика фильтрации пайплайнов
- Разница: `decide()` принимает `Chat` ORM-объект, `select()` принимает `PipelineExecutionContext`

Это дублирование означает, что баг-фикс или изменение промпта нужно вносить в двух местах.

## Анализ перед исправлением

- [ ] Найти все вызовы `pipeline_router.decide()` (или `PipelineRouter(...).decide()`)
- [ ] Понять — `decide()` используется в продакшн-коде или только в тестах?
- [ ] Сравнить сигнатуры: что именно передаётся в `decide()` vs `select()`
- [ ] Проверить, можно ли `Chat` привести к `PipelineExecutionContext` без потери данных

## Ожидаемое исправление

**Сценарий A (`decide()` только в тестах):**  
Переписать тесты на использование `select()`, удалить `decide()`.

**Сценарий B (`decide()` в продакшн-коде):**  
Реализовать `decide()` через делегацию к `select()`:
```python
async def decide(self, chat: Chat, ...) -> ...:
    ctx = PipelineExecutionContext.from_chat(chat)  # новый classmethod
    return await self.select(ctx, ...)
```

## Риски

Средние — нужно не сломать тесты при рефакторинге.
