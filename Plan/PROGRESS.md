# PROGRESS: Reranker Model Management

<!-- 
ПРАВИЛА ОБНОВЛЕНИЯ ЭТОГО ФАЙЛА:
- Модель обновляет ТОЛЬКО строку своего текущего шага в таблице
- Формат статуса: [ ] = не начат, [~] = в процессе, [x] = завершён, [!] = проблема
- После завершения шага — добавить краткую заметку в секцию Notes
- НИКОГДА не удалять строки и не менять статус чужих шагов
-->

## Статус шагов

| # | Шаг | Статус | Чат |
|---|-----|--------|-----|
| 1 | ORM модель `RerankModel` + миграция БД | [x] | — |
| 2 | CRUD методы в `settings_service.py` | [x] | — |
| 3 | Pydantic схемы в `schemas.py` | [x] | — |
| 4 | API роутер `rerank_models.py` + регистрация | [x] | — |
| 5 | `_check_reranker_provider()` в `helpers.py` | [x] | — |
| 6 | Логика rerankinga в `retrieval.py` | [x] | — |
| 7 | Фронтенд: вкладка + `rerank_models.js` | [x] | — |
| 8 | Удаление старых ключей `reranker.*` из platform_settings | [ ] | — |
| 9 | Сквозное тестирование (manual QA) | [ ] | — |

## Notes

[Step 1] Добавлен класс `RerankModel` в конец `models.py` (после `PipelineDecision`, перед алиасом). Структура таблицы соответствует CONCEPT.md §1. Миграция `0017_add_rerank_models.py` создаёт только таблицу `rerank_models`, существующие не тронуты.

[Step 2] Добавлены методы `_get_rerank_model`, `list_rerank_models`, `create_rerank_model`, `update_rerank_model`, `delete_rerank_model`, `activate_rerank_model`, `get_active_rerank_model`, `_rerank_model_dict` в конец класса `SettingsService`. Существующие методы не изменены. Добавлен импорт `RerankModel` в строку импортов.

[Step 3] Добавлены `RerankModelCreateRequest` и `RerankModelUpdateRequest` в конец `schemas.py`. Существующие схемы не изменены.

[Step 4] Создан `rag-backend/app/api/settings/rerank_models.py` — роутер по аналогии с `emb_models.py`. Имплементированы все 7 эндпоинтов: GET list, POST create, PUT update, DELETE delete, POST activate, POST deactivate, POST check. Lookup по `model_id` (str), не по UUID PK. Роутер зарегистрирован в `__init__.py` рядом с `emb_models_router`.

[Step 5] Добавлена функция `_check_reranker_provider(model: RerankModel)` в конец `helpers.py`. Добавлен импорт `RerankModel` в строку импортов. Существующие функции не тронуты. Поддерживаются openai_compatible / cohere / jina (единый формат POST /rerank).

[Step 6] Добавлена функция `rerank_hits(query, hits, db)` в конец `retrieval.py`. Функция вызывает `settings_service.get_active_rerank_model(db)` — если модели нет или `enabled=False`, возвращает hits без изменений. Поддерживаются оба формата ответа провайдера: `relevance_score` и `score`. В `retrieve_multi_vault()` добавлен вызов `result = await rerank_hits(query, result, db)` сразу после `result = all_hits[:effective_top_k]`. Функция `retrieve()` не тронута. `httpx` был уже импортирован — новый импорт не добавлялся. Логирование: `RERANK_HITS start` и `RERANK_HITS done`.

[Step 7] Создан `tab-rerank-models.js` (миксин по аналогии с emb/gen-моделями). Вкладка `rerank-models` добавлена в HTML (навешная панель и `<script>` тег). В `api.js` добавлены все rerank-методы (getRerankModels, createRerankModel, updateRerankModel, deleteRerankModel, activateRerankModel, deactivateRerankModel, checkRerankModel). В `settings.js` добавлены кейсы `rerank-models` в `loadTab()` и `_dispatch()` — без этого вкладка не рендерилась и кнопки не работали.

## Зависимости между шагами

```
Шаг 1 (ORM) → Шаг 2 (service) → Шаг 3 (schemas) → Шаг 4 (API)
                                                         ↓
                                               Шаг 5 (check helper)
Шаг 2 (service) → Шаг 6 (retrieval logic)
Шаг 4 + Шаг 7 (frontend) → Шаг 8 (cleanup)
Всё → Шаг 9 (QA)
```

Шаги 1–3 можно делать в одном чате (они маленькие).
Шаги 4–5 — в одном чате.
Шаг 6 — отдельный чат (критически важная логика).
Шаг 7 — отдельный чат (фронтенд).
Шаги 8–9 — финальный чат.
