# Фронтенд — структура и архитектура

## Общее

Фронтенд — это **ванильный JavaScript SPA** (не Vue-build, не React).
Нет компонентных фреймворков — чистый JS с DOM-манипуляциями, модульная структура через отдельные файлы.

- Раздаётся FastAPI из `rag-backend/app/static/`
- Единственный HTML-файл: `index.html` (все страницы внутри одного HTML)
- Сборка не нужна — файлы подключаются напрямую через `<script src>`

## Структура файлов

```
rag-backend/app/static/
├── index.html                  # Единственный HTML, вся разметка страниц
├── css/
│   ├── base.css                # Глобальные переменные, reset, типографика
│   ├── sidebar.css             # Боковая панель: домен, кампания, список чатов
│   ├── chat-area.css           # Основная область чата: сообщения, инпут
│   ├── markdown.css            # Стили рендеринга Markdown в сообщениях
│   ├── settings.css            # Страница настроек: табы, карточки, формы
│   ├── models.css              # Карточки моделей (generation, embedding, rerank)
│   ├── db-management.css       # Модальное окно поиска по хранилищу
│   └── pipeline-cards.css      # Карточки/плитки pipeline_builder
└── js/
    ├── api.js                  # Все HTTP-запросы к backend (34KB)
    ├── chat.js                 # Логика чата: сообщения, стриминг, FSM (40KB)
    ├── sidebar.js              # Боковая панель: список чатов, домен, кампания (21KB)
    ├── settings.js             # Орчестратор страницы настроек, переключение табов (22KB)
    ├── pipeline_builder.js     # DAG-редактор пайплайнов (40KB)
    ├── pending-banner.js       # Баннер ожидания/паузы пайплайна (7KB)
    ├── db_management.js        # Модальный поиск по LanceDB (11KB)
    └── settings/               # Табы страницы настроек
        ├── tab-domains.js          # Таб Домены (15KB)
        ├── tab-vaults.js           # Таб Vault'ы (5KB)
        ├── tab-models.js           # Оркестратор подтабов моделей (8KB)
        ├── tab-gen-models.js       # Подтаб Generation (5KB)
        ├── tab-emb-models.js       # Подтаб Embedding (4.5KB)
        ├── tab-rerank-models.js    # Подтаб Rerank (14KB)
        ├── tab-params.js           # Таб Параметры платформы (9.8KB)
        ├── tab-pipelines.js        # Таб Pipelines (список) (4.5KB)
        ├── tab-campaigns.js        # Таб Кампании (16KB)
        ├── tab-documents.js        # Таб Documents (самый большой, 49KB)
        └── tag-badge.js            # Шард тега (загружать ДО кампаний/документов!)
```

## Разметка страниц (index.html)

### Главный экран — Чат

Активен по умолчанию. Состоит из `div.app-container`:

```
.app-container
├── aside.sidebar                       # Боковая панель
│   ├── .sidebar-header
│   │   ├── #settings-btn               # Переход на страницу настроек
│   │   ├── #db-mgmt-btn                # Открывает модал поиска по LanceDB
│   │   ├── #domain-select              # <select> домена
│   │   ├── #campaign-selector          # <select> кампании (hidden по умолчанию)
│   │   └── #new-chat-btn               # Создать чат
│   └── #chat-list                  # Список чатов (динамически наполняется)
└── main.chat-main
    ├── .chat-header / #chat-title
    ├── #chat-context-bar (.hidden)     # Полоса с названием кампании + pipeline-select
    │   ├── #context-campaign           # Название кампании
    │   ├── #pipeline-select            # Выбор pipeline (Авто | фиксированный)
    │   ├── #lock-pipeline-btn          # Блокировка pipeline для чата
    │   └── #chat-banner-area           # Слот для pending-banner
    ├── #messages-container             # Основной скроль сообщений
    ├── #status-banner (.hidden)        # Статус-баннер (индексация, ошибки)
    └── #input-area (display:none)      # textarea + кнопка отправки
```

### Страница настроек

Скрыта по умолчанию (`.hidden`), показывается поверх всего:

```
main#settings-page
├── .settings-header + #back-to-chat-btn
├── nav.settings-tabs                   # 7 кнопок (домены, ваулты, модели, параметры, pipelines, campaigns, documents)
└── #settings-content                   # Контент активного таба (динамически заменяется)
```

### Модальные окна (3 шт.)

| ID | Назначение |
|---|---|
| `#rename-modal` | Переименование чата |
| `#db-mgmt-modal` | Поиск по хранилищу (LanceDB), выбор домена, запрос, лимит |
| `#chunk-detail-modal` | Детальный просмотр чанка |

## JS-модули — ответственность и главные объекты

### `api.js` — HTTP-клиент (34KB)

Единая точка взаимодействия с backend. Все другие модули используют только `api.js`, не `fetch()` напрямую.

```javascript
// Главный объект:
window.MercerAPI = {
  // Чаты
  getChats(), createChat(domainId, campaignId?), deleteChat(chatId),
  renameChat(chatId, title), updateChat(chatId, data),

  // Сообщения
  getMessages(chatId), clearMessages(chatId),

  // Отправка — стриминг через fetch() + ReadableStream
  sendMessage(chatId, text, onChunk, onDone, onError),

  // Pipeline
  getChatPipelineStatus(chatId),
  confirmPipeline(chatId, token),
  resumePipeline(chatId, token, answer),
  cancelPipeline(chatId),

  // Clarification
  getClarificationState(chatId),
  resetClarification(chatId),

  // Домены
  getDomains(), createDomain(), updateDomain(), deleteDomain(),
  getDomainPrompts(), updateDomainPrompt(),
  getClarificationFields(), createClarificationField(), deleteClarificationField(),

  // Vaults
  getVaults(), createVault(), updateVault(), deleteVault(),
  bindVault(vaultId, embModelId), unbindVault(vaultId),

  // Documents
  getDocuments(filters?), deleteDocument(), reindexDocuments(),

  // Модели
  getGenerationModels(), createGenModel(), updateGenModel(), deleteGenModel(), activateGenModel(),
  getEmbeddingModels(), createEmbModel(), updateEmbModel(), deleteEmbModel(),
  getRerankModels(), createRerankModel(), updateRerankModel(), deleteRerankModel(), activateRerankModel(),

  // Настройки
  getParams(), updateParam(key, value),

  // Pipelines
  getPipelines(), createPipeline(), updatePipeline(), deletePipeline(),

  // Кампании
  getCampaigns(), createCampaign(), updateCampaign(), deleteCampaign(),

  // Теги
  getTags(domainId?), createTag(), deleteTag(),

  // Indexer
  getIndexerState(vaultId), triggerWatchdog(),

  // DB search
  searchDb(domainId, query, limit),
}
```

Стриминг реализован через `fetch()` + `ReadableStream`, постеповое чтение SSE-подобных кусков.

---

### `chat.js` — логика чата (40KB)

Главный модуль. Инициализирует всё приложение (`initApp()` в `DOMContentLoaded`).

**Ответственность:**
- Открытие/закрытие чата, лента сообщений
- Отправка сообщения, обработка стримингового ответа
- Рендеринг Markdown (через `marked` + `DOMPurify` + `highlight.js`)
- Рендеринг сообщений ролей `user` / `assistant`
- Управление `#pipeline-select` и `#lock-pipeline-btn`
- Отображение clarification-вопросов как обычных сообщений
- Глобальное состояние: `window.currentChatId`, `window.currentDomainId`

**Отображение сообщений:**
- Markdown рендерится в реальном времени стрима (каждый `onChunk` обновляет DOM)
- Код подсвечивается через `highlight.js` по завершении стрима
- Сообщения пользователя и assistant отображаются различными CSS-классами

---

### `sidebar.js` — боковая панель (21KB)

**Ответственность:**
- Загрузка доменов в `#domain-select`
- Загрузка кампаний при выборе домена (показать/скрыть `#campaign-selector`)
- Рендеринг списка чатов `#chat-list`
- Контекстное меню (правая кнопка): переименовать, удалить чат
- При смене домена — обновление списка чатов + настройка контекстной полосы
- Глобальные: `window.currentDomainId`, `window.currentCampaignId`

---

### `settings.js` — оркестратор настроек (22KB)

**Ответственность:**
- Переключение между страницей чата и страницей настроек
- Рендеринг содержимого таба в `#settings-content`
- Делегирует каждому `tab-*.js`-модулю: `renderTab(tabName)`
- Хранит текущий активный таб: `window.activeSettingsTab`

**Порядок загрузки `<script>` в `index.html` критичен!**
Таб-модули зависят от `api.js` и `settings.js`, поэтому загружаются в таком порядке:
```
api.js → pipeline_builder.js → settings.js → tab-*.js → tag-badge.js → tab-campaigns.js → tab-documents.js
→ pending-banner.js → chat.js → sidebar.js → db_management.js
```

---

### `pipeline_builder.js` — DAG-редактор (40KB)

Визуальный редактор пайплайнов. Используется в вкладке "Pipelines" страницы настроек.

- Рендерит шаги пайплайна как дрег карточек (CSS-грид/стрелки)
- Отредактировать шаг: тип (`retrieval`, `generation`, `validation`, `planner`), параметры, `depends_on`
- Добавить/удалить шаг, изменить `final_composition`
- Сериализует пайплайн в JSON и отправляет через `api.js`
- Использует `pipeline-cards.css`

---

### `pending-banner.js` — баннер пайплайна (7KB)

Отображается в `#chat-banner-area` внутри контекст-бара.

- Регулярно поллит `GET /api/pipeline/{chat_id}/status`
- Если `pending_pipeline_confirm` != null — показывает баннер с кнопками «Подтвердить» / «Отменить»
- Если `pipeline_pause_state` != null — показывает баннер с полем ввода и кнопкой «Продолжить»
- Вызывает `api.confirmPipeline()` / `api.resumePipeline()` / `api.cancelPipeline()`

---

### `db_management.js` — поиск по LanceDB (11KB)

- Вязан на модальное окно `#db-mgmt-modal`
- Заполняет `#search-domain-select` из доменов
- `searchDb(domainId, query, limit)` → отображает `#search-results` карточками чанков
- Клик на чанк → открывает `#chunk-detail-modal` с полным текстом + метаданными

---

## Вкладки страницы настроек

| Таб (`data-tab`) | Файл | Содержание |
|---|---|---|
| `domains` | `tab-domains.js` | CRUD доменов, редактор промптов (4 типа), ClarificationFields |
| `vaults` | `tab-vaults.js` | CRUD ваултов, bind/unbind embedding-модель |
| `models` | `tab-models.js` + подтабы | Подтабы: Generation / Embedding / Rerank |
| `params` | `tab-params.js` | Редактирование PlatformSetting (сгруппированные по group_name) |
| `pipelines` | `tab-pipelines.js` + `pipeline_builder.js` | Список + DAG-редактор |
| `campaigns` | `tab-campaigns.js` | CRUD кампаний, привязка тегов |
| `documents` | `tab-documents.js` | Просмотр документов, фильтры, статусы, reindex |

## CDN-зависимости

| Библиотека | Версия | Назначение |
|---|---|---|
| `marked` | 12.0.0 | Парсер Markdown → HTML |
| `DOMPurify` | 3.1.0 | Санитация HTML (XSS-защита) |
| `highlight.js` | 11.9.0 | Подсветка кода (python, js, bash, json, yaml, sql) |

## Глобальные переменные `window.*`

| Переменная | Тип | Источник |
|---|---|---|
| `window.MercerAPI` | Object | `api.js` — весь HTTP-клиент |
| `window.currentChatId` | string/null | `chat.js` |
| `window.currentDomainId` | string | `sidebar.js` |
| `window.currentCampaignId` | string/null | `sidebar.js` |
| `window.activeSettingsTab` | string | `settings.js` |

## Особенности архитектуры

1. **Нет роутера** — переключение страниц = toggle `.hidden` на DOM-элементах.
2. **Нет стейта** — данные хранятся в `window.*` и передаются через них между модулями.
3. **Один CSS-файл / один JS-файл** — тематическое разделение по зонам приложения.
4. **Стриминг** — `fetch()` + `ReadableStream`, не `EventSource`. Ответ читается постепенно.
5. **Сборка не нужна** — добавление нового JS/CSS = подключить в `index.html` + обязательно соблюдать порядок загрузки.
6. **`tag-badge.js`** должен быть загружен ДО `tab-campaigns.js` и `tab-documents.js` — они импортируют его функции.
