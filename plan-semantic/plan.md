# Semantic Chunking — План реализации

> Стратегия всегда `semantic` — hardcode в воркере, поле `chunking_strategy` в БД не нужно.
> Каждый этап = отдельный чат с чистым контекстом.
> Переходить к следующему этапу только после верификации текущего.

---

## Этап 0 — Разведка

**Цель**: собрать реальные сигнатуры и структуры кода до начала любых изменений.
Этот этап защищает все последующие от галлюцинаций на основе «предполагаемого» кода.

**Что читаем** (модель открывает и конспектирует):
- `rag-indexer/embedding/base_provider.py` — полностью: есть ли `embed_batch`, сигнатура `embed`
- `rag-indexer/embedding/ollama_provider.py` — метод `embed` и всё связанное
- `rag-indexer/embedding/openai_provider.py` — то же
- `rag-indexer/parser/chunking/generic_chunker.py` — сигнатура `chunk_text`, что возвращает
- `rag-indexer/parser/chunking/entity_chunker.py` — используется ли результат `_entities` где-либо в воркере после возврата
- `rag-indexer/parser/chunking/embedding_enricher.py` — сигнатуры `build_embedding_text`, `extract_markdown_headers`
- `rag-indexer/parser/preprocessing/preprocessor.py` — сигнатура `preprocess`, идемпотентность
- `rag-indexer/indexer_worker.py` — метод `_process_file` целиком: порядок вызовов parse→chunk→preprocess→embed, как передаётся `provider`, как достаётся `vault` из БД
- `rag-backend/app/db/models.py` — поля модели `Vault`
- `rag-backend/app/db/migrations.py` — последняя миграция, формат SQL-скриптов
- `shared_contracts/models.py` — есть ли VaultConfig или передача vault между сервисами
- `rag-indexer/app/db_client.py` — метод `get_vault`, что возвращает (dict или объект)

**Результат**: файл `plan-semantic/recon.md` со следующими разделами:
- Точные сигнатуры `EmbeddingProvider`: есть ли `embed_batch`, как выглядит `embed`
- Как сейчас работает чанкер: функция/класс, сигнатура, что возвращает
- Используется ли `_entities` из `chunk_with_entities` после возврата (да/нет + где)
- Сигнатуры `build_embedding_text` и `extract_markdown_headers`
- Сигнатура и поведение `preprocess` (синхронная/асинхронная, идемпотентна)
- Точный порядок вызовов в `_process_file`: где именно чанкинг, где preprocess, где embed
- Текущие поля `Vault` в ORM (все поля)
- Формат последней миграции (шаблон SQL)
- Как `get_vault` возвращает данные (dict / ORM-объект / dataclass)
- Передаётся ли vault между сервисами через `shared_contracts`

**Верификация**: `recon.md` написан, все сигнатуры взяты из реального кода.

---

## Этап 1 — `embed_batch` в провайдерах эмбеддингов

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`

**Цель**: добавить метод `embed_batch(texts: list[str]) -> list[list[float]]` в базовый
класс и оба провайдера. Это фундамент для `SemanticChunker` — батчинг предложений
одним запросом вместо N последовательных.

> Если `embed_batch` уже есть (выяснится в Этапе 0) — пропустить этап.

**Задачи**:
1. `base_provider.py` — добавить абстрактный метод `embed_batch`
2. `ollama_provider.py` — реализация: Ollama не поддерживает батч нативно → N параллельных через `asyncio.gather`
3. `openai_provider.py` — реализация: POST `/embeddings` с массивом `input` (OpenAI-compatible API поддерживает батч нативно)
4. Тест: `rag-indexer/tests/test_embed_batch.py` — мок HTTP, проверить что батч не делает N последовательных вызовов

**Результат**:
- Изменены 3 файла в `rag-indexer/embedding/`
- Новый тест-файл
- `embed_batch` работает для обоих провайдеров

**Верификация**: `pytest rag-indexer/tests/test_embed_batch.py` — все зелёные.

---

## Этап 2 — Миграция БД и ORM

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`

**Цель**: добавить поле `semantic_threshold: float` в `Vault`.

**Задачи**:
1. `rag-backend/app/db/models.py` — добавить поле:
   ```python
   semantic_threshold: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
   ```
2. `rag-backend/app/db/migrations.py` — новый SQL-скрипт по образцу последней миграции:
   ```sql
   ALTER TABLE vaults ADD COLUMN IF NOT EXISTS semantic_threshold FLOAT NOT NULL DEFAULT 0.3;
   ```
3. Pydantic-схемы Vault (`VaultCreate`, `VaultUpdate`, `VaultResponse`) — добавить
   `semantic_threshold: float = 0.3`
4. `rag-indexer/app/db_client.py` — убедиться что `get_vault` возвращает `semantic_threshold`
   (если возвращает dict — поле появится автоматически после миграции; если ORM-объект — нужно добавить в схему)
5. `shared_contracts/models.py` — если vault передаётся между сервисами, добавить поле туда же

**Результат**:
- Vault в БД имеет поле `semantic_threshold`
- API принимает и возвращает поле
- Существующие записи получают дефолт 0.3 без потери данных

**Верификация**: применить миграцию локально, создать/обновить Vault через API,
проверить что поле сохраняется и возвращается.

---

## Этап 3 — Класс `SemanticChunker`

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`

**Цель**: написать изолированный класс `SemanticChunker` и покрыть его тестами.
Никаких зависимостей от HTTP, БД или FastAPI — только `EmbeddingProvider` и чистая логика.

**Важно**: метод `split(text)` принимает **уже очищенный текст** (после `preprocess()`).
Не нужно вызывать preprocess внутри чанкера — это ответственность воркера.

**Задачи**:
1. Новый файл `rag-indexer/parser/semantic_chunker.py`:

   ```python
   class SemanticChunker:
       MIN_CHUNK_SENTENCES = 2
       MAX_CHUNK_CHARS = 4000

       def __init__(self, embedding_provider: EmbeddingProvider, threshold: float = 0.3):
           ...

       async def split(self, text: str) -> list[str]:
           # 1. split text into sentences (nltk.sent_tokenize или regex)
           # 2. жёсткие границы по заголовкам (extract_markdown_headers из embedding_enricher)
           # 3. embed_batch(sentences) — один батч-запрос
           # 4. cosine distance между соседними эмбеддингами
           # 5. cut where distance > threshold
           # 6. apply MIN_CHUNK_SENTENCES guard (объединить с соседним если мало)
           # 7. apply MAX_CHUNK_CHARS guard (fixed-split если слишком велик)
           # 8. return list[str]
           ...
   ```

   Переиспользовать `extract_markdown_headers` из `embedding_enricher.py`
   для жёстких границ по заголовкам — не писать свой regex.

2. Обновить `rag-indexer/parser/__init__.py` — экспортировать `SemanticChunker`

3. Тесты `rag-indexer/tests/test_semantic_chunker.py`:
   - Мок `EmbeddingProvider.embed_batch` возвращает заранее заданные векторы
   - Тест: два семантически далёких блока → два чанка
   - Тест: один связный текст → один чанк
   - Тест: заголовок `## Section` всегда создаёт границу
   - Тест: очень короткий чанк (1 предложение) объединяется с соседним (MIN guard)
   - Тест: очень длинный блок (>MAX_CHUNK_CHARS) разбивается
   - Тест: пустая строка → пустой список
   - Тест: `embed_batch` вызывается ровно один раз (не N раз)

**Результат**:
- `rag-indexer/parser/semantic_chunker.py` — готов
- Тесты покрывают основные случаи и edge-cases

**Верификация**: `pytest rag-indexer/tests/test_semantic_chunker.py` — все зелёные.

---

## Этап 4 — Интеграция в `IndexerWorker`

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`
+ реальный код `_process_file` из `indexer_worker.py` (вставить в чат)

**Цель**: подключить `SemanticChunker` в воркер, добавить `preprocess` до чанкинга,
заменить обе ветки (fixed + entity_aware) на единственный путь через semantic.

**Задачи**:
1. `rag-indexer/indexer_worker.py` — в методе `_process_file`, **после** `merge_pdf_pages`
   и **до** чанкинга:

   ```python
   # НОВОЕ: pre-clean перед semantic split (preprocess идемпотентна)
   from parser.preprocessing.preprocessor import preprocess as preprocess_text
   cleaned_for_chunking = await asyncio.to_thread(
       preprocess_text, text_for_chunking, relative_path
   )

   # Заменяем обе ветки (entity_aware / generic) единственным:
   from parser.semantic_chunker import SemanticChunker
   raw_chunks = await SemanticChunker(
       provider,
       float(vault.get("semantic_threshold", 0.3))
   ).split(cleaned_for_chunking)
   ```

   Далее собрать `chunks: list[Chunk]` из `raw_chunks: list[str]` с метаданными
   (аналогично тому, как это делает `generic_chunker` — взять из `recon.md`).

2. Убедиться что после замены чанкера остальной пайплайн не изменился:
   - `strip_page_markers` + `preprocess(chunk.text)` на каждом чанке — остаётся
   - `_assign_page_numbers_and_headers` для PDF — остаётся (работает по `word_start` из metadata)
   - `build_embedding_text` на каждом чанке — остаётся
   - `_embed_chunks` — остаётся

   > ⚠️ `_assign_page_numbers_and_headers` использует `chunk.metadata["word_start"]`.
   > `SemanticChunker` должен заполнять это поле для каждого чанка, иначе
   > page_number у PDF-чанков будет потерян. Уточнить формат в `recon.md`.

3. Удалить / закомментировать ветку `entity_aware` (после проверки в Этапе 0,
   что `_entities` нигде не используется).

4. Добавить логирование:
   ```python
   logger.info(
       "SemanticChunker: file=%s chunks=%d threshold=%.2f",
       relative_path, len(raw_chunks), threshold
   )
   ```

5. Интеграционный тест `rag-indexer/tests/test_indexer_integration.py`:
   - Мок `EmbeddingProvider.embed_batch`
   - Мок `StorageClient.upsert_with_retry`
   - Прогнать `_process_file` на тестовом тексте
   - Проверить что `upsert_with_retry` вызван с правильным количеством чанков
   - Проверить что `preprocess` вызывался до чанкинга (через spy/mock)

**Результат**:
- Воркер использует `SemanticChunker` для всех документов
- `preprocess` вызывается до чанкинга
- Оба старых пути (fixed/entity) убраны
- Логи показывают количество чанков и threshold

**Верификация**: `pytest rag-indexer/tests/` — все зелёные.
Запустить индексацию тестового документа вручную, проверить чанки в LanceDB.

---

## Этап 5 — Ручная проверка качества

**Цель**: убедиться что semantic chunking реально улучшает качество, а не только
«работает технически».

**Задачи**:
1. Взять 2–3 реальных документа из Vault (PDF + MD).
2. Проиндексировать с `semantic_threshold=0.3` (дефолт).
3. Посмотреть чанки в LanceDB — нет ли аномалий:
   - Чанки из 1 предложения (MIN guard не сработал?)
   - Чанки >4000 символов (MAX guard не сработал?)
   - Пустые чанки
4. Задать 5–10 тестовых вопросов через retrieval, сравнить качество ответов
   с предыдущей fixed-стратегией (если есть snapshot).
5. Попробовать `semantic_threshold=0.2` и `0.4`, зафиксировать разницу.

**Верификация**: чанки выглядят семантически связными, нет очевидных аномалий,
retrieval возвращает релевантные результаты.
