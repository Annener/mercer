# TD-08 — Лишний async у _default_top_k()

**Приоритет:** 🟠 Структурный  
**Файл:** `rag-backend/app/services/retrieval.py`, функция `_default_top_k`

## Проблема

```python
# Текущий код:
async def _default_top_k() -> int:
    return int(os.getenv("DEFAULT_TOP_K", "10"))
```

Внутри нет ни одного `await`. Объявлять функцию `async` без необходимости —
антипаттерн: каждый вызов создаёт лишний coroutine object, который нужно
`await`-ить.

## Анализ перед исправлением

- [ ] Найти все места вызова `_default_top_k()` — проверить, что везде стоит `await`
- [ ] Убедиться, что функция не overriding-ится в тестах как async

## Ожидаемое исправление

Убрать `async`, убрать все `await` перед вызовами:

```python
def _default_top_k() -> int:
    return int(os.getenv("DEFAULT_TOP_K", "10"))
```

Либо вообще заменить на константу на уровне модуля:
```python
_DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "10"))
```

## Риски

Минимальные. Строго механическое изменение.
