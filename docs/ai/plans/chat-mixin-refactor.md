
## Цель

Привести frontend в порядок и подготовить к простой дальнейшей разработке:

- Разбить разросшийся `rag-backend/app/static/js/api/chat.js` (13 разнородных методов) на 4 миксина по ответственности.
- Удалить мёртвый код в миксине (4 метода), неиспользуемый потребителями.
- Удалить legacy-дубль `rag-backend/app/static/js/api.js`, не подключённый в `index.html`.
- Добавить unit-тесты для всех новых миксинов (vitest, мок fetch).
- Добавить dev-инфраструктуру: ESLint, ruff, npm-зависимости, Makefile-цели.

## Контекст

### Текущее состояние

- `rag-backend/app/static/js/api/chat.js` содержит 13 методов разного назначения: CRUD чатов, стриминг сообщений, пайплайн (confirm/resume), full-doc mode, clarification.
- Миксин `updateModeMixin` уже вынесен в `api/update-mode.js` — расщепление по доменам уже применяется.
- `rag-backend/app/static/js/api.js` — legacy-класс `ChatAPI` с дублирующимися методами. **Не подключён в `index.html`** (проверено), но присутствует в репозитории как мёртвый груз.
- JS-инфраструктуры нет: ни `package.json`, ни vitest, ни ESLint.
- Backend-тесты уже есть (`pytest`, `pytest-asyncio`) — стиль: dummy-классы, parametrize, фикстуры SQLAlchemy in-memory.

### Обнаруженный мёртвый код в `api/chat.js`

| Метод | Доказательство мёртвости |
|---|---|
| `updateChatTitle` | Не вызывается ни в `chat.js` (потребитель), ни в `sidebar.js`, ни в `db_management.js`, ни в `settings.js`, ни в `pipeline_builder.js`, ни в `pending-banner.js`. |
| `submitClarification` | FSM уточнений перенесён на backend (`clarification_fsm`, `clarification_service` в `chat.py`). Клиент отправляет обычное сообщение. |
| `getClarificationState` | То же — клиент больше не опрашивает FSM, бэкенд сам ведёт состояние. |
| `updateClarificationState` | То же. |

`lockPipeline` **живой** — вызывается из `chat.js:togglePipelineLock`. Оставляем.

## Scope

### Входит

1. Создание 4 новых миксинов: `chat-crud.js`, `chat-messages.js`, `chat-pipeline.js`, `chat-full-doc.js`.
2. Удаление `api/chat.js` (старый миксин).
3. Удаление `api.js` (legacy-дубль).
4. Удаление 4 мёртвых методов из миксина.
5. Обновление `api/index.js` (замена импорта, регистрация).
6. Обновление `context/frontend.md` (новая структура `js/api/`).
7. Dev-инфраструктура:
   - `package.json`, `vitest.config.js`, `eslint.config.js` в `rag-backend/app/static/`.
   - `.gitignore` — добавить `node_modules/`, `.venv/`.
   - Цели `Makefile`: `setup-dev`, `js-install`, `test`, `js-test`, `test-all`, `lint-py`, `lint-js`, `lint`, `lint-fix`.
8. Unit-тесты для каждого нового миксина (vitest, jsdom, мок `fetch`).

### НЕ входит

- Изменение backend (`rag-backend/app/api/chat.py`, `shared_contracts/`, `update_mode_*`).
- Изменение контрактов миксинов (порядок параметров, имена).
- E2E тесты (по решению — только unit).
- TypeScript-миграция.
- Косметика `chat.js` (потребитель) сверх необходимого.
- Создание коммитов / `git add` (конфиг aider отключает, политика проекта).

## Структура новых миксинов

```
rag-backend/app/static/js/api/
├── chat-crud.js          # CRUD чатов (8 методов)
├── chat-messages.js      # sendMessage + стриминг (1 метод)
├── chat-pipeline.js      # pipelineConfirm + pipelineResume (2 метода)
├── chat-full-doc.js      # setFullDocMode + fullDocConfirm (2 метода)
└── __tests__/
    ├── chat-crud.test.js
    ├── chat-messages.test.js
    ├── chat-pipeline.test.js
    └── chat-full-doc.test.js
```

**`chat-crud.js`** (CRUD):
- `createChat(domainId, campaignId?)`
- `listChats(domainId?, campaignId?)`
- `getChat(chatId)`
- `getChatHistory(chatId)` — алиас `getChat`
- `renameChat(chatId, title)`
- `updateChat(chatId, data)`
- `deleteChat(chatId)`
- `lockPipeline(chatId, pipelineId)`

**`chat-messages.js`** (отправка):
- `sendMessage(chatId, content, stream=true, signal=null)` — единственный метод, со всей логикой стриминга, прокидыванием `signal` в `fetch`, обработкой ошибок через `errData.detail || errData.message`.

**`chat-pipeline.js`** (пайплайн):
- `pipelineConfirm(chatId, confirmToken, action)` — SSE vs JSON по Content-Type.
- `pipelineResume(chatId, resumeToken, action, feedback=null)` — то же.

**`chat-full-doc.js`** (full-doc mode):
- `setFullDocMode(chatId, enabled, campaignId=null)`
- `fullDocConfirm(chatId, selectedDocumentIds)` — SSE vs JSON.

## Этапы работ

### Этап 0 — Подготовка dev-инфраструктуры

**Makefile** (новые цели):
- `setup-dev` — создаёт `.venv` в корне, ставит `requirements-dev.txt` + ruff, запускает `npm install` в `rag-backend/app/static/`.
- `js-install` — только `npm install`.
- `test` — Python pytest через `.venv/bin/pytest` (расширить существующую цель, не сломав).
- `js-test` — vitest run.
- `test-all` — оба.
- `lint-py` — ruff check.
- `lint-js` — eslint.
- `lint` — оба линтера.
- `lint-fix` — авто-фикс для обоих.

**`rag-backend/app/static/package.json`** (новый):
- `type: module` (миксины — ES modules).
- Scripts: `test`, `test:watch`, `lint`, `lint:fix`.
- Dev deps: `vitest@^2.0.0`, `jsdom@^25.0.0`, `eslint@^9.0.0`, `@eslint/js@^9.0.0`.

**`rag-backend/app/static/vitest.config.js`** (новый):
- `environment: jsdom`.
- `globals: false` (явные импорты из `vitest`).
- `include: ['js/**/*.test.js']`.

**`rag-backend/app/static/eslint.config.js`** (новый, flat config):
- Пресет для vanilla JS + ESM.
- Правила: `no-unused-vars`, `no-undef`, `eqeqeq`, `prefer-const`.
- Без форматирования (форматирование — отдельный инструмент).

**`.gitignore`** (обновить):
- Добавить `node_modules/`.
- Добавить `.venv/`.

### Этап 1 — Создание новых миксинов

Создать 4 файла с телами, скопированными байт-в-байт из существующего `api/chat.js` (с удалёнными мёртвыми методами в `chat-crud.js`).

### Этап 2 — Обновление регистрации

**`rag-backend/app/static/js/api/index.js`**:
- Заменить `import { chatMixin } from './chat.js'` на 4 новых импорта.
- Заменить `chatMixin` в `Object.assign` на 4 новых миксина.

### Этап 3 — Удаление старого кода

**Удалить вручную** (файлы не добавлены в чат, aider не может их править):
- `rag-backend/app/static/js/api/chat.js` — старый миксин.
- `rag-backend/app/static/js/api.js` — legacy-дубль.

### Этап 4 — Документация

**`context/frontend.md`** — обновить:
- Раздел «Структура файлов»: заменить один `chat.js` на 4 файла в `js/api/`.
- Раздел про `window.MercerAPI`: отразить новые методы, удалить `updateChatTitle` и три clarification-метода из перечисления.

### Этап 5 — Unit-тесты

Создать `js/api/__tests__/` (рядом с исходниками миксинов).

#### Матрица тестов

| Миксин | Тестов | Что проверяем |
|---|---|---|
| `chat-crud.test.js` | 10 | URL, метод, тело, query string, парсинг JSON, обработка ошибок для каждого из 8 методов |
| `chat-messages.test.js` | 6 | stream=true → response.body, stream=false → JSON, signal прокидывается, ошибка через `detail`, ошибка через `message`, fallback на statusText |
| `chat-pipeline.test.js` | 6 | pipelineConfirm confirmed=true/false, pipelineResume cancelled + user_feedback, SSE vs JSON, ошибки |
| `chat-full-doc.test.js` | 4 | setFullDocMode с campaignId и без, fullDocConfirm SSE/JSON, ошибки |
| **Итого** | **26** | |

#### Подход к мокам

```javascript
// Пример мока fetch в тесте
const fetchMock = vi.fn();
globalThis.fetch = fetchMock;

fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ chat_id: 'abc' }),
});

const api = { baseUrl: '' };
Object.assign(api, chatCrudMixin);
const result = await api.createChat('dnd');
expect(fetchMock).toHaveBeenCalledWith('/chat/create', expect.objectContaining({...}));
```

## Регрессионные проверки

После применения изменений:

1. `make setup-dev` — успешно ставит окружение (без интернета или с ошибками — сообщить).
2. `make js-test` — все 26 тестов проходят.
3. `make test` — Python-тесты не сломаны.
4. `make lint` — ruff + eslint без ошибок.
5. `make lint-fix` — не вносит неожиданных изменений.
6. Поиск ссылок на удалённые методы: `grep -r "updateChatTitle\|submitClarification\|getClarificationState\|updateClarificationState" rag-backend/app/static/js/` — должно быть пусто.

Ручная проверка UI (если есть окружение): создание чата, переименование, удаление, lock pipeline, стриминг, full-doc mode.

## Что я НЕ буду делать без явного запроса

- Менять `chat.js` (потребитель) — никаких правок не требуется, вызовы остаются работоспособными.
- Менять `index.html` — порядок подключения скриптов прежний, миксины подключаются через ES module `api/index.js`.
- Менять backend.
- Менять существующие цели `Makefile` (`setup`, `init-env`, `_agent-setup-dispatch`, и т. д.) — только добавление новых.
- Удалять `api/chat.js` и `api.js` сам (нет в чате) — пользователь удалит вручную.
- Делать `git add` / коммиты / `git push`.
- Менять `Makefile` цели `test` и `lint` так, чтобы сломать их существующее поведение — только расширяем.

## Порядок выполнения

1. Этап 0 (инфраструктура): `Makefile`, `package.json`, `vitest.config.js`, `eslint.config.js`, `.gitignore`.
2. Этап 1 (миксины): создать 4 файла, удалить мёртвый код в `chat-crud.js`.
3. Этап 2 (регистрация): `api/index.js`.
4. Этап 5 (тесты): `js/api/__tests__/*.test.js`.
5. Этап 4 (документация): `context/frontend.md`.
6. Этап 3 (удаление legacy): пользователь удаляет `api/chat.js` и `api.js` вручную.

После каждого этапа — конкретный file listing. Перед применением каждого файла — отдельное явное одобрение.

## Риски

1. **Стриминг-логика в `sendMessage`** — единственное сложное место. Сохраняем байт-в-байт (signal, response.body, парсинг ошибок через `errData.detail || errData.message`).
2. **Потребители могут ссылаться на удалённые методы** — перепроверены все известные потребители (`chat.js`, `sidebar.js`, `db_management.js`, `settings.js`, `pending-banner.js`, `pipeline_builder.js`). Удалённые методы не используются.
3. **`make test` уже существует** для Python — расширяем аккуратно, не ломая существующее поведение. Если текущая `make test` имеет другую семантику — обсудим отдельно.
4. **`npm install` требует интернет** — CI без интернета сломается. Это вне scope плана, отдельная задача.
5. **vitest 2.x vs 1.x**: 2.x нативно поддерживает ESM. Если несовместимость — откатим на 1.x.
6. **ESLint 9.x flat config** — новый формат. Если несовместимость с чем-то ещё в проекте — обсудим.
