# Фронтенд — структура и архитектура

## Общее

Фронтенд — это **React + TypeScript SPA**, собирается через **Vite**, состояние — **Zustand**, HTTP-кэш — **TanStack Query**, UI-стили — **Tailwind** с темами через CSS-переменные.

- Расположен в `rag-backend/app/static/frontend/`
- Сборка: `npm run build` → `frontend/dist/` → копируется в `app/static/dist/`
- Раздаётся FastAPI из `rag-backend/app/static/` (mount `/static`)
- `app/static/index.html` подключает собранный бандл из `/static/dist/assets/...`

## Структура файлов

```
rag-backend/app/static/
├── index.html                  # Подключает собранный бандл из /static/dist/
├── dist/                       # Билд Vite (генерируется при сборке)
│   ├── index.html              # Шаблон Vite (НЕ раздаётся — копия для проверки)
│   └── assets/
│       ├── index-*.js          # JS-бандл с хешем
│       └── index-*.css         # CSS-бандл с хешем
└── frontend/                   # Исходники Vite-проекта
    ├── package.json            # Зависимости и скрипты
    ├── tsconfig.json           # strict TS
    ├── vite.config.ts          # dev-сервер на 5173, base=/static/dist/
    ├── vitest.config.ts        # test setup
    ├── tailwind.config.ts      # Tailwind + CSS-vars
    ├── postcss.config.js
    ├── eslint.config.js
    ├── index.html              # Шаблон Vite для dev
    └── src/
        ├── main.tsx            # Точка входа React + QueryClientProvider
        ├── App.tsx             # Переключает ChatPage ↔ SettingsPage
        ├── api/                # HTTP-клиент (типизированный)
        │   ├── client.ts       # MercerAPI: все доменные методы
        │   ├── http.ts         # HttpClient + HttpError
        │   ├── types.ts        # Все TS-типы (из shared_contracts)
        │   └── index.ts
        ├── stores/             # Zustand stores
        │   ├── themeStore.ts   # light/dark + data-theme
        │   ├── domainStore.ts  # currentDomain, campaigns
        │   ├── chatStore.ts    # currentChat, messages, streaming
        │   └── settingsStore.ts# page: chat|settings, activeSettingsTab
        ├── hooks/              # Кастомные React-хуки
        ├── components/
        │   ├── ui/             # UI-кит (Button, Modal, Tabs, Select, Input, …)
        │   ├── chat/           # ChatPage, ChatArea, Markdown
        │   ├── sidebar/        # Sidebar, ChatList, RenameModal
        │   ├── settings/       # SettingsPage + tabs/*
        │   │   └── tabs/
        │   │       ├── DomainsTab.tsx
        │   │       ├── VaultsTab.tsx
        │   │       ├── ModelsTab.tsx
        │   │       ├── ParamsTab.tsx
        │   │       ├── PipelinesTab.tsx
        │   │       ├── PipelineBuilder.tsx       # DAG на SVG
        │   │       ├── CampaignsTab.tsx
        │   │       ├── DocumentsTab.tsx
        │   │       ├── useStateFields.ts         # хук для Campaign State fields
        │   │       ├── InitialStateButton.tsx    # Wizard 3 фазы
        │   │       ├── EffectiveContextButton.tsx
        │   │       └── UpdateModeButton.tsx      # Запуск Update Mode из настроек
        │   ├── wizard/         # UpdateModePanel — review/apply UI
        │   └── search/         # SearchDbModal — поиск по LanceDB
        ├── themes/
        │   ├── tokens.css      # CSS-переменные для light/dark
        │   └── index.css       # @tailwind + tokens + highlight.js
        ├── types/              # Общие типы (Theme, Result и т.п.)
        ├── utils/              # Утилиты (safeStorage)
        └── test/               # Vitest setup
```

## Разметка страниц (index.html)

### Главный экран — Чат

Активен по умолчанию. Реализован через `<ChatPage>` (`src/components/chat/ChatPage.tsx`):

```
<ChatPage>
├── <Sidebar>
│   ├── Header
│   │   ├── Кнопка «Настройки платформы» → useSettingsStore.openSettings()
│   │   ├── Кнопка «Поиск по хранилищу» → <SearchDbModal open>
│   │   ├── <DomainSelector>          # useDomainStore.domains
│   │   ├── <CampaignSelector>        # useDomainStore.campaigns
│   │   ├── Кнопка «Новая беседа»     # api.createChat()
│   │   └── Кнопка переключения темы  # useThemeStore.toggleTheme()
│   └── <ChatList chats={...}>
│       └── Каждый чат: title + меню (rename/delete)
└── <ChatArea>
    ├── header (title + домен)
    ├── messages (MessageBubble × role)
    │   └── <UpdateModePanel> если есть активная сессия
    └── footer (textarea + send/stop button)
```

### Страница настроек

Показывается при `useSettingsStore.page === 'settings'`:

```
<SettingsPage>
├── header (← Назад к чату)
├── <Tabs items=[domains,vaults,models,params,pipelines,campaigns,documents]>
└── <SettingsContent tab={activeTab}>
    ├── domains    → <DomainsTab> + <PromptEditor> × 4
    ├── vaults     → <VaultsTab>
    ├── models     → <ModelsTab> + подтабы (gen/emb/rerank)
    ├── params     → <ParamsTab>
    ├── pipelines  → <PipelinesTab> + <PipelineBuilder> (DAG на SVG)
    ├── campaigns  → <CampaignsTab> + <InitialStateButton>, <EffectiveContextButton>, <StateFields>
    └── documents  → <DocumentsTab>
```

```
main#settings-page
├── .settings-header + #back-to-chat-btn
├── nav.settings-tabs                   # 7 кнопок (домены, ваулты, модели, параметры, pipelines, campaigns, documents)
└── #settings-content                   # Контент активного таба (динамически заменяется)
```

### Модальные окна (React `<Modal>`)

| Компонент | Назначение |
|---|---|
| `<RenameModal>` | Переименование чата |
| `<SearchDbModal>` | Поиск по хранилищу (LanceDB), выбор домена, запрос, лимит |
| `<InitialStateWizard>` | Initial State: select → review → result |
| `<EffectiveContextDialog>` | Debug effective context |

### Inline компоненты в `<ChatArea>`

| Компонент | Файл | Назначение |
|---|---|---|
| `<UpdateModePanel>` | `src/components/wizard/UpdateModePanel.tsx` | Review/apply UI для Campaign Update Mode |
| `<ContextDraftCard>` | `src/components/chat/ContextDraftCard.tsx` | **Context Engine Phase 4**: карточка auto-draft campaign state. Кнопки Accept / Reject / Check-files. Polling `GET /api/chats/{id}/context-draft`. |
| `<ChatContextBar>` | `src/components/chat/ChatContextBar.tsx` | Контекстный бар чата (кампания, домен). Возможно место для badge draft. |
| `<PendingIndexBanner>` | `src/components/chat/PendingIndexBanner.tsx` | Баннер о файлах, ожидающих индексации |

## Архитектура модулей

### `src/api/` — HTTP-клиент (типизированный)

Единая точка взаимодействия с backend. Класс `MercerAPI extends HttpClient`
содержит все доменные методы, экспортируется как singleton `api`.

```typescript
// src/api/client.ts
export const api = new MercerAPI();

// Чаты
await api.listChats(domainId);
await api.createChat(domainId, campaignId);
await api.sendMessage(chatId, content, true, signal); // → ReadableStream SSE

// Campaign State (Stage 1-7)
await api.previewInitialState(campaignId, ids);       // → InitialProposalReadV2
await api.applyInitialState(campaignId, req);
await api.getEffectiveContext(campaignId, chatId?);
await api.getStateStaleStatus(campaignId);

// Campaign Update Mode (Sprint 3)
await api.startUpdateMode(chatId, note);
await api.getUpdateModeSession(chatId);
await api.updateModeReview(chatId, decisions);        // { accepted_change_ids, ..., state_patch_decisions, field_change_decisions }
await api.applyUpdateMode(chatId, applyId);
await api.cancelUpdateMode(chatId);

// Context Draft (Phase 4)
await api.getContextDraft(chatId);
await api.acceptContextDraft(chatId);
await api.rejectContextDraft(chatId);
await api.checkFilesFromContextDraft(chatId);

// Drift Models (Phase 2a)
await api.getDriftModels();
await api.createDriftModel(payload);
await api.updateDriftModel(modelId, payload);
await api.setActiveDriftModel(modelId);
await api.checkDriftModel(modelId);

// Sidecar / Indexer / DB Browser / Теги / ...
```

Поддерживается через `src/api/types.ts` — все типы доменных сущностей (Chat, Campaign,
InitialProposal, EffectiveContextRead, ContextDraft, DriftModel и т.д.) импортируются из этого файла.

`HttpError` (статус + detail) поддерживает `isCode('source_snapshot_stale')` для машинной обработки ошибок Initial State.

Стриминг `sendMessage(chatId, content, true, signal)` возвращает `ReadableStream` (fetch + ReadableStream, постепенное чтение SSE-подобных кусков).

---

### `<ChatPage>` — `src/components/chat/ChatPage.tsx`

Главная страница приложения (после перехода с vanilla JS на React).

**Ответственность:**
- Управление активным чатом через `useChatStore`
- Открытие/закрытие чата, лента сообщений
- Отправка сообщения через `api.sendMessage()`, обработка SSE-стрима (token/tool_call/round_start/tool_result/sources/final)
- Рендеринг Markdown через `<Markdown>` (`marked` + `DOMPurify` + `highlight.js`)
- Рендеринг inline-компонентов: `<UpdateModePanel>`, `<ContextDraftCard>`, `<ChatContextBar>`, `<PendingIndexBanner>`
- Кнопка Stop во время стрима через `AbortController`

**SSE-события** (типы в `src/api/types.ts`):
- `step_status`, `token`, `sources`, `error` — базовые
- `prefill_rag` — Sprint 2: после prefill retrieval
- `round_start`, `tool_call`, `tool_result` — bounded agent loop
- `context_update_proposal` — Sprint 3: модель предложила update
- `full_document_selection_required` — выбор документов
- `pipeline_confirm_required` — подтверждение пайплайна
- `clarification` — уточняющий вопрос

---

### `<Sidebar>` — `src/components/sidebar/Sidebar.tsx`

**Ответственность:**
- Отображает домен/кампанию через `useDomainStore`
- Загружает чаты через `useQuery(['chats', domainId])` (TanStack Query)
- Список чатов через `<ChatList>` с inline-меню (rename/delete)
- Кнопка переключения темы через `useThemeStore`
- Открывает `<SearchDbModal>` и `<RenameModal>`

### `<ChatArea>` — `src/components/chat/ChatArea.tsx`

**Ответственность:**
- Отображает ленту сообщений из `useChatStore`
- Стриминг через `api.sendMessage()` + ручной `ReadableStream`-reader
- Inline `<UpdateModePanel>` если есть активная Update Mode сессия
- Кнопка Stop во время стрима через `AbortController`

### `<SettingsPage>` — `src/components/settings/SettingsPage.tsx`

**Ответственность:**
- Переключает табы через `useSettingsStore`
- Рендерит активный таб через `<SettingsContent>` (switch по `activeSettingsTab`)

**Никакого порядка загрузки скриптов нет** — это преимущество Vite/ESM.
Импорты TS резолвятся автоматически, дерево зависимостей строится по факту
использования. Никаких `tag-badge.js ДО tab-campaigns.js`.

---

### `<PipelineBuilder>` — `src/components/settings/tabs/PipelineBuilder.tsx`

Визуальный редактор пайплайнов на чистом SVG (без сторонних библиотек).
Используется во вкладке "Pipelines" страницы настроек.

- Шаги пайплайна как `<rect>` + `<text>` с автолейаутом по уровням (topological sort)
- Связи через `<path>` с маркером `arrowhead`
- Inspector справа: редактирование name, depends_on (multi-checkbox)
- Добавление/удаление шагов, изменение `final_composition`
- Сохранение через `api.updatePipeline()`

---

### `<UpdateModePanel>` — `src/components/wizard/UpdateModePanel.tsx`

Review/apply UI для Campaign Update Mode. Встраивается inline в `<ChatArea>`.

- Опрос `api.updateModeGetSession()` каждые 5 секунд
- Список файловых изменений: unified diff + принять/отклонить
- Список state-ops: human-readable summary + принять/отклонить
- Inline-редактор для replace_single / update_list_item / add_list_item (TODO)
- Сохранить выбор → `api.updateModeReview()`
- Применить → `api.updateModeApply()`

---

### `<SearchDbModal>` — `src/components/search/SearchDbModal.tsx`

Поиск по LanceDB. Открывается из сайдбара. Использует `api.textSearchByDomain(domainId, query, limit)`.

---

## Вкладки страницы настроек

| Таб | Файл | Содержание |
|---|---|---|
| `domains` | `tabs/DomainsTab.tsx` | CRUD доменов, редактор промптов (4 типа), ClarificationFields |
| `vaults` | `tabs/VaultsTab.tsx` | CRUD ваултов, toggle embedding-модели |
| `models` | `tabs/ModelsTab.tsx` | Подтабы: Generation / Embedding / Rerank |
| `params` | `tabs/ParamsTab.tsx` | Редактирование PlatformSetting |
| `pipelines` | `tabs/PipelinesTab.tsx` + `tabs/PipelineBuilder.tsx` | Список + DAG-редактор на SVG |
| `campaigns` | `tabs/CampaignsTab.tsx` + подмодули | CRUD кампаний, **Campaign State UI**: State Fields, Initial State wizard, Effective Context debug |
| `documents` | `tabs/DocumentsTab.tsx` | Просмотр документов, фильтры, статусы, reindex |

### Campaign State UI

Карточка кампании в `<CampaignsTab>` интегрирует:

#### Поля Campaign State (Stage 1) — `useStateFields` хук

- CRUD по `state-fields`: добавление/редактирование/удаление полей, режим `single | list`,
  порядок (`display_order`), флаг `enabled`.
- Удаление поля требует подтверждения.
- Inline-редактор в `<StateFieldsSection>`.

#### Initial State (Stage 3) — `<InitialStateButton>` + `<InitialStateWizard>`

Modal с тремя фазами:

1. **Select** — выбор Markdown-документов кампании по тегам
   (`api.getCampaignTags` + `api.getCampaignGlobalTags` → `api.getSettingsDocuments({ tagIds })`).
   - Если у кампании 0 тегов — показывается баннер «Initial State недоступен».
   - Счётчик токенов с предупреждением, если > 64 000.
2. **Review** — список полей со значениями (`proposed` / `empty` / `needs_clarification`),
   отрендеренными через `<Markdown>`.
3. **Result** — финальное сообщение об успехе.

#### Effective Context debug (Stage 6) — `<EffectiveContextButton>`

Кнопка «Debug effective context» открывает `<EffectiveContextDialog>` с результатом
`api.getEffectiveContext(campaignId)`: блоки с метриками `total_tokens`, `budget`, `truncated_fields`.

#### Stale indicator (Stage 7)

TODO: бейдж «В источниках появились обновления» по `api.getStateStaleStatus(campaignId)`.

#### Update Mode — `<UpdateModeButton>` (запуск из настроек)

Кнопка в карточке кампании: пользователь вводит `note`, запускается
`api.updateModeStart(chatId, note)`. UI review/apply — внутри `<UpdateModePanel>` в чате.

### Update Mode UI — `UpdateModePanel` + `api.updateModeReview`

UI review-сессии в `<UpdateModePanel>` рендерит:

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
- Sprint 3: schema-change операции (create_field / update_field) рендерятся третьей секцией.

API метод `api.updateModeReview(chatId, { accepted_change_ids, rejected_change_ids, state_patch_decisions: {...}, field_change_decisions: {...} })`.

### Context Draft UI — `<ContextDraftCard>`

UI для auto-draft campaign state (Context Engine Phase 4). Встраивается inline в `<ChatArea>` рядом с `<UpdateModePanel>`.

- Polling `api.getContextDraft(chatId)` (через TanStack Query `['context-draft', chatId]`).
- Когда `draft != null` → карточка с summary + операции state_patch (expandable).
- Кнопки:
  - **Применить** → `api.acceptContextDraft(chatId)` → `POST .../context-draft/accept`. После успеха `clear_drift` + `DEL draft`.
  - **Отклонить** → `api.rejectContextDraft(chatId)` → `POST .../context-draft/reject`.
  - **Применить и проверить файлы** → `api.checkFilesFromContextDraft(chatId)` → `POST .../context-draft/check-files` → создаёт Update Mode session с `state_patch_context`. После успеха UI открывает `<UpdateModePanel>` с готовыми file_changes.

Стили: amber/brown палитра, чтобы отличать от Update Mode (синяя) и обычных сообщений.

### Conditional / cyclic RAG индикатор

TODO: бейдж «поиск» во время tool-цикла — пока host выполняет
`search_knowledge`, в сообщении ассистента показывается анимация и
`queries_used`. Текущая версия обрабатывает только `token` и `progress`-события.

### Drift-модели в `<ModelsTab>`

Таб «Модели» содержит 4 секции (с подтабами или вертикальными секциями):

- **Generation** — большая LLM для чата.
- **Embedding** — для индексации (`bge-m3` через pdf-sidecar).
- **Rerank** — `BAAI/bge-reranker-v2-m3` через pdf-sidecar.
- **Drift-модели** — Phase 2a context-engine. Управление активной моделью для drift detection.
  - Список моделей через `api.getDriftModels()`.
  - Создание через `api.createDriftModel({provider, base_url, model_name, ...})`.
  - Inline-edit через `<EditDriftModelModal>` (`api.updateDriftModel`).
  - Активация через `api.setActiveDriftModel(modelId)`.
  - Health-check через `api.checkDriftModel(modelId)`.

Реализация: `src/components/settings/tabs/ModelsTab.tsx` → компонент `DriftModelsBody` (строки 1381+) + `DriftModelCard` (строки 1420+).

## Зависимости (npm)

| Пакет | Версия | Назначение |
|---|---|---|
| `react` | 18.3 | UI-фреймворк |
| `react-dom` | 18.3 | React renderer для DOM |
| `zustand` | 4.5 | Глобальное состояние (замена `window.*`) |
| `@tanstack/react-query` | 5.51 | HTTP-кэш + mutations |
| `marked` | 12.0 | Парсер Markdown → HTML |
| `dompurify` | 3.1 | Санитация HTML (XSS-защита) |
| `highlight.js` | 11.9 | Подсветка кода (python, js, bash, json, yaml, sql) |
| `tailwindcss` | 3.4 | Утилитарные CSS-классы |
| `vite` | 5.3 | Сборщик + dev-сервер |
| `typescript` | 5.5 | Типизация |
| `vitest` | 2.0 | Unit-тесты |
| `@testing-library/react` | 16.0 | Тесты компонентов |

## Stores (замена `window.*`)

| Store | Источник | Заменяет |
|---|---|---|
| `useThemeStore` | `stores/themeStore.ts` | `data-theme` атрибут на `<html>` |
| `useDomainStore` | `stores/domainStore.ts` | `window.currentDomainId` / `window.currentCampaignId` |
| `useChatStore` | `stores/chatStore.ts` | `window.chatManager.currentChat` / `currentChatId` |
| `useSettingsStore` | `stores/settingsStore.ts` | `window.activeSettingsTab` + переключение страниц |

## Особенности архитектуры

1. **Нет react-router** — переключение страниц/табов через `useSettingsStore` (Zustand).
2. **TypeScript strict** — ошибки типов ловятся на этапе компиляции.
3. **TanStack Query** для всего server-state — `useQuery` для чтения, `useMutation` для записи,
   автоматическая инвалидация через `queryClient.invalidateQueries`.
4. **Zustand** для клиентского состояния (theme, current selections, streaming state).
5. **Tailwind + CSS variables + data-theme** — темизация через CSS-переменные, переключение light/dark.
6. **Стриминг** — `fetch()` + `ReadableStream`, не `EventSource` (как и раньше).
7. **Сборка обязательна** — `npm run build` → `frontend/dist/` → копируется в `app/static/dist/`.
   Никакого порядка загрузки скриптов — Vite/ESM резолвит дерево зависимостей сам.
8. **Никаких `tag-badge.js ДО tab-campaigns.js`** — все импорты через `import`/`export`.

## Разработка

### Dev-сервер

```bash
cd rag-backend/app/static/frontend
npm install
npm run dev
```

Vite стартует на `http://localhost:5173`. Проксирование `/api`, `/config`, `/chat`,
`/api/v1` идёт на `http://localhost:8000` (FastAPI должен быть запущен).

### Production-сборка

```bash
npm run build
# → dist/index.html + dist/assets/index-*.{js,css}
# Vite собирает с base=/static/dist/ для встраивания в FastAPI
```

При запуске `Dockerfile.rag-backend` стадия `frontend-builder` запускает `npm run build`,
а результат копируется в `/app/app/static/dist/`. Финальный `index.html` (в
`app/static/index.html`) подключает `/static/dist/assets/index-*.js`.

### Тесты

```bash
npm test          # однократный прогон
npm run test:watch
npm run lint      # ESLint
npm run typecheck # tsc --noEmit
```

## Что ещё TODO

Список известных пробелов в текущей миграции:

- Inline-редактор текста для replace_single / update_list_item в `<UpdateModePanel>`
- Бейдж `stale` indicator для Campaign State (Stage 7)
- Full Document Mode панель (выбор документов при full_document_selection_required)
- Pipeline inline-карточки (pipeline_confirm_required / validation_required)
- Conditional / cyclic RAG индикатор (tool_call / tool_result в ChatArea)
- Pending Banner (поллинг pending_pipeline_confirm / pipeline_pause_state)
- Pipeline Builder: drag-to-reorder, drag-to-connect вместо чекбоксов
- Полная Storybook / chromatic snapshot для регрессий UI
