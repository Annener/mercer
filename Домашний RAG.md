# RAG Platform — Project Context (Единый источник правды V3.0)

## 📋 Обзор проекта

Локальная multi-domain RAG (Retrieval-Augmented Generation) платформа для работы с базами знаний. Поддерживает несколько доменов (D&D, Work, etc.), инкрементальную индексацию документов, LLM-driven агентный цикл, streaming чат, clarification FSM, hot-reload pipelines и полноценный веб-интерфейс с domain-based изоляцией.

**Статус:** V3.0 PDF-Aware Semantic Chunking & Dual-Text Retrieval Architecture.
- ✅ Бэкенд-часть V3.0 завершена (Фазы 1 и 2 ТЗ)
- ⚠️ Фронтенд прогресс-бар (Фаза 3) — откатан, требует новой реализации
- 🔜 Подготовка к production-тестированию

Название продукта в UI: `MattMercer`

## Стек технологий

- **Backend:** Python 3.13+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, LanceDB
- **Indexer:** FastAPI, pdfminer.six (с кастомным heading-aware converter), pytesseract (OCR fallback), httpx
- **Frontend:** Vanilla HTML/CSS/JS (без фреймворков), markdown rendering (marked.js + DOMPurify + highlight.js)
- **Infrastructure:** Docker Compose, multi-stage builds, async workflows

## 🏗️ Архитектура

### Сервисы (4 контейнера)

**`rag-backend` (порт 8000)** — основной API + Web UI
- Chat API (создание чатов, отправка сообщений, SSE streaming, фильтрация по домену)
- Config API (`/config/domains`, `/config/vaults`)
- DB Management API (управление документами, multi-vault текстовый поиск, reindex/detach)
- Clarification FSM + LLM-driven Agent Planner (`LLMRAGPlanner`)
- Pipeline Framework (hot-reload исполняемых блоков)
- Domain Layer (загрузка промптов из YAML через `DomainRegistry`)
- Generation Provider (OpenAI-compatible LLM, поддержка `json_object` mode)
- Retrieval: `retrieve` (single-vault) + `retrieve_multi_vault` (параллельный поиск по домену)
- Раздача статического UI через `StaticFiles` + `GET /`

**`rag-indexer` (порт 9000)** — индексация документов
- Сканирование vault (`.md` и `.pdf`)
- **PDF-Aware пайплайн V3.0:** постраничный парсинг через pdfminer с heading detection (анализ размера шрифта), склейка страниц с удалением колонтитулов, построение псевдо-markdown структуры
- **Markdown-пайплайн V3.0:** цельное чтение с сохранением frontmatter и `#`-заголовков
- **Препроцессинг после чанкинга** (на каждом чанке отдельно) с глобальным кэшем suspicious Unicode-символов
- Heading-aware чанкинг с настраиваемым `chunk_size` и `overlap`
- Авто-тегирование чанков (`content_type`, `tags`, `entity_kinds`, `page_number`, `word_start`, `word_end`, `headers`, `embedding_text`)
- **Dual-text embedding V3.0:** вектор строится на обогащённом тексте (`Документ: ... / Раздел: ... / Подраздел: ...`), а в БД хранится чистый текст (для будущего BM25)
- Embedding (Ollama/OpenAI-compatible) с дисковым кэшем (индексируется по `embedding_text`)
- **WebSocket трансляция V3.0:** прогресс по чанкам (`chunks_processed / chunks_total`) через `file_chunk_progress` + legacy `file_status`
- Graceful shutdown (30 сек)

**`db-api-server` (порт 8080)** — векторное хранилище
- LanceDB управление таблицами
- Upsert чанков с проверкой размерности
- Semantic search (ANN) + Text search (по чистому тексту — готовится для BM25)
- Delete документов, Vault binding

**`rag-db` (порт 5432)** — PostgreSQL
- Чаты, сообщения, Clarification states, Vault bindings, Audit log

### Взаимодействие сервисов

```
Browser → rag-backend (8000)
    ├─→ PostgreSQL (5432)
    ├─→ db-api-server (8080)
    └─→ rag-indexer (9000)

rag-indexer
    ├─→ db-api-server (8080)
    └─→ Ollama/OpenAI (embeddings)
```

## 🔑 Ключевая концепция: Domain Isolation & Agent Flow

- **Домен** = контекст работы (промпты, pipelines, retrieval strategy).
- **Vault** = хранилище данных. К домену привязано ≥1 vault.
- Чат привязан к домену. Retrieval ищет параллельно по всем `enabled` vault'ам домена, результаты дедуплицируются и сортируются по score.
- **Агентный цикл:** Запрос → `LLMRAGPlanner` (декомпозиция на подзапросы) → Parallel Retrieval → `format_context` (структурированный XML/MD) → D&D Prompt → LLM Generation → SSE Stream.
- Домены без vault'ов работают в LLM-only режиме.

## 📁 Полная структура проекта

```
.
├── docker-compose.yml
├── .env / .env.example
├── config/
│   ├── config.yaml
│   ├── config.example.yaml
│   ├── storage.config.yaml
│   └── storage.config.example.yaml
├── shared_contracts/
│   ├── __init__.py
│   ├── models.py
│   └── pyproject.toml
├── rag-backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── migrations/
│   ├── app/
│   └── pipelines/
├── rag-indexer/
│   ├── Dockerfile / requirements.txt
│   ├── app/{main.py, indexer_service.py, websocket_manager.py}
│   ├── indexer_worker.py
│   ├── parser/
│   │   ├── scanning/vault_scanner.py
│   │   ├── parsing/{md_parser.py, pdf_parser.py}
│   │   ├── preprocessing/{preprocessor.py, pdf_page_merger.py}
│   │   ├── chunking/{generic_chunker.py, entity_chunker.py, embedding_enricher.py}
│   │   └── state/state_manager.py
│   ├── embedding/{base_provider, ollama_provider, openai_provider, cache}.py
│   └── storage/{storage_client.py, binding_manager.py}
├── db-api-server/
│   ├── Dockerfile / requirements.txt
│   ├── main.py / config.py
│   ├── api/index.py
│   └── storage/lancedb_store.py
├── tests/{unit, integration}/
├── vaults/{dnd, work}/
├── state/
├── cache/embeddings/
├── data/{postgres, lancedb}/
└── logs/
```

## 🔄 Конвейеры обработки

### 📥 Конвейер индексации (Markdown) — V3.0

```
Markdown файл
  → md_parser (целиком + frontmatter)
  → generic_chunker (heading-aware split по # + sliding window)
  → preprocess (на каждом чанке отдельно, с source_hint)
  → embedding_enricher (build_embedding_text: "Документ: .../Раздел: H1/...")
  → Embedding (по embedding_text)
  → Upsert (text=чистый, vector=от обогащённого, metadata.embedding_text=обогащённый)
```

- **Парсинг:** `.md` читается целиком, YAML frontmatter извлекается в metadata.
- **Чанкинг:** `generic_chunker` режет по regex `^#{1,6}\s+.+$`. Секция ≤ `chunk_size` слов — один чанк. Иначе — скользящее окно с `overlap`.
- **Препроцессинг:** после чанкинга, на каждом чанке отдельно. NFC, замена `U+FFFD/U+25A1/U+2212`, склейка дефисных переносов, нормализация абзацев. Детекция suspicious Unicode с глобальным кэшем.
- **Enrichment:** для Markdown H1/H2 извлекаются из первой строки чанка (если начинается с `#`).

### 📥 Конвейер индексации (PDF) — V3.0

```
PDF файл
  → pdf_parser (постранично + кастомный HeadingAwareConverter)
  → pdf_page_merger (детекция колонтитулов + склейка + вставка "## Заголовки")
  → generic_chunker (теперь видит псевдо-markdown заголовки)
  → preprocess (на каждом чанке отдельно)
  → _assign_page_numbers_and_headers (восстановление page_number и headers по word_start)
  → embedding_enricher (build_embedding_text с headers из merger)
  → Embedding (по embedding_text)
  → Upsert (text=чистый, vector=от обогащённого)
```

**Детали каждого шага:**

- **`pdf_parser.parse_pdf`** — использует pdfminer.six с кастомным `HeadingAwareConverter`, который анализирует `LTTextBox.font_size` и `LTTextBox.y0`. Блоки с `font_size ≥ медианы × 1.3` и длиной ≤ 200 символов классифицируются как headings. Тексты заголовков нормализуются: `re.sub(r"\s+", " ", ...)` — убирает переводы строк внутри заголовков.
- **`pdf_page_merger.merge_pdf_pages`:**
  - **Детекция колонтитулов:** считает частоту первых/последних непустых строк каждой страницы. Строка, встречающаяся на ≥60% страниц и длиной ≤200 символов — колонтитул (удаляется). Отключается на документах < 3 страниц. Защита от ложных удалений: строки со словами "глава/chapter/часть/..." не считаются колонтитулами.
  - **Склейка:** страницы объединяются через `\n\n`, между ними вставляются маркеры `<!--PAGE:N-->` и заголовки как `## <text>\n\n`.
  - **Возвращает:** `(merged_text, page_offsets, placed_headings)`, где `page_offsets` — список `[(char_offset, page_number), ...]` для бинарного поиска.
- **`generic_chunker`** — работает на `merged_text`, где заголовки уже оформлены как `## ...`. Regex `^#{1,6}\s+.+$` находит их и режет семантически.
- **`_assign_page_numbers_and_headers`** — для каждого чанка вычисляет `estimated_char_offset = word_start × 6` и бинарным поиском по `page_offsets` находит `page_number`, а через `resolve_headers_at_offset` — активный заголовок.
- **Dual-text:** `chunk.text` = чистый текст (для будущего BM25 и цитирования в UI). `chunk.metadata["embedding_text"]` = обогащённый текст с префиксами "Документ: / Раздел: / Подраздел:" (используется для построения вектора).
- **OCR-фоллбэк:** если pdfminer не работает, используется `pdf2image+pytesseract`. Heading detection в этом режиме недоступен (возвращается пустой список headings).

### 📤 Конвейер генерации (Агент)

```
Запрос пользователя
  → LLM Decomposer
  → Параллельный Multi-Vault Retrieval
  → Дедупликация
  → Structured Context Assembly
  → D&D Prompt
  → LLM Generation
```

- `LLMRAGPlanner` разбивает сложный запрос на 1-3 оптимизированных подзапроса.
- `format_context()` формирует структурированный блок `<retrieved_context>` с явными тегами, типами контента и score.
- Системный промпт домена `dnd` жёстко задаёт роль соавтора, опору на RAG, Markdown-формат и готовность к уточнениям.

## 🌐 API Reference

### Chat API (`rag-backend:8000`)
- `POST /chat/create` → `{ "vault_id": "...", "domain_id": "..." }` → `{ "chat_id": "...", "title": "New Chat" }`
- `GET /chat/list?domain_id=<opt>` → список чатов с фильтрацией
- `GET /chat/{chat_id}` → история сообщений
- `POST /chat/{chat_id}/message` → `{ "content": "...", "stream": true }` → SSE или JSON
- `POST /chat/{chat_id}/rename` → переименование
- `DELETE /chat/{chat_id}` → удаление

### Config API (`rag-backend:8000`)
- `GET /config/domains` → `{ "domains": [{ "domain_id", "has_vault", "vault_enabled" }] }`
- `GET /config/vaults?domain_id=<opt>&search=<opt>` → список vault'ов

### DB Management API (`rag-backend:8000`)
- `GET /db/documents?vault_id=...&limit=...`
- `GET /db/docs/{document_id}/chunks?vault_id=...`
- `DELETE /db/docs/{document_id}?vault_id=...`
- `POST /db/search/text` → `{ "vault_id", "query_text", "limit" }`
- `POST /db/search/text/by-domain` → `{ "domain_id", "query_text", "limit" }`
- `POST /vaults/{vault_id}/reindex` → `{ "force_reindex": true }`
- `POST /vaults/{vault_id}/detach`

### Indexer API (`rag-indexer:9000`)
- `POST /api/v1/tasks` → `{ "vault_id", "force_reindex" }`
- `GET /api/v1/tasks` → `{ "active_task_ids": [...] }`
- `POST /api/v1/tasks/{task_id}/cancel`
- `GET /api/v1/tasks/{task_id}/state`
- `WS /api/v1/tasks/{task_id}/stream` → прогресс индексации (включая `file_chunk_progress` V3.0 и `file_status` V2.1)

### UI Endpoint
- `GET /` → `index.html`
- `GET /static/*` → статические файлы (CSS/JS)

## ⚙️ Конфигурация

### `config.yaml` (ключевые секции)

```yaml
vaults:
  dnd-main: { vault_id: "dnd-main", domain_id: "dnd", path: "/data/vaults/dnd", enabled: true }
  work:     { vault_id: "work",     domain_id: "work", path: "/data/vaults/work", enabled: false }

embedding_models:
  nomic-local:
    model_id: "nomic-local"
    provider: "ollama"
    model_name: "dengcao/Qwen3-Embedding-4B:Q4_K_M"
    base_url: "http://host.docker.internal:11434"
    dimensions: 2560
    enabled: true
    timeout_seconds: 30
    max_retries: 3

generation_models:
  deepseek:
    model_id: "openrouter/deepseek/deepseek-chat-v3.1"
    provider: "openai_compatible"
    base_url: "https://openai.api.proxyapi.ru/v1"
    api_key_env: "OPENAI_API_KEY"
    enabled: true
    timeout_seconds: 60

chat: { max_clarification_turns: 3, stream_answers: true, auto_title: true }
retrieval: { enabled: true, top_k: 10, reranker_enabled: false }

chunking:
  entity_aware_mode: true
  chunk_size: 512      # Максимальное количество слов в одном чанке
  overlap: 64          # Перекрытие соседних чанков (в словах)

pipelines: { enabled: true, path: "/app/pipelines", reload_interval_seconds: 2.0, debounce_seconds: 2.0 }
ui: { db_management_enabled: true }
```

### `.env`
Содержит `POSTGRES_*`, `DATABASE_URL`, `OPENAI_API_KEY`, `DB_API_URL`, `INDEXER_API_URL`. Подключается через `env_file` в `docker-compose.yml`.

## 🔐 Контракты данных

### Модель `UpsertChunk` (двойной текст)

```python
class UpsertChunk(BaseModel):
    document_id: str
    chunk_index: int
    text: str              # ← text_for_bm25: чистый текст (для BM25 и UI)
    vector: list[float]    # ← embedding от text_for_embedding (обогащённый)
    metadata: dict         # ← включает embedding_text для отладки + headers + page_number + ...
```

**Правило:** вектор строится на обогащённом тексте с префиксами "Документ: / Раздел: / Подраздел:" (для качества retrieval). В БД хранится чистый текст (для будущего BM25 и цитирования). Обогащённый текст дублируется в `metadata.embedding_text`.

### Модель `FileIndexState` (прогресс по чанкам — V3.0)

```python
class FileIndexState(BaseModel):
    checksum_md5: str
    chunk_ids: list[str] = []
    status: Literal["pending", "parsing", "chunking", "indexing", "done", "error", "cancelled", "empty", "indexed"]
    progress_pct: int = 0          # deprecated, для back-compat с V2.1
    chunks_total: int = 0          # актуальный прогресс: знаменатель
    chunks_processed: int = 0      # актуальный прогресс: числитель
    last_modified: datetime
    error: str | None = None
```

### WebSocket-сообщения

- **`WSFileChunkProgressMessage` (V3.0):** прогресс по чанкам `chunks_processed / chunks_total` со стадиями `parsing | chunking | indexing | done | error`.
- **`WSFileStatusMessage` (deprecated, V2.1):** оставлено для back-compat, используется текущим UI.
- **`WSTaskCompleteMessage`, `WSTaskCancelledMessage`** — без изменений.

## 🚀 Разработка и деплой

```bash
# Инициализация
cp .env.example .env
cp config/config.example.yaml config/config.yaml
cp config/storage.config.example.yaml config/storage.config.yaml

# Запуск
docker compose up -d

# Обновление после правок в коде
docker compose up -d --build rag-backend rag-indexer

# ⚠️ ВАЖНО: при переходе с V2.x на V3.0
# 1. Очистить кэш эмбеддингов (индексация теперь идёт по другому тексту):
#    docker compose exec rag-indexer sh -c 'rm -rf /app/cache/embeddings/*'
# 2. Force reindex всех PDF-vault'ов:
#    curl -X POST http://localhost:8000/vaults/<vault_id>/reindex \
#         -H "Content-Type: application/json" \
#         -d '{"force_reindex": true}'
# Также можно из UI кнопкой "⚡ Reindex (force)"

# Тесты
docker compose exec rag-backend pytest tests/
```

## 📅 Дорожная карта (TODO)

| Приоритет | Задача | Статус |
|---|---|---|
| High | Heading-aware chunking с настраиваемым chunk_size / overlap | ✅ V2.1 |
| High | Entity-aware chunking с вплетением метаданных | ✅ V2.1 (декоративный) |
| High | LLM-driven query decomposition & structured context | ✅ V2.1 |
| High | Deep preprocessing + PDF page tracking | ✅ V2.1 |
| High | Robust state tracking & dynamic config loading | ✅ V2.1 |
| High | **PDF Page Merger** (детекция колонтитулов + склейка страниц) | ✅ **V3.0** |
| High | **PDF Heading Detector** (анализ font_size через pdfminer) | ✅ **V3.0** |
| High | **Dual-Text Embedding** (обогащённый для вектора, чистый для BM25) | ✅ **V3.0** |
| High | **Прогресс-бар по чанкам (backend)** `chunks_processed / chunks_total` | ✅ **V3.0** |
| High | **Глобальный кэш suspicious Unicode-символов** | ✅ **V3.0** |
| High | **Препроцессинг после чанкинга** (на каждом чанке отдельно) | ✅ **V3.0** |
| High | **Frontend прогресс-бар** по чанкам в UI | ⚠️ **Откат V3.0, требует новой реализации** |
| Medium | Reranker (Cohere/Cross-encoder) | 🔜 В очереди |
| Medium | Refactor `entity_chunker` (расширение словарей из SRD D&D 5e) | 🔜 В очереди |
| Medium | Hybrid search (BM25 + Vector) — архитектурная основа заложена в V3.0 | 🔜 В очереди |
| Medium | Comprehensive tests (>80% coverage) | ⚠️ В процессе |
| Low | Auth, rate limiting, input validation | 🔜 Планируется |
| Low | Late/Semantic Chunking (альтернативный режим в конфиге) | 🔜 Планируется |

## 🤝 Протокол взаимодействия с AI-ассистентом

Для обеспечения максимальной точности и нулевых конфликтов слияния, работа ведётся по строгой схеме:

1. **Запрос задачи** → Пользователь описывает фичу, фикс бага или архитектурное изменение.
2. **Анализ контекста** → AI сверяет запрос с текущей архитектурой (`Домашний RAG.md`, `config.yaml`). Если не хватает информации о текущем состоянии кода → AI запрашивает конкретные файлы.
3. **Предоставление файлов** → Пользователь прикладывает актуальные версии запрошенных файлов. Без этого шага генерация кода не начинается.
4. **Генерация правок** → AI возвращает **полные тексты файлов** с аккуратно встроенными изменениями. Сохраняются все существующие интерфейсы, совместимость с FSM, streaming и pipelines. Частичные патчи не используются.
5. **Верификация и деплой** → Пользователь заменяет файлы, перезапускает контейнеры (`docker compose up -d --build`), проверяет логи.
6. **Итерация** → При необходимости повторяются шаги 1-5 для смежных модулей или тестирования.

### Жёсткие правила для AI

- ✅ Всегда спрашивать текущее состояние файлов перед генерацией.
- ✅ Вносить изменения только с полным пониманием зависимостей и контрактов.
- ✅ Возвращать готовые к замене файлы целиком.
- ❌ Не генерировать код вслепую или по памяти.
- ❌ Не использовать `diff`/патчи, только полные файлы.
- ❌ Не ломать существующую архитектуру Domain Isolation, Clarification FSM и Agent Loop.
- ❌ Не ссылаться на предыдущие версии документации. Этот файл — единственный источник правды.
- ❌ **При изменении Frontend: ВСЕГДА запрашивать актуальные версии `index.html`, `db_management.js`, `chat.css`, `api.js` и никогда не менять HTML-структуру без явного запроса.**

## 🧠 Ключевые архитектурные принципы V3.0

### Dual-Text Pattern

В каждом чанке хранятся две версии текста:
- **`text` (чистый)** — для отображения в UI, цитирования и будущего BM25-индекса.
- **`embedding_text` (обогащённый)** префиксами "Документ: / Раздел: / Подраздел:" — используется только для построения вектора.

Это позволяет в будущем добавить BM25 без переиндексации: BM25 будет работать по `text`, Vector search — по `vector` (уже построенному).

### Препроцессинг после чанкинга

Препроцессор работает на каждом чанке отдельно, а не на всём документе. Причины:
- Ошибка в препроцессоре не портит весь документ.
- Детекция suspicious chars с указанием точного чанка (`source_hint`).
- Артефакты на границах страниц PDF не "загрязняют" соседние чанки.

### Heading Detection по размеру шрифта

В PDF заголовки определяются эвристически через pdfminer:
- Собирается медианный `font_size` по всем текстовым блокам страницы.
- Блоки с `font_size ≥ median × 1.3` и длиной ≤ 200 символов → heading.
- Headings превращаются в `## <text>` перед чанкингом, что делает их видимыми для `generic_chunker`.
- Graceful degradation: если heading detection падает, чанкинг продолжается без заголовков.

### Колонтитулы через частотный анализ

Повторяющиеся строки (≥60% страниц, длина ≤200) удаляются как колонтитулы. Простая и надёжная эвристика для D&D-книг с типовыми футерами ("Глава 2 | Сигил, Город Дверей").

### Suspicious Chars Cache

Глобальный кэш на уровне модуля `preprocessor.py` логирует каждый неизвестный Unicode-символ один раз за весь процесс. Это предотвращает спам в логах при индексации больших vault'ов.

## 📝 История изменений

### V3.0 (текущая)
- PDF-Aware Semantic Chunking с heading detection
- Dual-Text Embedding Pattern
- Препроцессинг после чанкинга
- Глобальный кэш suspicious Unicode-символов
- Backend прогресс-бар по чанкам
- ⚠️ Frontend прогресс-бар откатан из-за поломок UI

### V2.1
- Heading-aware chunking для Markdown
- Entity-aware chunking (декоративный)
- LLM-driven query decomposition
- Deep preprocessing
- Robust state tracking