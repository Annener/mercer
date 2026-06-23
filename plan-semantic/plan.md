# Semantic Chunking — План реализации

> Стратегия всегда `semantic`. Поле `chunking_strategy` в БД не нужно — hardcode в воркере.
> Каждый этап = отдельный чат с чистым контекстом.
> Переходить к следующему этапу только после верификации текущего.

---

## Этап 0 — Разведка

**Цель**: собрать реальные сигнатуры и структуры кода до начала любых изменений.
Этот этап защищает все последующие от галлюцинаций на основе «предполагаемого» кода.

**Что читаем** (модель открывает и конспектирует):
- `rag-indexer/embedding/base_provider.py` — полностью
- `rag-indexer/embedding/ollama_provider.py` — метод embed и всё что связано
- `rag-indexer/embedding/openai_provider.py` — то же
- `rag-indexer/parser/` — все файлы, особенно текущий чанкер
- `rag-indexer/indexer_worker.py` — метод `run_indexing_task`, как передаётся chunk_size/overlap, как инициализируется embedding_provider
- `rag-backend/app/db/models.py` — только модель `Vault`, её поля
- `rag-backend/app/db/migrations.py` — последняя миграция, формат SQL-скриптов
- `shared_contracts/models.py` — есть ли VaultConfig или похожее

**Результат**: файл `plan-semantic/recon.md` со следующими разделами:
- Точные сигнатуры `EmbeddingProvider`: есть ли `embed_batch`, как выглядит `embed`
- Как сейчас работает чанкер: класс/функция, сигнатура, параметры
- Как `IndexerWorker` получает vault-настройки и вызывает чанкер
- Текущие поля `Vault` в ORM
- Формат последней миграции (шаблон SQL)
- Передаётся ли что-то про vault между сервисами через `shared_contracts`

**Верификация**: `recon.md` написан, все сигнатуры взяты из реального кода (не придуманы).

---

## Этап 1 — `embed_batch` в провайдерах эмбеддингов

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`

**Цель**: добавить метод `embed_batch(texts: list[str]) -> list[list[float]]` в базовый
класс и оба провайдера. Это фундамент для `SemanticChunker` — батчинг предложений
одним запросом вместо N последовательных.

**Задачи**:
1. `base_provider.py` — добавить абстрактный метод `embed_batch`
2. `ollama_provider.py` — реализация: POST `/api/embeddings` с батчем (или N параллельных через `asyncio.gather` если Ollama не поддерживает батч нативно)
3. `openai_provider.py` — реализация: POST `/embeddings` с массивом `input`
4. Тест: `rag-indexer/tests/test_embed_batch.py` — мок HTTP, проверить что батч вызывается один раз

**Результат**:
- Изменены 3 файла в `rag-indexer/embedding/`
- Новый тест-файл
- `embed_batch` работает для обоих провайдеров

**Верификация**: тесты проходят (`pytest rag-indexer/tests/test_embed_batch.py`).

---

## Этап 2 — Миграция БД и ORM

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`

**Цель**: добавить поле `semantic_threshold: float` в `Vault` (единственное новое поле —
стратегия hardcode, хранить не нужно).

**Задачи**:
1. `rag-backend/app/db/models.py` — добавить поле:
   ```python
   semantic_threshold: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
   ```
2. `rag-backend/app/db/migrations.py` — новый SQL-скрипт:
   ```sql
   ALTER TABLE vaults ADD COLUMN IF NOT EXISTS semantic_threshold FLOAT NOT NULL DEFAULT 0.3;
   ```
3. Pydantic-схемы Vault (`VaultCreate`, `VaultUpdate`, `VaultResponse`) — добавить поле
   `semantic_threshold: float = 0.3`
4. `shared_contracts/models.py` — если Vault передаётся между сервисами, добавить поле туда же

**Результат**:
- Vault в БД имеет поле `semantic_threshold`
- API принимает и возвращает это поле
- Существующие записи получают дефолт 0.3 без потери данных

**Верификация**: применить миграцию локально, создать/обновить Vault через API,
проверить что поле сохраняется и возвращается.

---

## Этап 3 — Класс `SemanticChunker`

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`

**Цель**: написать изолированный класс `SemanticChunker` и покрыть его тестами.
Никаких зависимостей от HTTP, БД или FastAPI — только `EmbeddingProvider` и чистая логика.

**Задачи**:
1. Новый файл `rag-indexer/parser/semantic_chunker.py`:

   ```python
   class SemanticChunker:
       MIN_CHUNK_SENTENCES = 2
       MAX_CHUNK_CHARS = 4000

       def __init__(self, embedding_provider: EmbeddingProvider, threshold: float = 0.3):
           ...

       async def split(self, text: str) -> list[str]:
           # 1. split text into sentences
           # 2. embed_batch(sentences)
           # 3. compute cosine distances between neighbours
           # 4. cut where distance > threshold
           # 5. apply MIN/MAX guards
           # 6. return list of chunk strings
           ...
   ```

2. Обновить `rag-indexer/parser/__init__.py` — экспортировать `SemanticChunker`

3. Тесты `rag-indexer/tests/test_semantic_chunker.py`:
   - Мок `EmbeddingProvider.embed_batch` возвращает заранее заданные векторы
   - Тест: два семантически далёких блока → два чанка
   - Тест: один связный текст → один чанк
   - Тест: очень короткий чанк объединяется с соседним (MIN guard)
   - Тест: очень длинный блок разбивается (MAX guard)
   - Тест: пустая строка → пустой список

**Результат**:
- `rag-indexer/parser/semantic_chunker.py` — готов
- Тесты покрывают основные случаи включая edge cases

**Верификация**: `pytest rag-indexer/tests/test_semantic_chunker.py` — все зелёные.

---

## Этап 4 — Интеграция в `IndexerWorker`

**Контекст для чата**: `plan-semantic/context.md` + `plan-semantic/recon.md`
+ реальный код `indexer_worker.py` (вставить в чат целиком или ключевой метод)

**Цель**: подключить `SemanticChunker` в воркер вместо текущего fixed-чанкера.
Стратегия не выбирается — всегда semantic.

**Задачи**:
1. `rag-indexer/indexer_worker.py` — в методе `run_indexing_task`:
   - Убрать вызов fixed-чанкера
   - Заменить на:
     ```python
     chunks = await SemanticChunker(
         self.embedding_provider,
         vault.semantic_threshold
     ).split(text)
     ```
   - Убедиться что `self.embedding_provider` доступен в нужном месте
   - Добавить лог: количество чанков до/после, время выполнения

2. `rag-indexer/app/db_client.py` — убедиться что `semantic_threshold` приходит
   в объекте vault из rag-backend (если vault-объект передаётся через HTTP)

3. Интеграционный тест `rag-indexer/tests/test_indexer_integration.py`:
   - Мок `EmbeddingProvider.embed_batch`
   - Мок `StorageClient`
   - Прогнать `run_indexing_task` на тестовом тексте
   - Проверить что `StorageClient.store_chunks` вызван с правильными чанками

**Результат**:
- Воркер использует `SemanticChunker` для всех документов
- Лог показывает количество чанков и время
- Интеграционный тест проходит

**Верификация**: `pytest rag-indexer/tests/` — все зелёные. Запустить индексацию
тестового документа вручную, проверить чанки в LanceDB.
