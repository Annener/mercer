# Semantic Chunking — Разведка (Этап 0)

> Этот файл создаётся моделью в ходе Этапа 0.
> Содержит реальные сигнатуры из кода — не предполагаемые.

**Статус**: не заполнен

---

## EmbeddingProvider

*(заполнить из `rag-indexer/embedding/base_provider.py`)*

```python
# Сигнатура embed:

# Сигнатура embed_batch (если есть):

# Базовый класс / ABC:
```

---

## OllamaEmbeddingProvider

*(заполнить из `rag-indexer/embedding/ollama_provider.py`)*

```python
# Как вызывает API (endpoint, метод):

# Поддерживает ли батч нативно:
```

---

## OpenAICompatibleProvider

*(заполнить из `rag-indexer/embedding/openai_provider.py`)*

```python
# Как вызывает API:

# Поддерживает ли батч нативно:
```

---

## Текущий чанкер

*(заполнить из `rag-indexer/parser/chunking/generic_chunker.py`)*

```python
# Сигнатура chunk_text:

# Возвращаемый тип:
```

---

## entity_chunker

*(заполнить из `rag-indexer/parser/chunking/entity_chunker.py`)*

```python
# Сигнатура chunk_with_entities:

# Используется ли _entities в вызывающем коде после возврата: ДА / НЕТ
# Где (если да):
```

---

## embedding_enricher

*(заполнить из `rag-indexer/parser/chunking/embedding_enricher.py`)*

```python
# Сигнатура build_embedding_text:

# Сигнатура extract_markdown_headers:
```

---

## preprocess

*(заполнить из `rag-indexer/parser/preprocessing/preprocessor.py`)*

```python
# Сигнатура preprocess:

# Синхронная или асинхронная:

# Идемпотентна (повторный вызов на уже чистом тексте безопасен): ДА / НЕТ
```

---

## IndexerWorker._process_file — точный порядок вызовов

*(заполнить из `rag-indexer/indexer_worker.py`, метод `_process_file`)*

```
1. ...
2. ...
3. ...
# (порядок: parse → merge_pdf_pages → chunk → preprocess → embed → store)
```

**Где именно вставить preprocess(text_for_chunking)**: строка ~???

**Как передаётся provider в _process_file**: параметр / self / ...

**Как vault передаётся**: параметр `vault: dict` / ORM-объект / ...

---

## Vault ORM — поля

*(заполнить из `rag-backend/app/db/models.py`)*

```python
# Все текущие поля Vault:
```

---

## Формат последней миграции

*(заполнить из `rag-backend/app/db/migrations.py`)*

```python
# Шаблон SQL-скрипта (как выглядит последняя миграция):
```

---

## shared_contracts

*(заполнить из `shared_contracts/models.py`)*

```python
# Передаётся ли vault между сервисами: ДА / НЕТ
# Если да — имя модели и поля:
```

---

## db_client.get_vault

*(заполнить из `rag-indexer/app/db_client.py`)*

```python
# Что возвращает get_vault: dict / ORM / dataclass
# Нужно ли что-то добавлять для semantic_threshold:
```

---

## Выводы для реализации

*(заполнить после чтения всех файлов)*

- `embed_batch` уже есть: ДА / НЕТ → если НЕТ, Этап 1 обязателен
- `_entities` используется после возврата: ДА / НЕТ → если НЕТ, ветку можно просто убрать
- vault передаётся как: dict / ORM → способ обращения к `semantic_threshold`
- preprocess синхронная: ДА / НЕТ → нужен ли `asyncio.to_thread`
