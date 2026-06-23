# Semantic Chunking — Статус реализации

> Этот файл обновляется моделью в начале каждого чата.
> Формат: `[ ]` — не начато, `[~]` — в процессе, `[x]` — завершено и верифицировано.

---

## Этап 0 — Разведка

**Статус**: `[ ]`

**Файл результата**: `plan-semantic/recon.md` (не создан)

**Чеклист**:
- [ ] Прочитан `base_provider.py` — сигнатура `embed`, наличие `embed_batch`
- [ ] Прочитан `ollama_provider.py`
- [ ] Прочитан `openai_provider.py`
- [ ] Прочитан `generic_chunker.py` — сигнатура `chunk_text`, возвращаемый тип
- [ ] Прочитан `entity_chunker.py` — используется ли `_entities` после возврата
- [ ] Прочитан `embedding_enricher.py` — сигнатуры `build_embedding_text`, `extract_markdown_headers`
- [ ] Прочитан `preprocessor.py` — сигнатура `preprocess`, синхронная/асинхронная
- [ ] Прочитан `_process_file` в `indexer_worker.py` — точный порядок вызовов
- [ ] Прочитан `models.py` — все поля `Vault`
- [ ] Прочитан `migrations.py` — формат последней миграции
- [ ] Прочитан `shared_contracts/models.py` — передаётся ли vault между сервисами
- [ ] Прочитан `db_client.py` — что возвращает `get_vault` (dict / ORM / dataclass)
- [ ] Написан `plan-semantic/recon.md`

**Заметки**:
*(модель заполняет при работе)*

---

## Этап 1 — `embed_batch` в провайдерах

**Статус**: `[ ]`

**Зависит от**: Этап 0

> Пропустить если `embed_batch` уже есть (выяснится в Этапе 0)

**Чеклист**:
- [ ] `base_provider.py` — добавлен абстрактный метод `embed_batch`
- [ ] `ollama_provider.py` — реализация через `asyncio.gather`
- [ ] `openai_provider.py` — реализация через batch-запрос
- [ ] `tests/test_embed_batch.py` — написан и проходит

**Заметки**:
*(модель заполняет при работе)*

---

## Этап 2 — Миграция БД и ORM

**Статус**: `[ ]`

**Зависит от**: Этап 0

**Чеклист**:
- [ ] `models.py` — добавлено поле `semantic_threshold: float = 0.3`
- [ ] `migrations.py` — добавлен SQL ALTER TABLE
- [ ] Pydantic-схемы Vault — добавлено поле
- [ ] `db_client.py` — `get_vault` возвращает `semantic_threshold`
- [ ] `shared_contracts/models.py` — обновлён если нужно
- [ ] Миграция применена локально
- [ ] Поле проверено через API (create + get)

**Заметки**:
*(модель заполняет при работе)*

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
- [ ] `word_start` в metadata заполняется для PDF (для `_assign_page_numbers_and_headers`)
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
| 0. Разведка | `[ ]` | |
| 1. embed_batch | `[ ]` | |
| 2. Миграция БД | `[ ]` | |
| 3. SemanticChunker | `[ ]` | |
| 4. Интеграция | `[ ]` | |
| 5. Проверка качества | `[ ]` | |

---

*Последнее обновление: не начато*
