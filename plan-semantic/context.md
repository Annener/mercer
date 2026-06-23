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

В таблице `Vault` появляются два новых поля (или в `VaultConfig` / `PlatformSetting`):

```
chunking_strategy: str  — "fixed" (дефолт, текущее поведение) | "semantic"
semantic_threshold: float  — порог косинусного расстояния, дефолт ~0.3
```

> **Замечание по хранению**: паттерн проекта — настройки хранятся в PostgreSQL.
> `Vault` уже содержит `chunk_size` и `overlap`. Новые поля добавляются туда же,
> либо в отдельную `VaultConfig`-таблицу, если такая будет создана.
> Миграция — через `rag-backend/app/db/migrations.py` (кастомные SQL-скрипты, НЕ Alembic).

### Новый класс: SemanticChunker

Файл: `rag-indexer/parser/semantic_chunker.py`

```python
class SemanticChunker:
    def __init__(self, embedding_provider: EmbeddingProvider, threshold: float = 0.3):
        ...

    async def split(self, text: str) -> list[str]:
        """
        Принимает сырой текст документа.
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

Текущий поток:
```
text → Parser.split_into_chunks(chunk_size, overlap) → list[str] → embed → store
```

Новый поток при `chunking_strategy == "semantic"`:
```
text → SemanticChunker(embedding_provider, threshold).split(text) → list[str] → embed → store
```

Логика выбора стратегии — в `IndexerWorker.run_indexing_task()`,
после получения текста и до эмбеддинга:

```python
if vault.chunking_strategy == "semantic":
    chunks = await SemanticChunker(self.embedding_provider, vault.semantic_threshold).split(text)
else:
    chunks = parser.split_into_chunks(text, vault.chunk_size, vault.overlap)
```

### API

В эндпоинтах управления Vault (`rag-backend/app/api/vaults.py` или аналог)
появляются поля `chunking_strategy` и `semantic_threshold` в схемах
`VaultCreate` / `VaultUpdate` (Pydantic v2, `rag-backend/app/...`).

Фронтенд отображает выбор стратегии в настройках Vault (select + число для порога).

---

## Важные технические моменты

### Double-embedding при индексации

При `chunking_strategy == "semantic"` эмбеддинги вычисляются **дважды**:
1. При `SemanticChunker.split()` — по одному эмбеддингу на **предложение** (для нахождения границ).
2. При обычном пути индексации — по одному эмбеддингу на **чанк** (для хранения в LanceDB).

Это нормально и ожидаемо. Первый набор эмбеддингов временный, не хранится.
Однако индексация замедлится примерно в 2–5× для крупных документов.

**Оптимизация (опционально)**: после определения границ переиспользовать
mean pooling предложений чанка вместо повторного вызова к модели.
Но это усложняет код — сначала сделать наивно, замерить, потом оптимизировать.

### Батчинг эмбеддингов предложений

Не вызывать `embedding_provider.embed(sentence)` в цикле по одному.
Батчить все предложения документа одним запросом:

```python
# Хорошо
embeddings = await provider.embed_batch(sentences)

# Плохо
embeddings = [await provider.embed(s) for s in sentences]
```

Проверить, поддерживает ли `EmbeddingProvider.embed_batch()` уже существует в
`rag-indexer/embedding/base_provider.py`. Если нет — добавить.

### LanceDB схема не меняется

Схема записи в LanceDB (`chunk_id`, `document_id`, `vault_id`, `text`, `vector`, `metadata`)
остаётся без изменений. Семантические чанки хранятся точно так же, как фиксированные.

`VaultBinding` (`embedding_model_id` + `expected_dimensions`) не затрагивается —
та же модель эмбеддингов, те же dimensions.

> ⚠️ Если когда-либо потребуется сменить эмбеддинг-модель при переходе на semantic chunking —
> таблицу LanceDB для vault нужно будет пересоздать (LanceDB не позволяет менять dimensions).

### Пересчёт при смене стратегии

Если пользователь меняет `chunking_strategy` с `fixed` на `semantic` у уже
проиндексированного Vault — все существующие чанки в LanceDB **устаревают**.
Нужно триггернуть повторную индексацию всех документов Vault.

Механизм уже есть: `IndexerWorker` умеет переиндексировать. Нужно только
предупредить пользователя в UI и вызвать соответствующий endpoint.

### Порог `semantic_threshold`

Рекомендуемый дефолт: **0.3** (косинусное расстояние; соответствует ~0.7 косинусному сходству).
Диапазон для тонкой настройки: 0.15–0.5.

- Меньше порог → меньше разрывов → крупные чанки (близко к fixed с большим chunk_size)
- Больше порог → больше разрывов → мелкие чанки (рискует разорвать связанные предложения)

### Мин./макс. размер чанка (защитные ограничения)

Чистый semantic chunking может создавать чанки из 1 предложения или же
гигантские блоки на весь раздел. Рекомендуется добавить ограничения:

```python
MIN_CHUNK_SENTENCES = 2   # объединить с соседним, если чанк слишком мал
MAX_CHUNK_CHARS = 4000    # принудительно разбить, если чанк слишком велик
```

Значения настраиваемые или хардкод-константы в `semantic_chunker.py`.

---

## Файловая карта изменений

| Файл | Тип изменения | Описание |
|---|---|---|
| `rag-indexer/parser/semantic_chunker.py` | **Новый файл** | Класс `SemanticChunker` |
| `rag-indexer/parser/__init__.py` | Изменение | Экспортировать `SemanticChunker` |
| `rag-indexer/embedding/base_provider.py` | Изменение | Добавить `embed_batch()` если нет |
| `rag-indexer/indexer_worker.py` | Изменение | Выбор стратегии чанкинга |
| `rag-backend/app/db/models.py` | Изменение | Добавить поля в Vault |
| `rag-backend/app/db/migrations.py` | Изменение | SQL ALTER TABLE для новых полей |
| `rag-backend/app/api/vaults.py` (или аналог) | Изменение | Pydantic-схемы Vault |
| `rag-indexer/app/db_client.py` | Изменение | Передавать новые поля Vault в воркер |
| `shared_contracts/models.py` | Возможно | Если VaultConfig передаётся между сервисами |
| `rag-indexer/tests/` | **Новые файлы** | Тесты `SemanticChunker` |

---

## Что НЕ меняется

- Схема LanceDB и `lancedb_store.py` — без изменений.
- `retrieval.py` в rag-backend — без изменений. Ретривал работает одинаково для
  любых чанков.
- `pdf-sidecar` — без изменений.
- Пайплайны и `pipeline_executor.py` — без изменений.
- `format_context()` и нумерация источников на фронтенде — без изменений.
- `reranker.py` — работает поверх любых чанков.

---

## Зависимости

Новые Python-зависимости в `rag-indexer/requirements.txt`:

| Пакет | Зачем | Альтернатива |
|---|---|---|
| `nltk` | `sent_tokenize` — разбивка на предложения | Простой regex-split |
| `numpy` | косинусное расстояние (`np.dot`) | `scipy.spatial.distance.cosine` |

`numpy` скорее всего уже есть (используется в embedding-провайдерах).
`nltk` — минимальная зависимость, нужен только `punkt` tokenizer (загружается один раз).

Если хочется без nltk — достаточно:
```python
import re
sentences = re.split(r'(?<=[.!?])\s+', text)
```

---

## Паттерны и соглашения проекта (напоминание)

- Весь async-код через `async def` + `await`, httpx для HTTP-клиентов.
- Новые настройки Vault — через `rag-backend/app/db/migrations.py` (кастомный SQL, не Alembic).
- ID воркеров и воркер-сущностей — строковые slugs или UUID согласно таблице в `conventions.md`.
- Логирование — `logging.getLogger(__name__)`, уровень INFO/DEBUG.
- Провайдеры эмбеддингов инициализируются через фабрику `embedding/__init__.py`.
- Все Pydantic-схемы — v2 (model_config, `from_attributes=True`).

---

## Ссылки на ключевые файлы проекта

- Воркер индексации: `rag-indexer/indexer_worker.py`
- Существующие парсеры: `rag-indexer/parser/`
- Базовый провайдер эмбеддингов: `rag-indexer/embedding/base_provider.py`
- ORM-модели: `rag-backend/app/db/models.py`
- Миграции: `rag-backend/app/db/migrations.py`
- Общие контракты: `shared_contracts/models.py`
- Конвенции кода: `context/conventions.md`
