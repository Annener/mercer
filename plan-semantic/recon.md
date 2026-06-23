# Semantic Chunking — Разведка (Этап 0)

> Этот файл создаётся моделью в ходе Этапа 0.
> Содержит реальные сигнатуры из кода — не предполагаемые.

**Статус**: ✅ заполнен (23.06.2026)

---

## EmbeddingProvider

*файл: `rag-indexer/embedding/base_provider.py`*

```python
# Базовый класс / ABC:
class EmbeddingProvider(ABC):

# Сигнатура embed:
@abstractmethod
async def embed(self, texts: list[str]) -> list[list[float]]:
    """Return one vector per input text, using [] for per-text failures."""

# Абстрактное свойство:
@property
@abstractmethod
def dimensions(self) -> int:
    """Return the expected embedding vector size."""

# embed_batch: ОТСУТСТВУЕТ — Этап 1 обязателен
```

---

## OllamaEmbeddingProvider

*файл: `rag-indexer/embedding/ollama_provider.py`*

```python
class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url, model_name, dimensions, timeout=30, max_retries=3)

# Как вызывает API:
# POST {base_url}/api/embeddings
# json={"model": self.model_name, "prompt": text}

# Текущая реализация embed: параллельные запросы через asyncio.Semaphore(_OLLAMA_CONCURRENCY=4)
# Каждый текст — отдельный HTTP-запрос к /api/embeddings (prompt: str, не list)
# Нативного batch-endpoint НЕТ → embed_batch нужно реализовать через asyncio.gather

# Вспомогательный метод:
async def _embed_one(self, client: httpx.AsyncClient, text: str) -> list[float]
```

---

## OpenAICompatibleProvider

*файл: `rag-indexer/embedding/openai_provider.py`*

```python
class OpenAICompatibleProvider(EmbeddingProvider):
    def __init__(self, base_url, model_name, dimensions, api_key, timeout=30, max_retries=3)

# Как вызывает API:
# POST {base_url}/embeddings
# json={"model": self.model_name, "input": text}
# headers={"Authorization": f"Bearer {self.api_key}"}

# Текущая реализация embed: ПОСЛЕДОВАТЕЛЬНО (не параллельно)
# for text in texts: await self._embed_one(client, text)
# OpenAI API поддерживает "input": list[str] (настоящий батч)
# → embed_batch может отправить весь список в один запрос

# Вспомогательный метод:
async def _embed_one(self, client: httpx.AsyncClient, text: str) -> list[float]
```

---

## Текущий чанкер (generic)

*файл: `rag-indexer/parser/chunking/generic_chunker.py`*

```python
# Сигнатура chunk_text:
def chunk_text(
    text: str,
    document_id: str,
    vault_id: str,
    chunk_size: int = 1600,
    overlap: int = 64,
    metadata: dict | None = None,
) -> list[ChunkRecord]:

# Возвращаемый тип: list[ChunkRecord]
# Синхронная (не async)

# Логика:
# 1. Делит по Markdown-заголовкам regex: r'^(#{1,6}\s+.+)$'
# 2. Секция ≤ chunk_size → одним куском
# 3. Секция > chunk_size → скользящее окно с overlap
# 4. Заполняет metadata["word_start"] и metadata["word_end"] (в словах)
```

---

## entity_chunker

*файл: `rag-indexer/parser/chunking/entity_chunker.py`*

```python
# Сигнатура chunk_with_entities:
def chunk_with_entities(
    text: str,
    document_id: str,
    vault_id: str,
    chunk_size: int = 1600,
    overlap: int = 64,
    metadata: dict | None = None,
) -> tuple[list[ChunkRecord], list[EntityRecord]]:

# _entities используется после возврата: НЕТ
# В indexer_worker.py строка 331:
#   chunks, _entities = await asyncio.to_thread(chunk_with_entities, ...)
# _entities нигде далее не используется — можно безболезненно убрать ветку
```

---

## embedding_enricher

*файл: `rag-indexer/parser/chunking/embedding_enricher.py`*

```python
# Сигнатура build_embedding_text:
def build_embedding_text(
    chunk_text: str,
    source_path: str,
    headers: dict[str, Any] | None = None,
    content_type: str | None = None,
) -> str:
# Возвращает строку вида:
# "Документ: path\nРаздел: ...\nПодраздел: ...\nТип: ...\n[текст]"
# Вызывается ПОСЛЕ чанкинга, на финальных чанках — схему не трогать

# Сигнатура extract_markdown_headers:
def extract_markdown_headers(chunk_text: str) -> dict[str, str]:
# Извлекает H1/H2/H3 из первой строки чанка
# Возвращает: {"h1": "Title", "section": "Title"} или {"h2": ...} или {}
```

---

## preprocess

*файл: `rag-indexer/parser/preprocessing/preprocessor.py`*

```python
# Сигнатура:
def preprocess(text: str, source_hint: str = "") -> str:

# Синхронная (не async)
# В indexer_worker вызывается через: await asyncio.to_thread(preprocess, ...)

# Идемпотентна (повторный вызов на уже чистом тексте безопасен): ДА
# (NFC + замены символов + пробельная нормализация — повторный вызов не ломает текст)

# ВАЖНО: сейчас вызывается ПОСЛЕ чанкинга, на каждом чанке отдельно (строка 361)
# Для SemanticChunker нужно вызвать preprocess(text_for_chunking) ДО чанкинга
# — это соответствует архитектурному решению из context.md
```

---

## IndexerWorker._process_file — точный порядок вызовов

*файл: `rag-indexer/indexer_worker.py`, строки ~258–490*

```
1. _parse_file_with_progress()           → parsed (dict с "pages" или "text")
2. merge_pdf_pages(parsed["pages"], ...) → text_for_chunking, page_offsets, placed_headings  [только PDF]
3. text_for_chunking = parsed["text"]                                                          [MD]
4. (проверка пустого текста → return)
5. chunk_with_entities(text_for_chunking, ...) ИЛИ chunk_text(...)     ← ЗДЕСЬ будет SemanticChunker
6. (проверка пустых чанков → return)
7. for chunk in chunks:
       chunk.text = strip_page_markers(chunk.text)
       chunk.text = await asyncio.to_thread(preprocess, chunk.text, ...)   ← сейчас ПОСЛЕ чанкинга
8. (фильтрация пустых чанков после preprocess)
9. _assign_page_numbers_and_headers(chunks, page_offsets, placed_headings)  [только PDF]
10. for chunk in chunks:
        headers = extract_markdown_headers(chunk.text)   [только MD, если нет headers]
        embedding_text = build_embedding_text(...)
        chunk.metadata["embedding_text"] = embedding_text
11. _embed_chunks(chunks, embedding_model, provider, ...)   ← вызывает provider.embed([text]) в цикле
12. upsert_with_retry(UpsertRequest(...))
13. db_client.update_document_status(...)
```

**Где вставить preprocess(text_for_chunking) перед SemanticChunker**:
После шага 3/4 (после получения text_for_chunking, перед вызовом чанкера) — строка ~325.
Текущий per-chunk preprocess (шаг 7) при этом можно убрать или оставить как NO-OP (идемпотентен).

**Как передаётся provider**: параметр `provider: EmbeddingProvider` в `_process_file`

**Как vault передаётся**: параметр `vault: dict[str, Any]` — результат `db_client.get_vault()` (возвращает `dict(row)`)
→ обращение: `vault.get("semantic_threshold")` или `vault.get("semantic_threshold", 0.3)`

---

## Vault ORM — поля

*файл: `rag-backend/app/db/models.py`*

```python
class Vault(Base):
    __tablename__ = "vaults"

    id: Mapped[uuid.UUID]           # PK
    vault_id: Mapped[str]           # уникальный строковый ID
    domain_id: Mapped[str | None]   # FK → domains
    display_name: Mapped[str | None]
    enabled: Mapped[bool]           # default True
    embedding_model_id: Mapped[str | None]
    expected_dimensions: Mapped[int | None]
    chunk_size: Mapped[int | None]
    overlap: Mapped[int | None]
    entity_aware_mode: Mapped[bool | None]
    binding_status: Mapped[str]     # "unbound" / "indexing" / "bound" / "error"
    chunk_count: Mapped[int]        # default 0
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    documents: list[Document]       # relationship

# semantic_threshold: ОТСУТСТВУЕТ — Этап 2 обязателен
```

---

## Формат миграций

*файл: `rag-backend/app/db/migrations.py`*

```python
# migrations.py — НЕ содержит SQL-скриптов!
# Это просто Alembic runner:
async def run_migrations() -> None:
    await asyncio.to_thread(_upgrade_head)

def _upgrade_head() -> None:
    config = Config("/app/alembic.ini")
    command.upgrade(config, "head")
```

*Реальные миграции: `rag-backend/migrations/versions/`*

Последняя: `0021_remove_dead_platform_settings.py` (ревизия от 22.06.2026)
Формат — стандартный Alembic:
```python
revision = "0022_add_semantic_threshold"          # следующий номер
down_revision = "0021_remove_dead_platform_settings"

def upgrade() -> None:
    op.add_column("vaults", sa.Column("semantic_threshold", sa.Float(), nullable=True))
    op.execute("UPDATE vaults SET semantic_threshold = 0.3 WHERE semantic_threshold IS NULL")
    op.alter_column("vaults", "semantic_threshold", nullable=False, server_default="0.3")

def downgrade() -> None:
    op.drop_column("vaults", "semantic_threshold")
```

**Важно**: `migrations.py` просто запускает `alembic upgrade head`.
Новая миграция добавляется как файл в `rag-backend/migrations/versions/`.

---

## shared_contracts / VaultRead / VaultCreate

*файл: `shared_contracts/models.py`*

```python
# vault передаётся между сервисами: ДА
# Модели: VaultRead, VaultCreate, VaultUpdate

class VaultRead(ORMModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    enabled: bool = True
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    binding_status: Literal["unbound", "indexing", "bound", "error"] = "unbound"
    chunk_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

# semantic_threshold: ОТСУТСТВУЕТ → нужно добавить в VaultRead, VaultCreate, VaultUpdate
```

---

## db_client.get_vault

*файл: `rag-indexer/app/db_client.py`*

```python
async def get_vault(self, vault_id: str) -> dict[str, Any] | None:
    row = await self._fetchrow("SELECT * FROM vaults WHERE vault_id = $1", vault_id)
    return dict(row) if row is not None else None

# Возвращает: dict[str, Any] — плоский словарь из asyncpg Row
# SELECT * → после добавления колонки semantic_threshold в БД
#            get_vault вернёт её автоматически без изменения кода db_client
# Обращение в indexer_worker: vault.get("semantic_threshold", 0.3)
```

---

## _embed_chunks — текущая реализация

*файл: `rag-indexer/indexer_worker.py`, строка ~498*

```python
# Цикл по чанкам: для каждого вызывает provider.embed([embedding_text])
# Т.е. один HTTP-запрос на чанк — неэффективно

# После реализации embed_batch (Этап 1):
# result = await provider.embed_batch([chunk.metadata["embedding_text"] for chunk in chunks])
# Один вызов на весь документ — согласно архитектурному решению из context.md
```

---

## Выводы для реализации

| Вопрос | Ответ | Следствие |
|--------|-------|-----------|
| `embed_batch` уже есть? | **НЕТ** | Этап 1 обязателен |
| `_entities` используется после возврата? | **НЕТ** (переменная `_entities`) | Ветку `entity_aware` можно просто заменить |
| vault передаётся как? | **dict** (asyncpg Row → dict) | `vault.get("semantic_threshold", 0.3)` |
| preprocess синхронная? | **ДА** | Нужен `asyncio.to_thread` для CPU-bound вызова |
| semantic_threshold в ORM? | **ОТСУТСТВУЕТ** | Этап 2: добавить колонку + миграцию |
| semantic_threshold в shared_contracts? | **ОТСУТСТВУЕТ** | Этап 2: добавить в VaultRead/Create/Update |
| Миграционный механизм? | **Alembic** (файлы в `migrations/versions/`) | Добавить `0022_add_semantic_threshold.py` |
| word_start заполняется в generic_chunker? | **ДА** (`metadata["word_start"]`) | SemanticChunker должен делать то же самое |
| LanceDB схема меняется? | **НЕТ** | word_start в metadata — не в основной схеме |
| preprocess вызывается ДО или ПОСЛЕ чанкинга? | Сейчас **ПОСЛЕ** (на каждом чанке) | Для SemanticChunker вызвать **ДО** на весь текст |
