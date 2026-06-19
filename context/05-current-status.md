# 05 — Текущий статус проекта

**Дата последнего обновления:** 2026-06-19

## Состояние

✅ **Pipeline Redesign (DAG) — ЗАВЕРШЁН**
Все 11 этапов выполнены. Pytest: `104 passed, 1 warning`.

## Что реализовано

### Core платформа
- [x] Многосервисная архитектура (docker-compose)
- [x] PostgreSQL + Alembic-миграции (0001..0019)
- [x] LanceDB через db-api-server REST
- [x] Управление настройками через БД + runtime-кэш
- [x] Шифрование API-ключей (Fernet)
- [x] Система доменов (dnd, work, default)
- [x] Vault-ы с привязкой к доменам и моделям эмбеддингов
- [x] FSM уточняющих вопросов (clarification)
- [x] Query rewriter
- [x] Retrieval с гибридным поиском
- [x] Аудит-лог

### Пайплайны (DAG, завершено 2026-06-19)
- [x] DAG-модель (`PipelineStep.after_step_ids`, `step_id`, `type: validation`)
- [x] DAG-движок `pipeline_dag.py` (топологическая сортировка, уровни)
- [x] `prompt_pack.py`: `resolve_step_vars()`, `{STEP_ID.result}`, `{STEP_ID.key}`
- [x] `PipelineExecutionContext.resolve()`
- [x] `POST /pipeline_confirm` + `POST /pipeline_resume` API
- [x] Confirm-флоу в `send_stream()` с TTL 1ч
- [x] Миграция старых пайплайнов (`tools/migrate_pipelines.py`)
- [x] UI: Vis.js DAG-конструктор
- [x] UI: inline-карточки выполнения в ленте чата
- [x] Сквозное тестирование

### Индексация
- [x] Chunking с entity-aware mode
- [x] Эмбеддинги через Ollama (nomic/Qwen3)
- [x] PDF через pdf-sidecar (hi_res OCR) + pdfminer fallback
- [x] WebSocket прогресс в реальном времени
- [x] Statefile-трекинг задач

### Frontend (SPA, в `rag-backend/app/static/`)
- [x] Чат-интерфейс с SSE-стримингом
- [x] Управление доменами и vault-ами
- [x] Управление моделями (generation, embedding, rerank)
- [x] Управление тегами и кампаниями
- [x] DAG-конструктор пайплайнов (Vis.js)
- [x] Inline-карточки пайплайна в чате

## Технический долг (малоприоритетный)

| Задача | Приоритет | Файл |
|--------|-----------|------|
| `object.__setattr__` в DAG-тестах при `frozen=True` → `.model_copy(update=...)` | низкий | тесты |
| `pipeline_builder.js`: drag рёбер мышью | низкий | static/ |
| `pipeline_builder.js`: горячие клавиши Del для узла | низкий | static/ |
| Confirm-флоу в non-stream `send()` | средний | api/chat.py |
| Интеграционные тесты confirm-флоу | средний | tests/ |
| Ручная API-проверка мигрированных пайплайнов | желательно | — |
| `TODO(iter4-cleanup)`: убрать `vault_id` из `CreateChatRequest` | низкий | models.py |
| `TODO(iter4-cleanup)`: `vault_id` из `ChatRecord` | низкий | models.py |

## Возможные следующие направления

1. **Reranker** — включить и настроить (конфиг есть, код есть, выключен)
2. **BM25 + гибридный поиск** — добавить полнотекстовый поиск к семантическому
3. **Мониторинг** — логи есть, нет дашборда метрик
4. **Авторизация** — сейчас нет auth
5. **Iter4 cleanup** — убрать deprecated `vault_id` поля
6. **Pipeline dry-run** — тестовый прогон без сохранения

## Активная конфигурация

- Домен: `dnd` (активен), `work` (выключен)
- Embedding: Qwen3-Embedding-4B Q4_K_M (Ollama, 2560 dims)
- Generation: deepseek-chat-v3.1 (openrouter через proxyapi.ru)
- Reranker: выключен
- top_k: 10
- chunk_size: 2000 слов, overlap: 64 слова
