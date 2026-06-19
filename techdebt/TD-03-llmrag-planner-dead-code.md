# TD-03 — Мёртвый класс LLMRAGPlanner

**Приоритет:** 🟡 Серьёзный  
**Файл:** `rag-backend/app/services/planner.py`, класс `LLMRAGPlanner`

## Проблема

Класс `LLMRAGPlanner` определён, но не используется в текущей архитектуре.
Декомпозиция запросов переехала в `query_rewriter.py`. При этом класс
импортирует `get_generation_provider` из `app.providers.generation` — если
этот экспорт не сохранён в `__init__.py`, модуль упадёт с `ImportError`
при первом импорте.

## Анализ перед исправлением

- [ ] Проверить `app/providers/generation/__init__.py` — реэкспортирует ли
  `get_generation_provider` и `GenerationProviderUnavailableError`?
- [ ] Поиск по проекту: `LLMRAGPlanner` — есть ли импорты или использование?
- [ ] Сравнить `LLMRAGPlanner.decompose()` и `QueryRewriter` — возможно,
  есть полезная логика, которую стоит перенести перед удалением
- [ ] Проверить тесты: нет ли тестов на `LLMRAGPlanner`

## Ожидаемое исправление

Удалить класс `LLMRAGPlanner` из `planner.py` вместе с неиспользуемыми импортами
(`get_generation_provider`, `GenerationProviderUnavailableError`).

Если класс использовался в тестах — удалить соответствующие тесты.

## Риски

Низкие при условии подтверждения отсутствия использований.
