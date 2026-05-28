# RAG Platform — AI Diagnostic Context File

**Версия:** 1.0  
**Назначение:** Контекст для ИИ-ассистента при диагностике проблем и внесении изменений  
**Важно:** Этот файл — отправная точка. При работе ИИ может запрашивать конкретные файлы кода.

---

## 📋 О Проекте

**Название продукта:** MattMercer  
**Тип:** Локальная multi-domain RAG (Retrieval-Augmented Generation) платформа  
**Архитектура:** V3.0 PDF-Aware Semantic Chunking & Dual-Text Retrieval  

### Ключевые возможности

1. **Multi-domain архитектура** — поддержка различных предметных областей (DnD, Work, etc.)
2. **Vault-based хранение** — документы организованы в хранилища (vaults), привязанные к доменам
3. **PDF-Aware чанкинг** — постраничный парсинг PDF с детекцией заголовков по размеру шрифта
4. **Dual-Text Embedding** — вектор строится на обогащённом тексте, в БД хранится чистый текст (для будущего BM25)
5. **Clarification FSM** — система уточняющих вопросов для неоднозначных запросов
6. **LLM-driven Agent Planner** — декомпозиция сложных запросов на подзапросы
7. **Hot-reload Pipelines** — декларативные pipeline'ы с горячей перезагрузкой
8. **Worlds & Campaigns** — иерархическая организация контекста (для DnD)
9. **Settings UI** — управление настройками через веб-интерфейс без рестарта
10. **Streaming ответы** — SSE (Server-Sent Events) для потоковой генерации

### Стек технологий

- **Backend:** Python 3.13+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, LanceDB
- **Indexer:** FastAPI, pdfminer.six (heading-aware), pytesseract (OCR fallback), httpx
- **Frontend:** Vanilla HTML/CSS/JS (без фреймворков), marked.js + DOMPurify + highlight.js
- **Infrastructure:** Docker Compose, multi-stage builds, async workflows

---

## 🏗️ Архитектура Системы

### Сервисы (Docker Compose)

| Сервис | Порт | Описание | Зависимости |
|--------|------|----------|-------------|
| `rag-db` | 5432 | PostgreSQL 16 для метаданных | - |
| `db-api-server` | 8080 | HTTP-прослойка над LanceDB | rag-db |
| `rag-indexer` | 9000 | Индексация документов (внутренний) | db-api-server, rag-db |
| `rag-backend` | 8000 | Публичный API + Web UI | rag-db, db-api-server |
| `pdf-sidecar` | 8765 | OCR/Parsing на macOS хосте | - |

**Сеть:** Все сервисы в Docker сети `rag-net`. Только `rag-backend:8000` проброшен наружу.

### Схема взаимодействия

```
Browser → rag-backend (8000)
    ├─→ PostgreSQL (5432) — метаданные чатов, настройки, vaults
    ├─→ db-api-server (8080) — векторный поиск, CRUD чанков
    └─→ rag-indexer (9000) — индексация документов

rag-indexer
    ├─→ db-api-server (8080) — upsert чанков
    ├─→ Ollama/OpenAI — embeddings
    └─→ pdf-sidecar (8765) — парсинг PDF (опционально)
```

---

## 🌐 Полное описание Web Интерфейса

### Структура страниц

#### 1. Главная страница чата (`GET /`)

**Расположение:** `rag-backend/app/static/index.html`

##### Sidebar (левая панель)

**Элементы сверху вниз:**

1. **Заголовок:** `<h2>MattMercer</h2>`
2. **Кнопка "Настройки платформы"** (`#settings-btn`)
   - Класс: `btn btn-secondary btn-full btn-sidebar-secondary`
   - Действие: Открывает страницу настроек
3. **Кнопка "⚙️ Управление хранилищем"** (`#db-mgmt-btn`)
   - Класс: `btn btn-secondary btn-full btn-sidebar-secondary`
   - Действие: Открывает модальное окно управления хранилищем
4. **Селектор доменов** (`.domain-selector`)
   - Label: "Домен:"
   - Select: `#domain-select` (класс: `domain-select`)
   - Действие: Переключение между доменами (DnD, Work, etc.)
   - При изменении: Загружает список чатов домена, показывает/скрывает selector миров
5. **Селектор миров** (`#world-selector`, скрыт по умолчанию)
   - Label: "Мир:"
   - Select: `#world-select` (класс: `domain-select`)
   - Опции: `<option value="">Без мира</option>` + динамически загруженные миры
   - Список кампаний: `#campaigns-list` (динамически заполняется)
   - Действие: Выбор мира для нового чата, toggle кампаний
6. **Кнопка "+ Новая беседа"** (`#new-chat-btn`)
   - Класс: `btn btn-primary btn-full`
   - Действие: Создаёт новый чат в текущем домене/мире

**Список чатов:** `.chat-list #chat-list`
- Динамически заполняется чатами выбранного домена
- Каждый чат отображается с названием и временем последнего сообщения

##### Основная область чата

**Header чата:** `.chat-header #chat-header`
- Заголовок: `#chat-title` — название текущего чата или "Выберите чат или создайте новый"

**Context Bar** (панель контекста, скрыта если нет мира/pipeline): `.chat-context-bar #chat-context-bar`
- **Блок мира:** `#context-world`
  - Иконка: 🌍
  - Название: `#world-name`
- **Разделитель:** `|`
- **Блок Pipeline:** `.context-pipeline`
  - Label: "Pipeline:"
  - Select: `#pipeline-select`
    - Опции: `<option value="">Авто</option>` + динамически загруженные pipelines
  - Кнопка фиксации: `#lock-pipeline-btn`
    - Состояния: 🔓 (не зафиксировано) / 🔒 (зафиксировано)
    - Действие: Фиксирует/разблокирует выбранный pipeline для чата

**Контейнер сообщений:** `.messages-container #messages-container`
- Приветственное сообщение: `#welcome-message` (скрыто при активном чате)
- Сообщения пользователя и ассистента рендерятся динамически
- Поддерживается Markdown rendering, подсветка кода

**Status Banner:** `#status-banner` (скрыт по умолчанию)
- Класс: `status-banner hidden`
- Отображает статус платформы (например, "Индексация запущена")

**Область ввода:** `.input-area #input-area` (скрыта пока не выбран чат)
- Textarea: `#message-input`
  - Placeholder: "Введите сообщение..."
  - Rows: 1 (авто-расширение)
- Кнопка отправки: `#send-btn`
  - Класс: `btn btn-send`
  - Действие: Отправляет сообщение в чат (SSE streaming)

#### 2. Страница настроек (`#settings-page`)

**Расположение:** Скрыта по умолчанию, показывается при клике на "Настройки платформы"

**Header настроек:**
- Заголовок: `<h2>Настройки платформы</h2>`
- Кнопка "Назад к чатам": `#back-to-chat-btn`

**Табы настроек:** `.settings-tabs`
1. **"Домены"** (`data-tab="domains"`) — управление доменами
2. **"Vault'ы"** (`data-tab="vaults"`) — управление хранилищами
3. **"Генеративные модели"** (`data-tab="gen-models"`) — LLM для генерации
4. **"Embedding-модели"** (`data-tab="emb-models"`) — модели для эмбеддингов
5. **"Параметры"** (`data-tab="params"`) — runtime параметры платформы
6. **"Pipelines"** (`data-tab="pipelines"`) — управление pipelines
7. **"Миры"** (`data-tab="worlds"`) — управление мирами и кампаниями

**Контент настроек:** `#settings-content`
- Динамически заполняется в зависимости от выбранного таба

#### 3. Модальные окна

##### Модальное окно переименования чата (`#rename-modal`)

**Структура:**
- Заголовок: `<h3>Переименовать чат</h3>`
- Группа формы:
  - Label: "Новое название:"
  - Input: `#rename-input` (maxlength: 255)
- Кнопки:
  - "Сохранить": `#rename-confirm-btn`
  - "Отмена": `#rename-cancel-btn`

**Действие:** Переименование выбранного чата

##### Модальное окно управления хранилищем (`#db-mgmt-modal`)

**Класс:** `modal modal-lg` (широкое)

**Header:**
- Заголовок: `<h3>Хранилище</h3>`
- Кнопка закрытия: `#db-mgmt-close-btn` (✕)

**Табы:**
1. **"Управление"** (`data-tab="manage"`, активный по умолчанию)
2. **"Поиск"** (`data-tab="search"`)

**Вкладка "Управление":**

**Блок прогресса индексации** (`#mgmt-progress-block`, скрыт по умолчанию):
- Status badge: `#mgmt-task-status` (класс: `status-badge status-running`)
- Прогресс файлов: "Файлов: **0** / 0"
  - Счётчик выполненных: `#mgmt-files-done`
  - Счётчик всего: `#mgmt-files-total`
- Процент: `<span id="mgmt-progress-pct">0</span>%`
- Кнопка "Отменить": `#mgmt-cancel-btn` (класс: `btn btn-sm btn-danger`)
- Overall progress bar: `#mgmt-overall-bar` (`.overall-progress-bar`)
- Список файлов: `#mgmt-files-list` (`.files-list2`)

**Табы по доменам:** `#mgmt-domain-tabs` (`.domain-tabs`)
- Динамически заполняются доменами

**Список vault'ов:** `#mgmt-vaults-container` (`.vaults-container`)
- Для каждого vault'а:
  - Название vault'а
  - Кнопка "⚡ Reindex (force)" — принудительная переиндексация
  - Кнопка "🗑️ Detach" — открепить vault (очистить данные)
  - Список документов с кнопками удаления

**Вкладка "Поиск":**

**Форма поиска:** `.search-form2`
- Select домена: `#search-domain-select` (`.search-domain-sel`)
- Input запроса: `#search-query-input` (placeholder: "Введите текст...")
- Input лимита: `#search-limit` (value: 20, min: 1, max: 200)
- Кнопка "Найти": `#search-btn`

**Результаты поиска:** `#search-results` (`.search-results`)
- Динамически заполняется найденными чанками
- Каждый результат: путь к документу, номер страницы, score, текст чанка

##### Модальное окно деталей чанка (`#chunk-detail-modal`)

**Структура:**
- Header:
  - Span (пустой)
  - Кнопка закрытия: `#chunk-detail-close` (✕)
- Контент: `#chunk-detail-content` (`.chunk-detail-body`)
- Отображает полный текст чанка, metadata, embedding_text

---

## ⚙️ Детальное описание компонентов

### 1. Frontend JavaScript модули

#### `api.js` — API клиент

**Назначение:** Обёртка над fetch для всех API вызовов

**Ключевые методы:**

```javascript
// Chat API
api.createChat(vault_id, domain_id, world_id) → {chat_id, title}
api.getChatList(domain_id) → [ChatRecord]
api.getChat(chat_id) → ChatRecord с messages
api.sendMessage(chat_id, content, stream=true) → SSE stream
api.renameChat(chat_id, title) → void
api.deleteChat(chat_id) → void
api.lockPipeline(chat_id, pipeline_id) → void

// Settings API
api.getSettingsParams() → [PlatformSetting]
api.updateSetting(key, value) → void
api.resetSettings() → void
api.getDomains() → [Domain]
api.createDomain(payload) → Domain
api.updateDomain(domain_id, payload) → void
api.deleteDomain(domain_id) → void
api.getDomainPrompts(domain_id) → [Prompt]
api.updateDomainPrompt(domain_id, prompt_type, content) → void
api.getDomainFields(domain_id) → [ClarificationField]
api.updateDomainFields(domain_id, fields) → void
api.getGenerationModels() → [GenerationModel]
api.createGenerationModel(payload) → GenerationModel
api.updateGenerationModel(model_id, payload) → void
api.deleteGenerationModel(model_id) → void
api.activateGenerationModel(model_id) → void
api.getEmbeddingModels() → [EmbeddingModel]
api.createEmbeddingModel(payload) → EmbeddingModel
api.updateEmbeddingModel(model_id, payload) → void
api.deleteEmbeddingModel(model_id) → void
api.getSettingsVaults() → [Vault]
api.createVault(payload) → Vault
api.updateVault(vault_id, payload) → void
api.deleteVault(vault_id) → void
api.getWorlds(vault_id) → [World]
api.createWorld(payload) → World
api.updateWorld(world_id, payload) → void
api.getWorldCampaigns(world_id) → [Campaign]
api.toggleCampaign(world_id, campaign_id) → void
api.getPipelines(domain_id) → [Pipeline]
api.createPipeline(payload) → Pipeline
api.updatePipeline(pipeline_id, payload) → void

// DB Management API
api.getDocuments(vault_id, limit) → [DocumentRecord]
api.getDocumentChunks(document_id, vault_id) → [ChunkRecord]
api.deleteDocument(document_id, vault_id) → void
api.searchText(vault_id, query_text, limit) → [SearchResult]
api.searchTextByDomain(domain_id, query_text, limit) → [SearchResult]
api.triggerReindex(vault_id, force_reindex) → {task_id}
api.cancelIndexTask(task_id) → void
api.getIndexTaskState(task_id) → IndexState
api.detachVault(vault_id) → void
```

#### `sidebar.js` — SidebarManager

**Назначение:** Управление sidebar (домены, миры, кампании, список чатов)

**Состояние:**
```javascript
{
    currentDomainId: string | null,
    currentWorldId: string | null,
    domainCache: [Domain],
    chatCache: [ChatRecord]
}
```

**Ключевые методы:**
- `init()` — инициализация, загрузка доменов
- `selectDomain(domain_id)` — выбор домена, загрузка vault'ов и миров
- `selectWorld(world_id)` — выбор мира, загрузка кампаний
- `toggleCampaign(world_id, campaign_id)` — вкл/выкл кампанию
- `renderChatList(chats)` — рендеринг списка чатов
- `createChat()` — создание нового чата
- `deleteChat(chat_id)` — удаление чата
- `renameChat(chat_id, title)` — переименование чата

#### `chat.js` — ChatManager

**Назначение:** Управление чатом (отправка сообщений, SSE streaming, рендеринг)

**Состояние:**
```javascript
{
    currentChatId: string | null,
    currentPipelineId: string | null,
    isLocked: boolean,
    messageHistory: [ChatMessage]
}
```

**Ключевые методы:**
- `init()` — инициализация
- `loadChat(chat_id)` — загрузка чата с историей
- `sendMessage(content)` — отправка сообщения с SSE streaming
- `parseSSE(stream)` — парсинг SSE событий
- `appendToken(token)` — добавление токена в ответ
- `showPipelineBadge(data)` — отображение бейджа pipeline
- `updateProgressBar(step, total, step_name)` — обновление прогресс-бара
- `markStepDone(step)` — отметка шага как выполненного
- `appendSources(sources)` — отображение источников
- `appendGroupedSources(step_groups)` — отображение группированных источников
- `extractCitedIndices(text)` — извлечение цитат `[1]`, `[2]` из текста

**SSE события (новый формат Pipeline):**
```javascript
{type: 'pipeline_selected', pipeline_id, name, mode, reasoning}
{type: 'progress', step, total, step_name}
{type: 'step_done', step}
{type: 'token', content}
{type: 'sources', grouped_by_step: true, step_groups: [...]}
{type: 'sources', sources: [...]}
{type: 'error', message}
{type: '[DONE]'}
```

**SSE события (старый формат Planner):**
```javascript
{token: "..."}
{sources: [...]}
```

#### `settings.js` — SettingsManager

**Назначение:** Управление страницей настроек

**Ключевые методы:**
- `init()` — инициализация, загрузка параметров
- `switchTab(tab_name)` — переключение таба
- `renderDomainsTab()` — рендеринг таба доменов
- `renderVaultsTab()` — рендеринг таба vault'ов
- `renderGenModelsTab()` — рендеринг таба генеративных моделей
- `renderEmbModelsTab()` — рендеринг таба embedding-моделей
- `renderParamsTab()` — рендеринг таба параметров
- `renderPipelinesTab()` — рендеринг таба pipelines
- `renderWorldsTab()` — рендеринг таба миров

#### `db_management.js` — DBManagementManager

**Назначение:** Управление модальным окном хранилища

**Ключевые методы:**
- `init()` — инициализация
- `openModal()` — открытие модального окна
- `renderVaultsContainer()` — рендеринг списка vault'ов
- `renderProgressBlock(task_id)` — рендеринг прогресса индексации
- `handleWebSocket(task_id)` — подключение к WebSocket прогресса
- `renderSearchResults(results)` — рендеринг результатов поиска
- `showChunkDetail(chunk)` — отображение деталей чанка

---

### 2. Backend компоненты

#### `rag-backend/app/main.py`

**Назначение:** Точка входа FastAPI

**Основные endpoints:**
- `GET /` — раздача `index.html`
- `GET /static/*` — статические файлы
- `GET /health` — health check
- `GET /status` — статус платформы
- `POST /chat/create` — создание чата
- `GET /chat/list` — список чатов
- `GET /chat/{chat_id}` — чат с сообщениями
- `POST /chat/{chat_id}/message` — отправка сообщения (SSE)
- `GET /api/settings/*` — настройки
- `GET /api/db/*` — DB management
- `POST /vaults/{vault_id}/reindex` — триггер индексации

#### `rag-backend/app/services/settings_service.py`

**Назначение:** Singleton для управления настройками платформы

**Ключевые методы:**
- `get_all_params()` → dict[key, value]
- `update_param(key, value)` → void
- `reset_to_defaults()` → void
- `get_generation_model(model_id)` → GenerationModel
- `get_active_generation_model()` → GenerationModel
- `get_embedding_model(model_id)` → EmbeddingModel

#### `rag-backend/app/services/retrieval.py`

**Назначение:** Поиск чанков в LanceDB

**Ключевые методы:**
- `retrieve(vault_id, query, top_k)` → [ChunkRecord]
- `retrieve_multi_vault(domain_id, query, top_k)` → [ChunkRecord]
  - Параллельный поиск по всем enabled vault'ам домена
  - Дедупликация и сортировка по score

#### `rag-backend/app/services/planner.py`

**Назначение:** LLM-driven декомпозиция запросов

**Класс:** `LLMRAGPlanner`

**Ключевые методы:**
- `decide(query, context)` → Plan
  - Возвращает список подзапросов для параллельного выполнения
  - Определяет необходимость clarification вопросов

#### `rag-backend/app/services/pipeline_executor.py`

**Назначение:** Выполнение hot-reload pipelines

**Ключевые методы:**
- `execute(pipeline_id, query, context)` → Generator[Event]
  - Пошаговое выполнение pipeline
  - SSE streaming событий: `progress`, `step_done`, `token`, `sources`

#### `rag-backend/app/services/clarification_fsm.py`

**Назначение:** FSM для уточняющих вопросов

**Состояния:**
- `idle` — ожидание запроса
- `collecting` — сбор недостающих полей
- `complete` — все поля собраны
- `fallback` — превышен лимит раундов

**Ключевые методы:**
- `start_collecting(missing_fields)` → void
- `process_answer(answer)` → {complete: bool, collected: dict}
- `get_next_question()` → string

---

### 3. Indexer компоненты

#### `rag-indexer/app/indexer_service.py`

**Назначение:** Оркестрация индексации

**Ключевые методы:**
- `start_task(vault_id, force_reindex)` → task_id
- `cancel_task(task_id)` → void
- `get_task_state(task_id)` → IndexState
- `stream_progress(task_id)` → WebSocket stream

#### `rag-indexer/parser/parsing/pdf_parser.py`

**Назначение:** Парсинг PDF с heading detection

**Алгоритм:**
1. Постраничное чтение через pdfminer
2. `HeadingAwareConverter` анализирует `font_size` и `y0` текстовых блоков
3. Блоки с `font_size ≥ median × 1.3` и длиной ≤ 200 символов → headings
4. Нормализация заголовков: `re.sub(r"\s+", " ", ...)`
5. Возвращает: `(page_texts, page_headings)`

#### `rag-indexer/parser/preprocessing/pdf_page_merger.py`

**Назначение:** Склейка страниц с удалением колонтитулов

**Алгоритм:**
1. Частотный анализ первых/последних строк каждой страницы
2. Строка, встречающаяся на ≥60% страниц и длиной ≤200 → колонтитул
3. Удаление колонтитулов
4. Склейка страниц через `\n\n` с маркерами `<!--PAGE:N-->`
5. Вставка заголовков как `## <text>\n\n`
6. Возвращает: `(merged_text, page_offsets, placed_headings)`

#### `rag-indexer/parser/chunking/generic_chunker.py`

**Назначение:** Heading-aware чанкинг

**Алгоритм:**
1. Regex `^#{1,6}\s+.+$` находит заголовки
2. Секция ≤ `chunk_size` слов → один чанк
3. Иначе → sliding window с `overlap`
4. Возвращает: [Chunk]

#### `rag-indexer/embedding/cache.py`

**Назначение:** Дисковый кэш эмбеддингов

**Ключ:** SHA256 хэш от `embedding_text`

**Методы:**
- `get(text_hash)` → vector | None
- `set(text_hash, vector)` → void

---

## 🗄️ Работа с параметрами системы

### Хранение параметров

**Таблица:** `platform_settings` (PostgreSQL)

**Схема:**
```sql
CREATE TABLE platform_settings (
    key        VARCHAR(128) PRIMARY KEY,
    value      TEXT NOT NULL,
    value_type VARCHAR(16) NOT NULL,  -- int, float, bool, str
    group_name VARCHAR(64) NOT NULL,
    label      VARCHAR(255) NOT NULL,
    hint       TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Seed данные (16 параметров)

| Key | Value | Type | Group | Label |
|-----|-------|------|-------|-------|
| `retrieval.enabled` | `true` | bool | retrieval | Включить retrieval |
| `retrieval.top_k` | `10` | int | retrieval | Количество чанков для поиска |
| `retrieval.reranker_enabled` | `false` | bool | retrieval | Включить reranker |
| `chunking.chunk_size` | `2000` | int | chunking | Размер чанка (слова) |
| `chunking.overlap` | `64` | int | chunking | Перекрытие чанков |
| `chunking.entity_aware_mode` | `true` | bool | chunking | Entity-aware режим |
| `chat.max_clarification_turns` | `3` | int | chat | Макс. раундов уточнений |
| `chat.stream_answers` | `true` | bool | chat | Streaming ответов |
| `chat.auto_title` | `true` | bool | chat | Авто-генерация заголовка |
| `reranker.enabled` | `false` | bool | reranker | Включить reranker |
| `reranker.provider` | `null` | str | reranker | Провайдер reranker |
| `reranker.base_url` | `null` | str | reranker | URL reranker |
| `reranker.model_name` | `null` | str | reranker | Модель reranker |
| `pdf_sidecar.url` | `"http://host.docker.internal:8765"` | str | pdf_sidecar | URL pdf-sidecar |
| `pdf_sidecar.timeout_seconds` | `180` | int | pdf_sidecar | Таймаут парсинга PDF |
| `pdf_sidecar.fallback_to_pdfminer` | `true` | bool | pdf_sidecar | Fallback на pdfminer |

### Чтение параметров

**Сервис:** `SettingsService` (singleton)

**Метод:** `get_all_params()`

**Алгоритм:**
```python
async def get_all_params(self) -> dict:
    async with self.session_factory() as session:
        result = await session.execute(select(PlatformSetting))
        settings = result.scalars().all()
        
        params = {}
        for s in settings:
            if s.value_type == 'int':
                params[s.key] = int(s.value)
            elif s.value_type == 'float':
                params[s.key] = float(s.value)
            elif s.value_type == 'bool':
                params[s.key] = s.value.lower() == 'true'
            else:
                params[s.key] = s.value
        
        return params
```

**Пример использования:**
```python
# В retrieval.py
settings = await self.settings_service.get_all_params()
top_k = settings.get('retrieval.top_k', 10)
enabled = settings.get('retrieval.enabled', True)

if not enabled:
    return []

results = await self.db_api.search(vault_id, query, top_k=top_k)
```

### Запись параметров

**API Endpoint:** `PUT /api/settings/params/{key}`

**Request:**
```json
{
    "value": "new_value",
    "value_type": "str"
}
```

**Сервис:** `SettingsService.update_param(key, value, value_type)`

**Алгоритм:**
```python
async def update_param(self, key: str, value: str, value_type: str):
    async with self.session_factory() as session:
        setting = await session.get(PlatformSetting, key)
        if not setting:
            raise HTTPException(404, f"Setting {key} not found")
        
        setting.value = value
        setting.value_type = value_type
        setting.updated_at = datetime.now(timezone.utc)
        
        await session.commit()
        
        # Invalidate cache if needed
        self._cache.pop(key, None)
```

**Пример из UI:**
```javascript
// settings.js
async updateSetting(key, value, valueType) {
    const response = await fetch(`/api/settings/params/${key}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({value, value_type: valueType})
    });
    
    if (!response.ok) throw new Error('Failed to update');
}

// Usage:
await this.updateSetting('retrieval.top_k', '15', 'int');
```

### Reset к defaults

**API Endpoint:** `POST /api/settings/params/reset`

**Алгоритм:**
```python
async def reset_to_defaults(self):
    defaults = {
        'retrieval.enabled': ('true', 'bool'),
        'retrieval.top_k': ('10', 'int'),
        # ... остальные 14 параметров
    }
    
    async with self.session_factory() as session:
        for key, (value, value_type) in defaults.items():
            setting = await session.get(PlatformSetting, key)
            if setting:
                setting.value = value
                setting.value_type = value_type
                setting.updated_at = datetime.now(timezone.utc)
        
        await session.commit()
```

---

## 🔄 Основные процессы

### 1. Индексация документа

```
User → POST /vaults/{vault_id}/reindex (кнопка "⚡ Reindex (force)")
     ↓
rag-backend:
  1. Проверка active tasks для vault
  2. POST http://rag-indexer:9000/api/v1/tasks
     Body: {"vault_id": "...", "force_reindex": true/false}
     ↓
rag-indexer:
  1. Создать task_id
  2. Scan vault directory (.md, .pdf)
  3. For each file:
     a. Вычислить MD5 checksum
     b. Если checksum совпадает и не force → skip
     c. Parse:
        - PDF → pdf_parser (постранично + heading detection)
        - MD → md_parser (целиком + frontmatter)
     d. Preprocess (pdf_page_merger для PDF)
     e. Chunk (generic_chunker, heading-aware)
     f. Assign page numbers & headers (_assign_page_numbers_and_headers)
     g. Enrich (embedding_enricher.build_embedding_text)
     h. Embedding:
        - Проверить кэш по hash(embedding_text)
        - Если нет → запрос к Ollama/OpenAI
        - Сохранить в кэш
     i. UpsertChunk:
        - text: чистый текст (для BM25)
        - vector: от embedding_text (обогащённый)
        - metadata: {embedding_text, headers, page_number, ...}
     j. POST http://db-api-server:8080/index/upsert
     k. WS stream: file_chunk_progress (chunks_processed / chunks_total)
  4. Update IndexState в PostgreSQL
  5. WS stream: task_complete
```

### 2. Обработка сообщения в чате

```
User → POST /chat/{chat_id}/message (кнопка "Отправить")
     ↓
rag-backend:
  1. Save user message to DB (messages table)
  2. Load ClarificationState для чата
  3. If stage == "idle":
     a. LLMRAGPlanner.decide(query)
     b. Если нужны уточнения → ClarificationFSM.start_collecting()
     c. Return SSE: clarification question
  4. If stage == "collecting":
     a. ClarificationFSM.process_answer(user_input)
     b. Если complete → execute pipeline
     c. Если ещё вопросы → return next question
  5. Execute pipeline:
     a. retrieve_multi_vault(domain_id, query, top_k)
        - Параллельный поиск по всем enabled vault'ам
        - Дедупликация по chunk_id
        - Сортировка по score
     b. format_context(chunks) → XML/MD structured context
     c. Build prompt: system + context + query
     d. Call LLM (GenerationProvider.generate())
     e. Stream tokens via SSE
  6. Save assistant message to DB
  7. SSE events:
     - pipeline_selected (если pipeline)
     - progress (step, total, step_name)
     - step_done (step)
     - token (content)
     - sources (grouped_by_step, step_groups)
     - [DONE]
```

### 3. Hot-reload Pipeline

```
Pipeline Executor (background thread в rag-backend):
  1. Poll /app/pipelines каждые 2 секунды
  2. Detect changes (debounce 2s)
  3. For each pipeline:
     a. Parse YAML manifest (rule_lookup.yaml)
     b. Load Python module (impl.py)
     c. Validate structure (steps, final_composition)
     d. Если валидно → atomic swap в registry
     e. Если невалидно → log error, keep old version
  4. Notify connected clients via SSE (опционально)
```

---

## 🛠️ Диагностика проблем

### Типичные проблемы и запрашиваемые файлы

#### Проблема: Индексация зависает на "parsing"

**Запросить файлы:**
- `rag-indexer/app/indexer_service.py`
- `rag-indexer/parser/parsing/pdf_parser.py`
- `rag-indexer/parser/preprocessing/pdf_page_merger.py`
- `logs/indexer.log`

**Что искать:**
- Ошибки pdfminer
- Timeout при парсинге больших PDF
- Проблемы с кодировкой

#### Проблема: Нет эмбеддингов в результатах поиска

**Запросить файлы:**
- `rag-indexer/embedding/openai_provider.py`
- `rag-indexer/embedding/ollama_provider.py`
- `rag-indexer/embedding/cache.py`
- `config/config.yaml` (секция embedding_models)

**Что искать:**
- Недоступность Ollama/OpenAI
- Несоответствие dimensions
- Ошибки кэша

#### Problem: Clarification FSM не задаёт вопросы

**Запросить файлы:**
- `rag-backend/app/services/clarification_fsm.py`
- `rag-backend/app/services/planner.py`
- `rag-backend/app/domains/dnd/prompts.yaml`

**Что искать:**
- Неправильный промпт planner
- Ошибки в domain_clarification_fields
- Лимит turns превышен

#### Проблема: UI не показывает прогресс индексации

**Запросить файлы:**
- `rag-backend/app/static/js/db_management.js`
- `rag-backend/app/static/js/api.js`
- `rag-backend/app/static/index.html` (блок `#mgmt-progress-block`)

**Что искать:**
- Ошибки WebSocket подключения
- Неправильный парсинг `file_chunk_progress`
- CSS классы `hidden`

#### Проблема: Pipeline не обновляется после изменения YAML

**Запросить файлы:**
- `rag-backend/app/services/pipeline_executor.py`
- `rag-backend/pipelines/dnd/rule_lookup.yaml`
- `rag-backend/pipelines/dnd/impl.py`
- `config/config.yaml` (секция pipelines)

**Что искать:**
- `pipelines.enabled: false`
- Синтаксические ошибки YAML
- Ошибки валидации steps

---

## 📦 Запросы файлов для диагностики

При работе с этим контекстом, ИИ должен запрашивать файлы по следующему алгоритму:

### Шаг 1: Определить область проблемы

- **Индексация** → запросить файлы из `rag-indexer/`
- **Чат/SSE** → запросить файлы из `rag-backend/app/services/` и `rag-backend/app/static/js/chat.js`
- **Настройки UI** → запросить `settings.js`, `settings.py`, `settings_service.py`
- **БД/параметры** → запросить `models.py`, `migrations.py`, `settings_service.py`
- **UI верстка** → запросить `index.html`, `chat.css`, соответствующий JS файл

### Шаг 2: Запросить актуальные версии файлов

**Важно:** Никогда не генерировать код без предварительного получения актуальных версий файлов!

**Пример запроса:**
> "Для диагностики этой проблемы мне нужны следующие файлы:
> - `rag-backend/app/static/js/chat.js`
> - `rag-backend/app/static/js/api.js`
> - `rag-backend/app/services/pipeline_executor.py`
> 
> Пожалуйста, предоставьте содержимое этих файлов."

### Шаг 3: Анализ и генерация правок

После получения файлов:
1. Проанализировать текущую реализацию
2. Выявить корневую причину проблемы
3. Предложить полные тексты файлов с изменениями (не diff!)

---

## 📝 Примечания для ИИ

1. **Конфигурация в БД:** Параметры платформы хранятся в PostgreSQL (`platform_settings`), не в YAML. YAML используется только для initial seed и storage config.

2. **ENCRYPTION_KEY:** Обязателен для работы с API ключами моделей (шифрование в БД).

3. **pdf-sidecar на хосте:** Работает на macOS хосте, не в Docker. URL: `http://host.docker.internal:8765`.

4. **Миры и кампании:** НЕ удаляются через API — только вручную через ФС.

5. **Pipelines декларативные:** JSONB в БД, не YAML файлы (кроме legacy lookup файлов в `pipelines/`).

6. **Clarification FSM лимит:** Ограничивает число раундов через `chat.max_clarification_turns` (default: 3).

7. **Hot-reload атомарный:** Невалидная версия pipeline игнорируется, старая версия сохраняется.

8. **Dual-Text Pattern:** 
   - `chunk.text` = чистый текст (для BM25 и UI)
   - `chunk.metadata.embedding_text` = обогащённый текст (для построения вектора)

9. **Frontend без фреймворков:** Vanilla JS, никаких React/Vue. Изменения должны быть совместимы с существующей архитектурой.

10. **SSE streaming:** Ответы генерируются потоково. Важно не блокировать event loop.

---

## 🔗 Ссылки на спецификации

В проекте есть детальные технические спецификации в `/workspace/specs_update/`:

- `Spec-00-Architecture-Overview-artifact.md` — общий обзор архитектуры
- `Spec-01-Database-Foundation.md` — схема БД
- `Spec-02a/b/c-Settings-*` — настройки (сервисы, API, UI)
- `Spec-03a/b-Indexer-*` — индексация (DB client, parser, cleanup)
- `Spec-04a/b/c-Pipeline-*` — pipelines (retrieval, executor, router)
- `Spec-05a/b/c-Settings-UI-*` — UI настроек
- `Spec-06-Pipelines-And-Worlds-UI.md` — UI pipelines и миров

---

## 🚀 Быстрый старт для ИИ

Если пользователь описывает проблему, следуйте этому алгоритму:

1. **Классифицировать проблему:**
   - Индексация → `rag-indexer/`
   - Чат → `rag-backend/app/services/` + `chat.js`
   - Настройки → `settings_service.py` + `settings.js`
   - UI верстка → `index.html` + `chat.css` + JS

2. **Запросить файлы:**
   > "Для анализа мне нужны файлы: [список]"

3. **Получить файлы от пользователя**

4. **Проанализировать и предложить решение:**
   - Объяснить корневую причину
   - Предоставить полные тексты файлов с изменениями

5. **Инструкция по деплою:**
   ```bash
   # После замены файлов
   docker compose up -d --build rag-backend rag-indexer
   docker compose logs -f rag-backend rag-indexer
   ```

---

**Конец файла контекста.**
