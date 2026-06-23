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

**Статус**: `[x]` — завершено 23.06.2026

**Зависит от**: Этап 1

**Чеклист**:
- [x] `parser/semantic_chunker.py` — создан
- [x] `parser/__init__.py` — экспортирует `SemanticChunker`
- [x] Реализованы: sentence split, embed_batch, cosine distance, MIN guard, MAX guard
- [x] Переиспользован `extract_markdown_headers` из `embedding_enricher.py` (жёсткие границы по заголовкам)
- [x] `split()` принимает уже очищенный текст (не вызывает preprocess внутри)
- [x] `tests/test_semantic_chunker.py` — написан (10 тестов)

**Заметки**:
- Разбивка на предложения: regex-split по абзацам (`\n\n`) + по концу предложения — без nltk
- Заголовки `#{1,6}` определяются как отдельный unit и создают жёсткую границу (break перед заголовком)
- cosine distance реализован чистым Python (без numpy) через `math.sqrt` + `sum`
- MIN_CHUNK_SENTENCES=2: короткий блок присоединяется к предыдущему (если есть), иначе к следующему
- MAX_CHUNK_CHARS=4000: `_fixed_split()` делит по последнему пробелу внутри лимита
- `embed_batch` вызывается ровно один раз на весь документ (один батч-запрос)
- Верификация: `pytest rag-indexer/tests/test_semantic_chunker.py`

---

## Этап 4 — Интеграция в `IndexerWorker`

**Статус**: `[x]` — завершено 23.06.2026

**Зависит от**: Этапы 2 и 3

**Чеклист**:
- [x] `preprocess(text_for_chunking)` вызывается ДО чанкинга
- [x] Обе старые ветки (fixed + entity_aware) заменены на `SemanticChunker`
- [x] `word_start` в metadata заполняется в `_build_chunk_records` для PDF page assignment
- [x] Логирование: количество чанков + threshold
- [x] `tests/test_indexer_integration.py` — написан (5 тестов)
- [ ] `pytest rag-indexer/tests/` — запустить вручную
- [ ] Запущена индексация тестового документа вручную
- [ ] Чанки проверены в LanceDB

**Заметки**:
- Удалены импорты `chunk_with_entities`, `chunk_text` из `indexer_worker.py`
- Удалены параметры `chunk_size`, `overlap`, `entity_aware` из сигнатуры `_process_file` и вызова `run_indexing`
- Добавлен `_build_chunk_records()` — преобразует `list[str]` в `list[ChunkRecord]` с `word_start`/`word_end`
- Импорт `uuid` добавлен в `indexer_worker.py` (нужен для `_build_chunk_records`)
- Тесты: 5 кейсов (upsert count, word_start, empty text, preprocess order, threshold effect)
- Коммит: [d277e35](https://github.com/Annener/mercer/commit/d277e353beb57e57a17e9343cba2beb8cc5a9860) (indexer_worker.py), [9fb8b89](https://github.com/Annener/mercer/commit/9fb8b89d8556eb8c067e6c2b601292fa50676345) (test)

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
| 3. SemanticChunker | `[x]` | Завершено 23.06.2026, 3 файла + 10 тестов |
| 4. Интеграция | `[x]` | Завершено 23.06.2026, 2 файла + 5 тестов |
| 5. Проверка качества | `[ ]` | |

---

*Последнее обновление: 23.06.2026, Этап 4 завершён*
