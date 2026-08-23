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
    ├── api.js                  # Главный HTTP-клиент — обратная совместимость; агрегатор
    ├── api/                    # Модули HTTP-клиента по доменам (используются index.html)
    │   ├── index.js            # Сборка window.MercerAPI из модулей
    │   ├── chat.js             # Чаты, сообщения, стриминг, pipeline-статус
    │   ├── campaigns.js        # CRUD кампаний + Campaign State API
    │   ├── documents.js        # Документы, reindex
    │   ├── domains.js          # Домены, промпты, clarification fields
    │   ├── models.js           # Generation / Embedding / Rerank модели
    │   ├── pipeline.js         # Pipeline confirm/resume/cancel/status
    │   ├── search.js           # Поиск по LanceDB (db search)
    │   ├── settings.js         # PlatformSettings (params)
    │   ├── sidecar.js          # Управление pdf-sidecar через host-agent
    │   ├── update-mode.js      # Campaign Update Mode (start/session/review/apply)
    │   └── vaults.js           # Vaults, bind/unbind
    ├── chat.js                 # Логика чата: сообщения, стриминг, FSM (45KB)
    ├── sidebar.js              # Боковая панель: список чатов, домен, кампания (24KB)
    ├── settings.js             # Орчестратор страницы настроек, переключение табов (21KB)
    ├── pipeline_builder.js     # DAG-редактор пайплайнов (40KB)
    ├── pending-banner.js       # Баннер ожидания/паузы пайплайна (7KB)
    ├── db_management.js        # Модальный поиск по LanceDB (11KB)
    ├── update-mode.js          # UI обёртка для Campaign Update Mode (review/apply)
    └── settings/               # Табы страницы настроек
        ├── tab-domains.js          # Таб Домены (15KB)
        ├── tab-vaults.js           # Таб Vault'ы (5.8KB)
        ├── tab-models.js           # Оркестратор подтабов моделей (9.8KB)
        ├── tab-gen-models.js       # Подтаб Generation (5KB)
        ├── tab-emb-models.js       # Подтаб Embedding (7.8KB)
        ├── tab-rerank-models.js    # Подтаб Rerank (14KB)
        ├── tab-params.js           # Таб Параметры платформы (20KB)
        ├── tab-pipelines.js        # Таб Pipelines (список) (4.3KB)
        ├── tab-campaigns.js        # Таб Кампании (16KB) — вызывает InitialState / StateFields
        ├── tab-documents.js        # Таб Documents (самый большой, 49KB)
        ├── domain-rail.js          # Шард домен-rail в сайдбаре
        ├── initial-state.js        # UI Initial State (Stage 3): выбор .md → preview → apply
        ├── initial-state-wizard.js # Альтернативный wizard Initial State
        ├── state-fields.js         # UI Field Configuration Campaign State (Stage 1)
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

### `api.js` + `api/` — HTTP-клиент

Единая точка взаимодействия с backend. `api.js` — агрегатор, подключает все модули из `js/api/`.
Все другие модули используют только `window.MercerAPI`, не `fetch()` напрямую.

Модули в `js/api/` разбиты по доменам:

```javascript
// Главный объект (собирается в api/index.js):
window.MercerAPI = {
  // Чаты (api/chat.js)
  getChats(), createChat(domainId, campaignId?), deleteChat(chatId),
  renameChat(chatId, title), updateChat(chatId, data),

  // Сообщения (api/chat.js)
  getChatHistory(chatId),                                  // алиас для getChat; history endpoint

  // Отправка — стриминг через fetch() + ReadableStream
  sendMessage(chatId, text, onChunk, onDone, onError),

  // Pipeline (api/pipeline.js)
  getChatPipelineStatus(chatId),
  confirmPipeline(chatId, token),
  resumePipeline(chatId, token, answer),
  cancelPipeline(chatId),

  // Clarification (api/chat.js) — submitClarification активен;
  // getClarificationState/updateClarificationState помечены как legacy (бэкенд не предоставляет /clarification endpoint)
  submitClarification(chatId, clarificationId, answers),

  // Домены (api/domains.js)
  getDomains(), createDomain(), updateDomain(), deleteDomain(),
  getDomainPrompts(), updateDomainPrompt(),
  getClarificationFields(), createClarificationField(), deleteClarificationField(),

  // Vaults (api/vaults.js)
  getVaults(), createVault(), updateVault(), deleteVault(),
  toggleVault(vaultId),                                  // bind/unbind через единый toggle

  // Documents (api/documents.js)
  getDocuments(filters?), deleteDocument(), reindexDocuments(),

  // Модели (api/models.js)
  getGenerationModels(), createGenModel(), updateGenModel(), deleteGenModel(), activateGenModel(),
  getEmbeddingModels(), createEmbModel(), updateEmbModel(), deleteEmbModel(),
  getRerankModels(), createRerankModel(), updateRerankModel(), deleteRerankModel(), activateRerankModel(),

  // Настройки (api/settings.js)
  getParams(), updateParam(key, value),

  // Pipelines (api/pipeline.js)
  getPipelines(), createPipeline(), updatePipeline(), deletePipeline(),

  // Кампании (api/campaigns.js)
  getCampaigns(), createCampaign(), updateCampaign(), deleteCampaign(),
  // Campaign State (Stage 1) — api/campaigns.js
  getStateFields(campaignId), createStateField(campaignId, payload),
  updateStateField(campaignId, fieldId, payload),
  deleteStateField(campaignId, fieldId), reorderStateFields(campaignId, ids),
  // Campaign State (Stage 2) — active state + patch
  getActiveCampaignState(campaignId),
  // Campaign State (Stage 3) — Initial
  previewInitialState(campaignId, documentIds), getInitialStateProposal(campaignId),
  applyInitialState(campaignId, proposalId, configVersion),
  // Campaign State (Stage 6) — debug
  getEffectiveContext(campaignId, chatId?),
  // Campaign State (Stage 7) — stale
  getStateStaleStatus(campaignId),
  // Campaign Update Mode (api/update-mode.js) — отдельный модуль
  startUpdateMode(chatId, note), getUpdateModeSession(chatId),
  reviewUpdateMode(chatId, decisions), applyUpdateMode(chatId, applyId),
  cancelUpdateMode(chatId),

  // Теги (api/domains.js или отдельный модуль)
  getTags(domainId?), createTag(), deleteTag(),

  // Indexer (api/chat.js)
  getIndexerState(vaultId), triggerWatchdog(),

  // DB search (api/search.js)
  searchDb(domainId, query, limit),

  // Sidecar (api/sidecar.js)
  getSidecarStatus(), startSidecar(), stopSidecar(), restartSidecar(), installSidecarStream(),
}
```

Стриминг реализован через `fetch()` + `ReadableStream`, постепенное чтение SSE-подобных кусков.

---

### `chat.js` — логика чата (45KB)

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

### `sidebar.js` — боковая панель (24KB)

**Ответственность:**
- Загрузка доменов в `#domain-select`
- Загрузка кампаний при выборе домена (показать/скрыть `#campaign-selector`)
- Рендеринг списка чатов `#chat-list`
- Контекстное меню (правая кнопка): переименовать, удалить чат
- При смене домена — обновление списка чатов + настройка контекстной полосы
- Глобальные: `window.currentDomainId`, `window.currentCampaignId`

---

### `settings.js` — оркестратор настроек (21KB)

**Ответственность:**
- Переключение между страницей чата и страницей настроек
- Рендеринг содержимого таба в `#settings-content`
- Делегирует каждому `tab-*.js`-модулю: `renderTab(tabName)`
- Хранит текущий активный таб: `window.activeSettingsTab`

**Порядок загрузки `<script>` в `index.html` критичен!**
Таб-модули зависят от `api.js` и `settings.js`, поэтому загружаются в таком порядке:
```
api/index.js → api/*.js → api.js → pipeline_builder.js → settings.js → tab-*.js
→ tag-badge.js → initial-state.js → state-fields.js → tab-campaigns.js
→ tab-documents.js → pending-banner.js → chat.js → sidebar.js
→ db_management.js → update-mode.js
```

`initial-state.js` и `state-fields.js` должны быть загружены **ДО**
`tab-campaigns.js` (последний вызывает `window.InitialState.open()` и
`window.StateFields.*` из обработчиков кнопок в карточке кампании).

---

### `pipeline_builder.js` — DAG-редактор (40KB)

Визуальный редактор пайплайнов. Используется во вкладке "Pipelines" страницы настроек.

- Рендерит шаги пайплайна как drag-карточки (CSS-грид/стрелки)
- Отредактировать шаг: тип (`retrieval`, `validation`), параметры, `depends_on`
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
| `vaults` | `tab-vaults.js` | CRUD ваултов, toggle embedding-модели |
| `models` | `tab-models.js` + подтабы | Подтабы: Generation / Embedding / Rerank |
| `params` | `tab-params.js` | Редактирование PlatformSetting (сгруппированные по group_name) |
| `pipelines` | `tab-pipelines.js` + `pipeline_builder.js` | Список + DAG-редактор |
| `campaigns` | `tab-campaigns.js` + `initial-state.js` + `state-fields.js` | CRUD кампаний, привязка тегов, **Campaign State UI**: конфигурация полей, Initial State wizard, версии и patch-операции, Effective Context debug, stale indicator |
| `documents` | `tab-documents.js` | Просмотр документов, фильтры, статусы, reindex |

### Campaign State UI

Карточка кампании в `tab-campaigns.js` интегрирует несколько модулей:

#### Поля Campaign State (Stage 1) — `state-fields.js`

- CRUD по `state-fields`: добавление/редактирование/удаление полей, режим `single | list`,
  порядок (`display_order`), флаг `enabled`.
- Кнопка reorder открывает drag-and-drop интерфейс.
- Удаление поля требует подтверждения (cascade-purge: «Удаление очистит значение
  в активной версии state»).
- Бейдж «конфигурация обновлена» появляется, если `config_version` изменился.

#### Initial State (Stage 3) — `initial-state.js` / `initial-state-wizard.js`

Полноэкранный overlay с тремя фазами:

1. **Select** — выбор Markdown-документов кампании. Перед загрузкой
   документов Wizard собирает ID тегов кампании через
   `getCampaignTags(campaignId)` + `getCampaignGlobalTags(campaignId)`
   и передаёт их как `tagIds` в `getSettingsDocuments` —
   `GET /api/settings/documents?domain_id=...&tag_id=u1&tag_id=u2&tag_id=u3&status=indexed`.
   Документы фильтруются по тегам кампании (OR-логика), а не по всему домену.
   - Если у кампании 0 тегов (ни своих, ни подключённых глобальных) —
     показывается баннер «Initial State недоступен», Wizard не открывается,
     кнопка «Сформировать начальный контекст» скрыта в карточке кампании
     (`initial-state.js`).
   - Под полем поиска отображается подсказка с числом тегов кампании.
   - Счётчик токенов с предупреждением, если > 64 000.
   - Изменение чекбокса документа обновляет счётчики и прогресс-бар
     точечно (через `_updateBudgetView`), без полного перерендера списка —
     это сохраняет `scrollTop` контейнера `.iswizard__docs` (иначе
     список «прыгал» в начало при каждом клике).
2. **Review** — diff по полям (`proposed` / `empty` / `needs_clarification`),
   свёрнутый source snapshot, warnings. В фоне проверяется свежесть
   `Document.md5` против snapshot — если расхождение, показывается баннер
   «Источники изменились».
   - **Inline-edit:**
     - Single-поля: кнопка «Изменить» открывает textarea, «Сохранить»/«Отменить».
     - List-поля: у каждого элемента кнопки ✎ (edit) и 🗑 (remove);
       под списком — кнопка «+ Добавить элемент». `source_refs` остаются
       зафиксированными от LLM, не редактируются.
   - Валидация: text ≥ 1, ≤ 8192 (как в `CampaignStateInitialSingleValue.text`
     и `CampaignStateInitialListItem.text`).
3. **Apply** — `POST /state/initial/apply` с телом
   `{ proposal_id, config_version, proposal_overrides? }`.
   `proposal_overrides` — частичный proposal (по `field_key`),
   сформированный из текущего состояния `ctx.proposal.proposal` в Wizard.
   Бэкенд мерджит его поверх proposal, лежащего в Redis. Обрабатывает
   все коды ошибок бэкенда: `initial_already_applied`, `source_snapshot_stale`,
   `proposal_expired`, `503 generation_provider_unavailable`.
   - Баннер ошибки с кнопкой `×` (dismiss) работает в любом стейте, где
     он показан (`select_documents`, `review`, `result`).

При успехе показывается финальное сообщение и карточка кампании заменяет
кнопку на badge «Initial State применён» через `loadTab('campaigns')`.

#### Patch и версии (Stage 2)

- Список `state/versions` с метаданными (`state_version`, `config_version`,
  `source_kind`, `created_at`, `created_by`).
- Inline-редактор патча через `state/patch` с поддержкой частичного apply.

#### Effective Context debug (Stage 6)

Кнопка «Debug effective context» открывает оверлей с результатом
`GET /api/settings/campaigns/{id}/effective-context?chat_id=...`: блоки
`system_prompt`, `campaign_state`, `rag_context`, `history`, `user_message`,
метрики `total_tokens`, `budget`, `truncated_fields`. Не выполняет retrieval
и не вызывает LLM.

#### Stale indicator (Stage 7)

Бейдж «В источниках появились обновления» появляется, если
`GET /api/settings/campaigns/{id}/state/stale-status` возвращает
`potentially_stale=true`. По клику открывается Action «Обновить контекст»,
который переключает на chat этой кампании и предлагает запустить Campaign Update Mode.

### Update Mode UI — `update-mode.js`

`api/update-mode.js` (новый модуль; старый метод в `api.js` помечен как legacy
и фактически не загружается `index.html`) отправляет PATCH в правильной форме:

```javascript
// api/update-mode.js
reviewUpdateMode(chatId, {
  accepted_change_ids: [...],
  rejected_change_ids: [...],
  state_patch_decisions: {
    accepted_op_indexes: [...],
    rejected_op_indexes: [...],
    edited: [{ op_index, text }],
  },
})
```

UI review-сессии в `js/update-mode.js` показывает:

- Список файловых change-ов с unified diff и кнопками «принять / отклонить».
- Список state-patch операций с человеко-читаемой формулировкой:
  ```
  Изменить: Текущая локация
  Было:    Порт Соляных Врат
  Станет:  Руины маяка на острове Керн
  Основание: session-14.md
  ```
- Операции удаления/закрытия (`clear_single`, `resolve_list_item`,
  `remove_list_item`) визуально выделены и по умолчанию НЕ выбраны.
- Inline-редактор текста для replace_single / update_list_item / add_list_item.

### Conditional / cyclic RAG индикатор

Чат отображает badge «поиск» во время tool-цикла: пока host выполняет
`search_knowledge`, в сообщении ассистента показывается анимация и
`queries_used`. По завершении рендерится финальный ответ, а в debug-панели
(`/effective-context`) видны блоки `rag_context` (если был retrieval).

## CDN-зависимости

| Библиотека | Версия | Назначение |
|---|---|---|
| `marked` | 12.0.0 | Парсер Markdown → HTML |
| `DOMPurify` | 3.1.0 | Санитация HTML (XSS-защита) |
| `highlight.js` | 11.9.0 | Подсветка кода (python, js, bash, json, yaml, sql) |

## Глобальные переменные `window.*`

| Переменная | Тип | Источник |
|---|---|---|
| `window.MercerAPI` | Object | `api.js` + `api/*.js` — весь HTTP-клиент |
| `window.currentChatId` | string/null | `chat.js` |
| `window.currentDomainId` | string | `sidebar.js` |
| `window.currentCampaignId` | string/null | `sidebar.js` |
| `window.activeSettingsTab` | string | `settings.js` |

## Особенности архитектуры

1. **Нет роутера** — переключение страниц = toggle `.hidden` на DOM-элементах.
2. **Нет стейта** — данные хранятся в `window.*` и передаются через них между модулями.
3. **Тематическое разделение** — CSS и JS по зонам приложения; API-слой разбит на отдельные файлы в `js/api/`.
4. **Стриминг** — `fetch()` + `ReadableStream`, не `EventSource`. Ответ читается постепенно.
5. **Сборка не нужна** — добавление нового JS/CSS = подключить в `index.html` + обязательно соблюдать порядок загрузки.
6. **`tag-badge.js`** должен быть загружен ДО `tab-campaigns.js` и `tab-documents.js` — они импортируют его функции.
7. **`initial-state.js`** должен быть загружен ДО `tab-campaigns.js` — последний вызывает `window.InitialState.open()` из обработчика кнопки в карточке кампании.
8. **`state-fields.js`** должен быть загружен ДО `tab-campaigns.js` — последний вызывает `window.StateFields.*` для управления полями.
9. **`api/update-mode.js`** — модульный mixin для Update Mode review/apply; загружается через `api/index.js` и собирается в `window.MercerAPI`. Старая синхронная версия в `api.js` оставлена для back-compat, но `index.html` подключает только модульный агрегатор.
