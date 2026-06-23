# Semantic Chunking — Контекстный документ для реализации

## Что такое фича

Semantic Chunking — альтернативная стратегия разбиения документа на чанки,
при которой границы чанков определяются не фиксированным количеством символов/токенов,
а **семантическими разрывами** в тексте.

Алгоритм:
1. Разбить документ на предложения (или абзацы).
2. Для каждого предложения вычислить эмбеддинг.
3. Вычислить косинусное расстояние между *соседними* эмбеддингами.
4. Там, где расстояние превышает порог (`semantic_threshold`), — граница чанка.
5. Объединить предложения внутри одного семантического блока в итоговый чанк.

Результат: чанки с более связным смыслом, лучшее качество ретривала, меньше
"разорванных" смысловых единиц на границах.

---

## Итоговый вид фичи

### Настройки Vault (PostgreSQL)

В таблице `Vault` появляется одно новое поле:

```
semantic_threshold: float  — порог косинусного расстояния, дефолт ~0.3
```

> **Стратегия hardcode**: `chunking_strategy` как поле в БД не нужно — semantic chunking
> включается как единственный режим (текущий fixed-чанкер убирается из основного пути).
> Миграция — через `rag-backend/app/db/migrations.py` (кастомные SQL-скрипты, НЕ Alembic).

### Новый класс: SemanticChunker

Файл: `rag-indexer/parser/semantic_chunker.py`

```python
class SemanticChunker:
    MIN_CHUNK_SENTENCES = 2
    MAX_CHUNK_CHARS = 4000

    def __init__(self, embedding_provider: EmbeddingProvider, threshold: float = 0.3):
        ...

    async def split(self, text: str) -> list[str]:
        """
        Принимает ПРЕДВАРИТЕЛЬНО ОЧИЩЕННЫЙ текст документа (после preprocess()).
        Возвращает список чанков по семантическим границам.
        """
        ...
```

**Зависимость**: `EmbeddingProvider` (уже существует в `rag-indexer/embedding/`).
Чанкер должен получать экземпляр провайдера — он передаётся из `IndexerWorker`.

**Разбивка на предложения**: рекомендуется `nltk.sent_tokenize` или простой split по
`\n\n` + `. ` (без тяжёлых NLP-зависимостей). В README зафиксировать выбор.

### Изменения в IndexerWorker

Файл: `rag-indexer/indexer_worker.py`

**Текущий поток** (fixed chunking):
```
parse
  → merge_pdf_pages (если PDF)
  → chunk_with_entities / chunk_text  ← чанкинг сырого текста
  → strip_page_markers + preprocess(каждый чанк)  ← очистка ПОСЛЕ чанкинга
  → build_embedding_text(каждый чанк)
  → embed(каждый чанк)
  → store
```

**Новый поток** (semantic chunking):
```
parse
  → merge_pdf_pages (если PDF)
  → preprocess(text_for_chunking)  ← НОВАЯ ВСТАВКА: очистка всего текста ДО чанкинга
  → SemanticChunker.split(cleaned_text)  ← semantic split
  → strip_page_markers + preprocess(каждый чанк)  ← остаётся, idempotent
  → build_embedding_text(каждый чанк)
  → embed(каждый чанк)
  → store
```

> ⚠️ **Критично**: `preprocess()` в V3.0 документально вызывается «на каждом чанке
> после чанкинга» (`preprocessor.py`, комментарий в коде). Если `SemanticChunker`
> получит сырой текст с PDF-артефактами (битые символы, мягкие переносы, U+FFFD),
> косинусное расстояние между предложениями будет зашумлено. Поэтому нужен
> `preprocess(text_for_chunking)` ДО передачи в `SemanticChunker`.
> `preprocess` идемпотентна — повторный вызов на чанке ничего не сломает.

Логика в `_process_file()`, после получения `text_for_chunking` и до чанкинга:

```python
# НОВОЕ: pre-clean перед semantic split
cleaned_for_chunking = preprocess(text_for_chunking, source_hint=relative_path)

chunks = await SemanticChunker(
    provider,
    vault.get("semantic_threshold", 0.3)
).split(cleaned_for_chunking)
```

### API

В эндпоинтах управления Vault (`rag-backend/app/api/vaults.py` или аналог)
появляется поле `semantic_threshold` в схемах `VaultCreate` / `VaultUpdate` / `VaultResponse`
(Pydantic v2, `from_attributes=True`).

Фронтенд отображает числовое поле порога в настройках Vault.

---

## Важные технические моменты

### preprocess() — порядок вызова (критично)

`preprocessor.py` содержит функцию `preprocess(text, source_hint)` — глубокую очистку:
замена проблемных Unicode (U+FFFD, U+00AD мягкие переносы, тире, спецсимволы PDF),
нормализация пробелов, удаление управляющих символов.

В текущем коде вызывается **на каждом чанке после чанкинга** (строка ~350 в `indexer_worker.py`):
```python
for idx, chunk in enumerate(chunks):
    cleaned = await asyncio.to_thread(preprocess, chunk.text, source_hint)
    chunk.text = cleaned
```

Для `SemanticChunker` необходимо **дополнительно** вызвать `preprocess` на всём
`text_for_chunking` перед передачей в чанкер. Без этого cosine similarity между
предложениями будет зашумлена артефактами PDF.

Итого `preprocess` вызывается дважды — это нормально, функция идемпотентна.

### embedding_text vs chunk.text — два разных поля

После чанкинга воркер строит обогащённый текст для эмбеддинга:
```python
embedding_text = build_embedding_text(
    chunk_text=chunk.text,
    source_path=source_path,
    headers=headers,
    content_type=chunk.metadata.get("content_type"),
)
chunk.metadata["embedding_text"] = embedding_text
```

`build_embedding_text()` из `embedding_enricher.py` добавляет заголовки документа,
путь к файлу, тип контента — для улучшения качества финальных эмбеддингов.

**Важно для SemanticChunker**: при разведочных эмбеддингах предложений (шаг нахождения
границ) использовать **чистый текст предложений**, без обёрток `build_embedding_text`.
Это даст чистый семантический сигнал. Финальные чанки после `split()` проходят через
`build_embedding_text` как обычно — эту логику в воркере не трогать.

### extract_markdown_headers() — переиспользовать

Функция уже есть в `embedding_enricher.py` и уже используется в воркере для MD-файлов:
```python
if not is_pdf and not headers:
    headers = extract_markdown_headers(chunk.text)
```

`SemanticChunker` может использовать её для определения заголовочных границ:
заголовки (`# Заголовок`, `## Раздел`) — это всегда жёсткие границы чанков,
независимо от косинусного расстояния. Переиспользовать, не писать свой regex.

### entity_aware ветка

В воркере сейчас два пути чанкинга:
```python
if entity_aware:
    chunks, _entities = chunk_with_entities(...)
else:
    chunks = chunk_text(...)
```

После введения `SemanticChunker` оба пути заменяются единственным:
```python
chunks = await SemanticChunker(provider, threshold).split(cleaned_for_chunking)
```

Entity extraction в `entity_chunker.py` — это не отдельная логика разбивки,
a NER-обогащение метаданных. Нужно проверить при разведке (Этап 0), используется ли
результат `_entities` где-либо после возврата из `chunk_with_entities`.
Если нет — просто удаляем ветку. Если используется — сохранить NER как отдельный шаг
после `SemanticChunker.split()`.

### BM25 / FTS — изменения не нужны, качество улучшится

`lancedb_store.py` строит FTS-индекс по колонке `text` при старте сервиса:
```python
table.create_fts_index("text", replace=True)
```

Схема записи в LanceDB (`chunk_id`, `document_id`, `text`, `vector`, `metadata`)
**не меняется**. `SemanticChunker` меняет только границы чанков, но не структуру записи.

BM25 при semantic chunking работает **лучше**: смысловые границы снижают вероятность
разрыва термина между двумя чанками, характерного для fixed-size cut.

Hybrid search (`retrieval.py`) — не трогать, он не знает о способе чанкинга.

### Double-embedding при индексации

При semantic chunking эмбеддинги вычисляются **дважды**:
1. `SemanticChunker.split()` — батч эмбеддингов предложений (временные, для границ).
2. Основной путь воркера — эмбеддинг каждого финального чанка (хранится в LanceDB).

Это нормально и ожидаемо. Индексация замедлится ~2–5× для крупных документов.

**Оптимизация (опционально, не в первой итерации)**: mean pooling токенов предложений
чанка вместо повторного embed-вызова. Усложняет код — сначала наивно, потом профилировать.

### Батчинг эмбеддингов предложений

Не вызывать `embedding_provider.embed(sentence)` в цикле — только батч:

```python
# Хорошо
embeddings = await provider.embed_batch(sentences)  # один запрос

# Плохо
embeddings = [await provider.embed(s) for s in sentences]  # N запросов
```

Проверить при разведке (Этап 0): есть ли `embed_batch()` в `base_provider.py`.
Если нет — добавить как первый шаг (Этап 1 плана).

### LanceDB схема не меняется

Схема записи (`chunk_id`, `document_id`, `vault_id`, `text`, `vector`, `metadata`)
остаётся без изменений. `VaultBinding` (`embedding_model_id` + `expected_dimensions`)
не затрагивается — та же модель, те же dimensions.

> ⚠️ Если когда-либо потребуется сменить эмбеддинг-модель вместе с semantic chunking —
> таблицу LanceDB для vault нужно будет пересоздать (LanceDB не позволяет менять dimensions).

### Пересчёт при смене порога

Если пользователь меняет `semantic_threshold` у уже проиндексированного Vault —
старые чанки технически не устаревают, но будут несогласованными с новыми.
Рекомендуется предупреждать в UI и предлагать force-reindex.
Механизм уже есть в воркере.

### Порог `semantic_threshold`

Рекомендуемый дефолт: **0.3** (косинусное расстояние; ≈0.7 косинусного сходства).
Диапазон: 0.15–0.5.

- Меньше → крупные чанки (мало разрывов)
- Больше → мелкие чанки (много разрывов, риск разорвать связанные предложения)

### Мин./макс. размер чанка (защитные ограничения)

```python
MIN_CHUNK_SENTENCES = 2   # объединить с соседним, если чанк слишком мал
MAX_CHUNK_CHARS = 4000    # принудительно разбить, если чанк слишком велик
```

---

## Файловая карта изменений

| Файл | Тип изменения | Описание |
|---|---|---|
| `rag-indexer/parser/semantic_chunker.py` | **Новый файл** | Класс `SemanticChunker` |
| `rag-indexer/parser/__init__.py` | Изменение | Экспортировать `SemanticChunker` |
| `rag-indexer/embedding/base_provider.py` | Изменение | Добавить `embed_batch()` если нет |
| `rag-indexer/indexer_worker.py` | Изменение | 1) `preprocess(text_for_chunking)` до чанкинга; 2) замена fixed/entity-chunker на `SemanticChunker` |
| `rag-backend/app/db/models.py` | Изменение | Добавить `semantic_threshold: float = 0.3` в Vault |
| `rag-backend/app/db/migrations.py` | Изменение | SQL ALTER TABLE для `semantic_threshold` |
| `rag-backend/app/api/vaults.py` (или аналог) | Изменение | Pydantic-схемы Vault |
| `rag-indexer/app/db_client.py` | Изменение | Передавать `semantic_threshold` из vault в воркер |
| `shared_contracts/models.py` | Возможно | Если VaultConfig передаётся между сервисами |
| `rag-indexer/tests/` | **Новые файлы** | Тесты `SemanticChunker` и `embed_batch` |

---

## Что НЕ меняется

- `lancedb_store.py` и схема LanceDB — без изменений.
- `retrieval.py` — без изменений. Ретривал работает одинаково для любых чанков.
- `pdf-sidecar` и `pdf_parser.py` — без изменений.
- `pipeline_executor.py` — без изменений.
- `format_context()` и нумерация источников на фронтенде — без изменений.
- `reranker.py` — работает поверх любых чанков.
- FTS/BM25 гибридный поиск — без изменений, качество только улучшится.
- `pdf_page_merger.py`, `merge_pdf_pages()` — без изменений, вызывается до чанкинга как сейчас.
- `build_embedding_text()` в `embedding_enricher.py` — без изменений, вызывается на финальных чанках как сейчас.

---

## Зависимости

Новые Python-зависимости в `rag-indexer/requirements.txt`:

| Пакет | Зачем | Альтернатива |
|---|---|---|
| `nltk` | `sent_tokenize` — разбивка на предложения | Простой regex-split |
| `numpy` | косинусное расстояние (`np.dot`) | `scipy.spatial.distance.cosine` |

`numpy` скорее всего уже есть. `nltk` — минимальная зависимость, нужен только `punkt`
tokenizer (загружается один раз при старте контейнера).

Если хочется без nltk — достаточно:
```python
import re
sentences = re.split(r'(?<=[.!?])\s+', text)
```

---

## Паттерны и соглашения проекта (напоминание)

- Весь async-код через `async def` + `await`, httpx для HTTP-клиентов.
- CPU-bound операции (текстовый split, cosine distance) — через `asyncio.to_thread`.
- Новые настройки Vault — через `rag-backend/app/db/migrations.py` (кастомный SQL, не Alembic).
- Логирование — `logging.getLogger(__name__)`, уровень INFO/DEBUG.
- Провайдеры эмбеддингов инициализируются через фабрику в воркере (`_build_provider`).
- Все Pydantic-схемы — v2 (`model_config`, `from_attributes=True`).
- `preprocess()` из `parser/preprocessing/preprocessor.py` — публичная функция, не класс.

---

## Ссылки на ключевые файлы проекта

- Воркер индексации: `rag-indexer/indexer_worker.py`
- Существующий generic-чанкер: `rag-indexer/parser/chunking/generic_chunker.py`
- Entity-чанкер: `rag-indexer/parser/chunking/entity_chunker.py`
- Препроцессор: `rag-indexer/parser/preprocessing/preprocessor.py`
- Embedding enricher (build_embedding_text, extract_markdown_headers): `rag-indexer/parser/chunking/embedding_enricher.py`
- Базовый провайдер эмбеддингов: `rag-indexer/embedding/base_provider.py`
- ORM-модели: `rag-backend/app/db/models.py`
- Миграции: `rag-backend/app/db/migrations.py`
- LanceDB store (FTS): `db-api-server/storage/lancedb_store.py`
- Общие контракты: `shared_contracts/models.py`
- Конвенции кода: `context/conventions.md`
