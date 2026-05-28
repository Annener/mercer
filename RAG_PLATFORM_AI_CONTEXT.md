# RAG Platform — AI Diagnostic Context File

**Версия:** 2.0 (Unified)  
**Назначение:** Единый контекст для ИИ-ассистента при диагностике проблем и внесении изменений  
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
- **TypeScript:** Не используется, чистый JavaScript

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

## 📁 Структура Проекта

```
/workspace/
├── README.md                          # Основная документация
├── docker-compose.yml                 # Оркестрация сервисов
├── requirements-dev.txt               # Dev зависимости
├── pytest.ini                         # Конфиг тестов
│
├── config/
│   ├── config.yaml                    # Главный конфиг (vaults, модели, настройки)
│   └── storage.config.yaml            # Конфиг LanceDB storage
│
├── shared_contracts/
│   ├── __init__.py
│   ├── models.py                      # Pydantic модели для API контрактов
│   └── pyproject.toml
│
├── rag-backend/                       # Основной backend сервис
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini                    # Миграции БД
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # Точка входа FastAPI
│   │   ├── config.py                  # Парсинг config.yaml
│   │   ├── logging_config.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── models.py              # SQLAlchemy ORM модели
│   │   │   ├── session.py             # DB сессии
│   │   │   └── migrations.py          # Alembic миграции
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── chat.py                # Chat endpoints
│   │   │   ├── settings.py            # Settings management API
│   │   │   ├── db_management.py       # DB/Vault operations
│   │   │   └── config_api.py          # Config reload API
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── settings_service.py    # Settings singleton
│   │   │   ├── domain_service.py      # Domain logic
│   │   │   ├── retrieval.py           # Retrieval from LanceDB
│   │   │   ├── planner.py             # LLM-based planning
│   │   │   ├── pipeline_executor.py   # Pipeline execution
│   │   │   ├── pipeline_router.py     # Pipeline selection
│   │   │   ├── prompt_pack.py         # Prompt templates
│   │   │   └── clarification_fsm.py   # Clarification state machine
│   │   ├── providers/
│   │   │   └── generation/
│   │   │       ├── __init__.py
│   │   │       ├── base.py            # Base generation provider
│   │   │       └── openai_compatible.py
│   │   ├── domains/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py
│   │   │   ├── default/
│   │   │   ├── dnd/
│   │   │   └── work/
│   │   ├── pipelines/
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   ├── planners/
│   │   │   └── __init__.py
│   │   └── static/
│   │       └── js/
│   │           ├── api.js             # API клиент (обёртка fetch)
│   │           ├── chat.js            # ChatManager (SSE streaming)
│   │           ├── db_management.js   # DBManagementManager
│   │           ├── settings.js        # SettingsManager
│   │           └── sidebar.js         # SidebarManager
│   └── pipelines/                     # Hot-reload pipelines
│       ├── dnd/
│       │   ├── impl.py
│       │   └── rule_lookup.yaml
│       └── work/
│           ├── impl.py
│           └── work_lookup.yaml
│
├── rag-indexer/                       # Индексация документов
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── indexer_worker.py
│   ├── config.py
│   ├── config_loader.py
│   ├── logging_config.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── db_client.py               # Async DB client
│   │   ├── indexer_service.py         # Indexing logic
│   │   └── websocket_manager.py       # WS progress streaming
│   ├── embedding/
│   │   ├── __init__.py
│   │   ├── base_provider.py
│   │   ├── cache.py
│   │   ├── ollama_provider.py
│   │   └── openai_provider.py
│   └── parser/
│       ├── chunking/
│       │   ├── __init__.py
│       │   ├── embedding_enricher.py
│       │   ├── entity_chunker.py
│       │   └── generic_chunker.py
│       ├── parsing/
│       │   ├── __init__.py
│       │   ├── md_parser.py
│       │   └── pdf_parser.py
│       ├── preprocessing/
│       │   ├── __init__.py
│       │   ├── pdf_page_merger.py
│       │   └── preprocessor.py
│       ├── scanning/
│       │   └── vault_scanner.py
│       └── state/
│           ├── __init__.py
│           └── state_manager.py
│
├── db-api-server/                     # LanceDB HTTP wrapper
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   ├── config_loader.py
│   ├── logging_config.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── index.py                   # Index CRUD + search
│   └── storage/
│       ├── __init__.py
│       └── lancedb_store.py           # LanceDB operations
│
├── pdf-sidecar/                       # PDF parsing на macOS хосте
│   ├── README.md
│   ├── app.py
│   ├── parser.py
│   ├── preprocessor.py
│   ├── requirements.txt
│   ├── install.sh
│   ├── start.sh
│   └── status.sh
│
└── specs_update/                      # Технические спецификации
    ├── Spec-00-Architecture-Overview-artifact.md
    ├── Spec-01-Database-Foundation.md
    ├── Spec-02a-Settings-Services.md
    ├── Spec-02b-Settings-API.md
    ├── Spec-02c-Settings-API.md
    ├── Spec-03a-Indexer-DB-Client.md
    ├── Spec-03b-Indexer-Parser-and-Cleanup.md
    ├── Spec-04a-Retrieval-and-Pipeline-Service.md
    ├── Spec-04b-Pipeline-Executor.md
    ├── Spec-04c-Pipeline-Router-and-Chat-Integration.md
    ├── Spec-05a-Settings-UI-Foundation.md
    ├── Spec-05b-Settings-UI.md
    ├── Spec-05c-Settings-UI.md
    ├── Spec-06-Pipelines-And-Worlds-UI.md
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

**Назначение:** Выполнение декларативных pipelines

**Класс:** `PipelineExecutor`

**Ключевые методы:**
- `execute(pipeline_id, query, chat_context)` → AsyncGenerator[SSEEvent]
  - Выполняет шаги pipeline последовательно/параллельно
  - Генерирует SSE события progress/step_done/sources/token

#### `rag-backend/app/services/clarification_fsm.py`

**Назначение:** State machine для уточняющих вопросов

**Состояния:**
- `idle` — ожидание запроса
- `collecting` — сбор информации
- `complete` — достаточно данных
- `fallback` — переход к обычному ответу

**Ключевые методы:**
- `process_query(query, chat_id)` → ClarificationDecision
- `next_question()` → str
- `is_complete()` → bool

---

## 🗄️ Схема Базы Данных (PostgreSQL)

### Таблицы

#### 1. Домены и Промпты

```sql
-- domains - предметные области
CREATE TABLE domains (
    domain_id    VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(255) NOT NULL,
    description  TEXT,
    is_system    BOOLEAN DEFAULT FALSE,
    enabled      BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- domain_prompts - промпты для доменов
CREATE TABLE domain_prompts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id   VARCHAR(32) NOT NULL REFERENCES domains(domain_id) ON DELETE CASCADE,
    prompt_type VARCHAR(32) NOT NULL,  -- system, clarification, planner, pipeline_router
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_id, prompt_type)
);

-- domain_clarification_fields - поля для уточняющих вопросов
CREATE TABLE domain_clarification_fields (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id     VARCHAR(32) NOT NULL REFERENCES domains(domain_id) ON DELETE CASCADE,
    field_name    VARCHAR(64) NOT NULL,
    label         VARCHAR(255) NOT NULL,
    hint          TEXT,
    required      BOOLEAN DEFAULT TRUE,
    display_order INT DEFAULT 0,
    UNIQUE(domain_id, field_name)
);
```

#### 2. Настройки Платформы

```sql
-- platform_settings - runtime параметры
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

**Seed данные (16 параметров):**
- `retrieval.enabled` (bool) = true
- `retrieval.top_k` (int) = 10
- `retrieval.reranker_enabled` (bool) = false
- `chunking.chunk_size` (int) = 2000
- `chunking.overlap` (int) = 64
- `chunking.entity_aware_mode` (bool) = true
- `chat.max_clarification_turns` (int) = 3
- `chat.stream_answers` (bool) = true
- `chat.auto_title` (bool) = true
- `reranker.enabled` (bool) = false
- `reranker.provider` (str) = null
- `reranker.base_url` (str) = null
- `reranker.model_name` (str) = null
- `pdf_sidecar.url` (str) = "http://host.docker.internal:8765"
- `pdf_sidecar.timeout_seconds` (int) = 180
- `pdf_sidecar.fallback_to_pdfminer` (bool) = true

#### 3. Модели

```sql
-- generation_models - LLM для генерации ответов
CREATE TABLE generation_models (
    model_id          VARCHAR(128) PRIMARY KEY,
    provider          VARCHAR(32) NOT NULL DEFAULT 'openai_compatible',
    display_name      VARCHAR(255),
    base_url          VARCHAR(512) NOT NULL,
    encrypted_api_key TEXT,
    timeout_seconds   INT NOT NULL DEFAULT 60,
    is_active         BOOLEAN NOT NULL DEFAULT FALSE,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_generation_models_active 
ON generation_models(is_active) WHERE is_active = true;

-- embedding_models - модели для эмбеддингов
CREATE TABLE embedding_models (
    model_id        VARCHAR(128) PRIMARY KEY,
    provider        VARCHAR(32) NOT NULL,  -- ollama, openai_compatible
    display_name    VARCHAR(255),
    model_name      VARCHAR(255) NOT NULL,
    base_url        VARCHAR(512) NOT NULL,
    encrypted_api_key TEXT,
    dimensions      INT NOT NULL,
    timeout_seconds INT NOT NULL DEFAULT 30,
    max_retries     INT NOT NULL DEFAULT 3,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

#### 4. Vaults

```sql
-- vaults - хранилища документов
CREATE TABLE vaults (
    vault_id           VARCHAR(64) PRIMARY KEY,
    domain_id          VARCHAR(32) NOT NULL REFERENCES domains(domain_id),
    display_name       VARCHAR(255),
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    embedding_model_id VARCHAR(128) REFERENCES embedding_models(model_id),
    expected_dimensions INT,
    chunk_size         INT,
    overlap            INT,
    entity_aware_mode  BOOLEAN,
    binding_status     VARCHAR(16) NOT NULL DEFAULT 'unbound',
    chunk_count        INT NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_vaults_domain ON vaults(domain_id);
CREATE INDEX idx_vaults_enabled ON vaults(enabled);
```

#### 5. Чаты и Сообщения

```sql
-- chats - сессии чатов
CREATE TABLE chats (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              VARCHAR(512),
    vault_id           VARCHAR(64) REFERENCES vaults(vault_id),
    domain_id          VARCHAR(32) REFERENCES domains(domain_id),
    world_id           VARCHAR(64),
    locked_pipeline_id VARCHAR(64),
    pipeline_versions  JSONB,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

-- messages - сообщения в чатах
CREATE TABLE messages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id    UUID NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role       VARCHAR(16) NOT NULL,  -- user, assistant, system
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- clarification_states - FSM состояния уточнений
CREATE TABLE clarification_states (
    chat_id       UUID PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
    stage         VARCHAR(32) NOT NULL,  -- idle, collecting, complete, fallback
    missing_fields JSONB,
    collected     JSONB,
    turn          INT NOT NULL DEFAULT 0,
    next_question TEXT,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

#### 6. Worlds и Campaigns (DnD)

```sql
-- worlds - миры (контекстные группы)
CREATE TABLE worlds (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    world_id    VARCHAR(64) NOT NULL,
    vault_id    VARCHAR(64) NOT NULL REFERENCES vaults(vault_id),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    path_prefix VARCHAR(512) NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(world_id, vault_id)
);
CREATE INDEX idx_worlds_vault ON worlds(vault_id);

-- campaigns - кампании внутри миров
CREATE TABLE campaigns (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id VARCHAR(64) NOT NULL,
    world_id    VARCHAR(64) NOT NULL,
    vault_id    VARCHAR(64) NOT NULL REFERENCES vaults(vault_id),
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    path_prefix VARCHAR(512) NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(campaign_id, world_id)
);
```

#### 7. Pipelines

```sql
-- pipelines - декларативные pipeline'ы
CREATE TABLE pipelines (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id       VARCHAR(64) NOT NULL,
    domain_id         VARCHAR(32) NOT NULL REFERENCES domains(domain_id),
    version           VARCHAR(32) NOT NULL,
    name              VARCHAR(255) NOT NULL,
    steps             JSONB NOT NULL,
    final_composition JSONB NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(pipeline_id, domain_id)
);
CREATE INDEX idx_pipelines_domain ON pipelines(domain_id);
```

---

## 🔌 API Эндпоинты

### Chat API

| Метод | Endpoint | Описание | Request | Response |
|-------|----------|----------|---------|----------|
| POST | `/chat/create` | Создание чата | `{vault_id, domain_id, world_id?}` | `{chat_id, title}` |
| GET | `/chat/list?domain_id=` | Список чатов | - | `[ChatRecord]` |
| GET | `/chat/{chat_id}` | Чат с сообщениями | - | `ChatRecord + messages` |
| POST | `/chat/{chat_id}/message` | Отправка сообщения | `{content}` | SSE stream |
| PUT | `/chat/{chat_id}/rename` | Переименование | `{title}` | - |
| DELETE | `/chat/{chat_id}` | Удаление чата | - | - |
| POST | `/chat/{chat_id}/pipeline/lock` | Lock pipeline | `{pipeline_id}` | - |

### Settings API

| Метод | Endpoint | Описание | Request | Response |
|-------|----------|----------|---------|----------|
| GET | `/api/settings/params` | Параметры платформы | - | `[PlatformSetting]` |
| PUT | `/api/settings/param/{key}` | Обновить параметр | `{value}` | - |
| POST | `/api/settings/reset` | Сброс к дефолту | - | - |
| GET | `/api/settings/domains` | Список доменов | - | `[Domain]` |
| POST | `/api/settings/domains` | Создать домен | `{domain_id, display_name}` | `Domain` |
| PUT | `/api/settings/domains/{id}` | Обновить домен | `{display_name, enabled}` | - |
| DELETE | `/api/settings/domains/{id}` | Удалить домен | - | - |
| GET | `/api/settings/domains/{id}/prompts` | Промпты домена | - | `[Prompt]` |
| PUT | `/api/settings/domains/{id}/prompts/{type}` | Обновить промпт | `{content}` | - |
| GET | `/api/settings/domains/{id}/fields` | Поля уточнений | - | `[ClarificationField]` |
| PUT | `/api/settings/domains/{id}/fields` | Обновить поля | `[fields]` | - |
| GET | `/api/settings/models/generation` | Генеративные модели | - | `[GenerationModel]` |
| POST | `/api/settings/models/generation` | Создать модель | `{model_id, provider, base_url}` | `GenerationModel` |
| PUT | `/api/settings/models/generation/{id}` | Обновить модель | `{...}` | - |
| DELETE | `/api/settings/models/generation/{id}` | Удалить модель | - | - |
| POST | `/api/settings/models/generation/{id}/activate` | Активировать | - | - |
| GET | `/api/settings/models/embedding` | Embedding модели | - | `[EmbeddingModel]` |
| POST | `/api/settings/models/embedding` | Создать модель | `{model_id, provider, model_name}` | `EmbeddingModel` |
| PUT | `/api/settings/models/embedding/{id}` | Обновить модель | `{...}` | - |
| DELETE | `/api/settings/models/embedding/{id}` | Удалить модель | - | - |
| GET | `/api/settings/vaults` | Список vault'ов | - | `[Vault]` |
| POST | `/api/settings/vaults` | Создать vault | `{vault_id, domain_id}` | `Vault` |
| PUT | `/api/settings/vaults/{id}` | Обновить vault | `{display_name, enabled}` | - |
| DELETE | `/api/settings/vaults/{id}` | Удалить vault | - | - |
| GET | `/api/settings/worlds?vault_id=` | Миры vault'а | - | `[World]` |
| POST | `/api/settings/worlds` | Создать мир | `{world_id, vault_id, name}` | `World` |
| PUT | `/api/settings/worlds/{id}` | Обновить мир | `{name, description}` | - |
| GET | `/api/settings/campaigns?world_id=` | Кампании мира | - | `[Campaign]` |
| POST | `/api/settings/campaigns/{world_id}/toggle` | Toggle кампании | `{campaign_id}` | - |
| GET | `/api/settings/pipelines?domain_id=` | Pipelines домена | - | `[Pipeline]` |
| POST | `/api/settings/pipelines` | Создать pipeline | `{pipeline_id, domain_id, steps}` | `Pipeline` |
| PUT | `/api/settings/pipelines/{id}` | Обновить pipeline | `{steps, final_composition}` | - |

### DB Management API

| Метод | Endpoint | Описание | Request | Response |
|-------|----------|----------|---------|----------|
| GET | `/api/db/documents?vault_id=&limit=` | Документы vault'а | - | `[DocumentRecord]` |
| GET | `/api/db/chunks?document_id=&vault_id=` | Чанки документа | - | `[ChunkRecord]` |
| DELETE | `/api/db/documents/{id}?vault_id=` | Удалить документ | - | - |
| POST | `/api/db/search/text` | Текстовый поиск | `{vault_id, query_text, limit}` | `[SearchResult]` |
| POST | `/api/db/search/domain` | Поиск по домену | `{domain_id, query_text, limit}` | `[SearchResult]` |
| POST | `/vaults/{vault_id}/reindex` | Запуск индексации | `{force_reindex?}` | `{task_id}` |
| DELETE | `/index-tasks/{task_id}` | Отмена задачи | - | - |
| GET | `/index-tasks/{task_id}/state` | Статус задачи | - | `IndexState` |
| POST | `/vaults/{vault_id}/detach` | Открепить vault | - | - |

---

## 📦 Сущности Данных

### Domain

```python
Domain:
  - domain_id: str (PK)
  - display_name: str
  - description: str | None
  - is_system: bool
  - enabled: bool
  - created_at: datetime
  - updated_at: datetime
```

### Vault

```python
Vault:
  - vault_id: str (PK)
  - domain_id: str (FK)
  - display_name: str | None
  - enabled: bool
  - embedding_model_id: str | None
  - expected_dimensions: int | None
  - chunk_size: int | None
  - overlap: int | None
  - entity_aware_mode: bool | None
  - binding_status: Literal["unbound", "binding", "bound", "error"]
  - chunk_count: int
  - created_at: datetime
  - updated_at: datetime
```

### Chat

```python
ChatRecord:
  - chat_id: str (UUID)
  - title: str | None
  - vault_id: str | None
  - domain_id: str | None
  - world_id: str | None
  - locked_pipeline_id: str | None
  - pipeline_versions: dict[str, str]
  - created_at: datetime
  - updated_at: datetime

ChatMessage:
  - message_id: str (UUID)
  - chat_id: str (FK)
  - role: Literal["user", "assistant", "system"]
  - content: str
  - created_at: datetime
```

### Pipeline

```python
PipelineStep:
  - order: int
  - type: Literal["book", "world", "campaign"]
  - name: str
  - role: Literal["methodology", "lore", "campaign_context", "character_sheet", "session_log", "rules"]
  - system_prompt: str
  - top_k: int | None
  - document_ids: list[str] | None
  - world_id: str | None

PipelineRead:
  - pipeline_id: str
  - domain_id: str
  - version: str
  - name: str
  - steps: list[PipelineStep]
  - final_composition: FinalComposition
  - is_active: bool
```

### SearchResult

```python
SearchResult:
  - chunk_id: str
  - document_path: str
  - page_number: int | None
  - chunk_index: int
  - text: str
  - embedding_text: str | None
  - score: float
  - metadata: dict
```

### WebSocket сообщения

```python
WSFileChunkProgressMessage:
  - type: "file_chunk_progress"
  - task_id: str
  - file_path: str
  - stage: Literal["parsing", "chunking", "indexing", "done", "error"]
  - chunks_total: int
  - chunks_processed: int

WSTaskCompleteMessage:
  - type: "task_complete"
  - task_id: str
  - files_total: int
  - files_indexed: int
```

---

## ⚙️ Конфигурация

### config/config.yaml

Основные секции:

```yaml
vaults:
  dnd-main:
    vault_id: "dnd-main"
    domain_id: "dnd"
    path: "/data/vaults/dnd"
    enabled: true

embedding_models:
  nomic-local:
    model_id: "nomic-local"
    provider: "ollama"
    model_name: "nomic-embed-text"
    base_url: "http://host.docker.internal:11434"
    dimensions: 768
    enabled: true

generation_models:
  deepseek:
    model_id: "deepseek-chat"
    provider: "openai_compatible"
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
    enabled: true

chat:
  max_clarification_turns: 3
  stream_answers: true
  auto_title: true

retrieval:
  enabled: true
  top_k: 10
  reranker_enabled: false

chunking:
  chunk_size: 2000
  overlap: 64
  entity_aware_mode: true

pipelines:
  enabled: true
  path: "/app/pipelines"
  reload_interval_seconds: 2.0

ui:
  db_management_enabled: true

pdf_sidecar:
  url: "http://host.docker.internal:8765"
  timeout_seconds: 180
  fallback_to_pdfminer: true
```

### Environment Variables

```bash
DATABASE_URL=postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform
ENCRYPTION_KEY=<fernet-key-32-bytes>
STORAGE_API_URL=http://db-api-server:8080
INDEXER_API_URL=http://rag-indexer:9000
DB_API_URL=http://db-api-server:8080
OPENAI_API_KEY=<your-key>
SERVICE_PORT=8000
```

---

## 🔄 Основные Процессы

### 1. Индексация документа

```
User → POST /vaults/{vault_id}/reindex
  ↓
rag-backend → POST {INDEXER_API_URL}/tasks/index
  ↓
rag-indexer (background task)
  1. Scan vault directory for new/modified files
  2. For each file:
     a. Parse (MD/PDF via pdf-sidecar or pdfminer)
     b. Preprocess (merge pages, detect headings)
     c. Chunk (entity-aware, heading-aware)
     d. Enrich (build embedding_text)
     e. Embed (via Ollama/OpenAI)
     f. Upsert to LanceDB via db-api-server
  3. Update chunk_count in PostgreSQL
  4. Send WebSocket progress updates
  ↓
SSE/WebSocket events → UI progress bar
```

### 2. Отправка сообщения в чат

```
User → POST /chat/{chat_id}/message (SSE)
  ↓
rag-backend
  1. Load chat history from DB
  2. Check clarification FSM (если active domain)
  3. Если clarification нужен → задать вопрос
  4. Иначе:
     a. Retrieve chunks (multi-vault, если domain)
     b. Выбрать pipeline (router или locked)
     c. Выполнить pipeline steps:
        - Retrieve по каждому шагу
        - Build context per step
     d. Call LLM (GenerationProvider.generate())
     e. Stream tokens via SSE
  5. Save assistant message to DB
  6. SSE events:
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

## 🔍 Работа с параметрами

### Query-параметры URL

- **Чаты:** `/chat/list?domain_id=dnd` — фильтрация по домену
- **Поиск:** `/api/db/documents?vault_id=dnd-main&limit=50`
- **Миры:** `/api/settings/worlds?vault_id=dnd-main`

### Хранение фильтров/пагинации

- **Фильтры доменов/миров:** В состоянии SidebarManager (frontend)
- **Пагинация документов:** Через `limit` параметр в API
- **Состояние чата:** В localStorage (current_chat_id, current_domain_id)

### Формирование запросов к бэкенду

Все API запросы формируются в `api.js` через обёртку `fetch`:

```javascript
// Пример: поиск по домену
async searchTextByDomain(domainId, queryText, limit = 20) {
    const response = await this.fetch('/api/db/search/domain', {
        method: 'POST',
        body: JSON.stringify({
            domain_id: domainId,
            query_text: queryText,
            limit: limit
        })
    });
    return response.json();
}
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

#### Проблема: Clarification FSM не задаёт вопросы

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

## 📋 Алгоритм работы для ИИ

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

## 🚀 Инструкция по запуску локально

### Требования

- Docker + Docker Compose
- macOS (для pdf-sidecar) или настроенный pdf-sidecar в Docker
- Ollama с моделью nomic-embed-text (опционально)

### Быстрый старт

```bash
# 1. Клонировать репозиторий
cd /workspace

# 2. Создать .env файл
cat > .env << EOF
DATABASE_URL=postgresql+asyncpg://raguser:changeme@rag-db:5432/ragplatform
ENCRYPTION_KEY=<generate-fernet-key>
STORAGE_API_URL=http://db-api-server:8080
INDEXER_API_URL=http://rag-indexer:9000
OPENAI_API_KEY=<your-key>
SERVICE_PORT=8000
EOF

# 3. Запустить все сервисы
docker compose up -d

# 4. Проверить логи
docker compose logs -f rag-backend rag-indexer

# 5. Открыть UI
# http://localhost:8000
```

### Генерация ENCRYPTION_KEY

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### Проверка здоровья

```bash
# Health check
curl http://localhost:8000/health

# Swagger UI
open http://localhost:8000/docs
```

### Пересборка после изменений

```bash
# Пересобрать конкретный сервис
docker compose up -d --build rag-backend

# Пересобрать все
docker compose up -d --build
```

---

## 🔗 Ссылки

- **OpenAPI Docs:** `http://localhost:8000/docs`
- **Web UI:** `http://localhost:8000`
- **Спецификации:** `/workspace/specs_update/`

---

**Конец файла контекста.**
