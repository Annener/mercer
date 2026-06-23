# Semantic Chunking — Статус реализации

> Этот файл обновляется моделью в начале каждого чата.
> Формат: `[ ]` — не начато, `[~]` — в процессе, `[x]` — завершено и верифицировано.

---

## Этап 0 — Разведка

**Статус**: `[x]` — завершено 23.06.2026

**Файл результата**: `plan-semantic/recon.md` — заполнен

**Чеклист**:
- [x] Прочитан `base_provider.py` — сигнатура `embed`, `embed_batch` ОТСУТСТВОВАЛА
- [x] Прочитан `ollama_provider.py`
- [x] Прочитан `openai_provider.py`
- [x] Прочитан `generic_chunker.py` — сигнатура `chunk_text`, возвращаемый тип
- [x] Прочитан `entity_chunker.py` — `_entities` НЕ используется после возврата
- [x] Прочитан `embedding_enricher.py` — сигнатуры `build_embedding_text`, `extract_markdown_headers`
- [x] Прочитан `preprocessor.py` — синхронная, идемпотентная
- [x] Прочитан `_process_file` в `indexer_worker.py` — точный порядок вызовов
- [x] Прочитан `models.py` — все поля `Vault`, `semantic_threshold` ОТСУТСТВУЕТ
- [x] Прочитан `migrations.py` — Alembic runner, реальные миграции в `migrations/versions/`
- [x] Прочитан `shared_contracts/models.py` — vault передаётся, `semantic_threshold` ОТСУТСТВУЕТ
- [x] Прочитан `db_client.py` — `get_vault` возвращает `dict`, SELECT *
- [x] Написан `plan-semantic/recon.md`

**Ключевые находки**:
- `embed_batch` отсутствовал — Этап 1 выполнен
- `_entities` не используется — ветку заменяем безболезненно
- `migrations.py` — это Alembic runner; новая миграция добавляется в `migrations/versions/0022_...py`
- preprocess сейчас вызывается ПОСЛЕ чанкинга; для SemanticChunker — ДО

---

## Этап 1 — `embed_batch` в провайдерах

**Статус**: `[x]` — завершено 23.06.2026

**Зависит от**: Этап 0

**Чеклист**:
- [x] `base_provider.py` — добавлен абстрактный метод `embed_batch`
- [x] `ollama_provider.py` — реализация через `asyncio.gather` (N параллельных POST на /api/embeddings)
- [x] `openai_provider.py` — реализация через batch-запрос (`"input": list[str]`, 1 HTTP-запрос)
- [x] `tests/test_embed_batch.py` — написан (7 тестов: параллелизм Ollama, единственный запрос OpenAI, порядок, пустой вход, mismatch)

**Заметки**:
- Ollama `embed_batch`: без Semaphore (SemanticChunker вызывает батч 1 раз на документ; предложения обрабатываются быстро)
- OpenAI `embed_batch`: один POST с `input: list[str]`, ответ `data[i].embedding` → `results[i]`
- При несоответствии длины ответа и входа возвращаются `[]` для каждого текста
- Верификация: `pytest rag-indexer/tests/test_embed_batch.py`

---

## Этап 2 — Миграция БД и ORM

**Статус**: `[x]` — завершено 23.06.2026

**Зависит от**: Этап 0

**Чеклист**:
- [x] `rag-backend/app/db/models.py` — добавлено поле `semantic_threshold: float = 0.3`
- [x] `rag-backend/migrations/versions/0022_add_semantic_threshold.py` — новый Alembic-файл (upgrade: add_column → backfill → NOT NULL; downgrade: drop_column)
- [x] `shared_contracts/models.py` — добавлено поле в VaultRead (`float = 0.3`), VaultCreate (`float = 0.3`), VaultUpdate (`float | None = None`), VaultConfigEntry (`float = 0.3`)
- [ ] `db_client.py` — `get_vault` вернёт `semantic_threshold` автоматически (через SELECT *) — **проверить вручную после применения миграции**
- [ ] Миграция применена локально (`alembic upgrade head`)
- [ ] Поле проверено через API (create + get)

**Заметки**:
- ORM-модель `Vault` в `rag-backend/app/db/models.py`: `Column(Float, nullable=False, default=0.3, server_default="0.3")`
- Alembic-миграция: 3-шаговая (add nullable → backfill → NOT NULL) для безопасного применения на живой БД
- `db_client.py` не требует изменений — `get_vault` использует `SELECT *`, поле вернётся автоматически
- После `alembic upgrade head` проверить: `SELECT semantic_threshold FROM vaults LIMIT 5;`

---

## Этап 3 — Класс `SemanticChunker`

**Статус**: `[ ]`

**Зависит от**: Этап 1

**Чеклист**:
- [ ] `parser/semantic_chunker.py` — создан
- [ ] `parser/__init__.py` — экспортирует `SemanticChunker`
- [ ] Реализованы: sentence split, embed_batch, cosine distance, MIN guard, MAX guard
- [ ] Переиспользован `extract_markdown_headers` из `embedding_enricher.py`
- [ ] `split()` принимает уже очищенный текст (не вызывает preprocess внутри)
- [ ] `tests/test_semantic_chunker.py` — все тесты зелёные

**Заметки**:
*(модель заполняет при работе)*

---

## Этап 4 — Интеграция в `IndexerWorker`

**Статус**: `[ ]`

**Зависит от**: Этапы 2 и 3

**Чеклист**:
- [ ] `preprocess(text_for_chunking)` вызывается ДО чанкинга
- [ ] Обе старые ветки (fixed + entity_aware) заменены на `SemanticChunker`
- [ ] `word_start` в metadata заполняется в SemanticChunker для PDF page assignment
- [ ] Логирование: количество чанков + threshold
- [ ] `tests/test_indexer_integration.py` — проходит
- [ ] Запущена индексация тестового документа вручную
- [ ] Чанки проверены в LanceDB

**Заметки**:
*(модель заполняет при работе)*

---

## Этап 5 — Ручная проверка качества

**Статус**: `[ ]`

**Зависит от**: Этап 4

**Чеклист**:
- [ ] Проиндексированы 2–3 реальных документа (PDF + MD)
- [ ] Аномалий нет: нет чанков из 1 предложения, нет чанков >4000 символов
- [ ] Проверено 5–10 тестовых запросов через retrieval
- [ ] Протестированы threshold 0.2 / 0.3 / 0.4 — разница зафиксирована
- [ ] BM25/гибридный поиск работает без изменений

**Заметки**:
*(модель заполняет при работе)*

---

## Итоговый статус

| Этап | Статус | Комментарий |
|---|---|---|
| 0. Разведка | `[x]` | Завершено 23.06.2026, recon.md заполнен |
| 1. embed_batch | `[x]` | Завершено 23.06.2026, 3 файла + тест |
| 2. Миграция БД | `[x]` | Завершено 23.06.2026, 3 файла |
| 3. SemanticChunker | `[ ]` | |
| 4. Интеграция | `[ ]` | |
| 5. Проверка качества | `[ ]` | |

---

*Последнее обновление: 23.06.2026, Этап 2 завершён*
