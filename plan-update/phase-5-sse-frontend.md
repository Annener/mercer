# Фаза 5 — UI, E2E и operational readiness

## Цель

Подключить Campaign Update Mode к пользовательскому интерфейсу, проверить полный путь на реальном Docker deployment и зафиксировать operational guarantees.

К концу фазы пользователь должен пройти путь:

```text
campaign chat
→ enter update mode
→ submit note
→ review original-file diffs
→ accept/reject changes
→ apply
→ see per-vault commit and reindex status
→ ask chat using newly indexed context
```

Эта фаза не меняет архитектурные boundaries предыдущих фаз:

- backend остаётся orchestrator;
- indexer остаётся единственным filesystem/git writer;
- Redis остаётся review-session store;
- PostgreSQL остаётся source of truth vault settings;
- git repo остаётся один на vault.

---

## Precondition

Перед началом UI работы должны быть завершены и проверены:

- Фаза 0: инварианты и baseline;
- Фаза 1: path/file/git foundation;
- Фаза 2: contracts, migration, Redis store;
- Фаза 3: retrieval, generation, resolve;
- Фаза 4: review, apply, git, targeted reindex.

Не компенсировать отсутствующую backend/indexer логику логикой на frontend.

---

## UI scope

Добавить Campaign Update Mode только в campaign-aware chat interface.

UI должен быть доступен, когда:

- chat существует;
- chat имеет `campaign_id`;
- campaign имеет tags;
- backend start endpoint разрешает операцию.

UI не должен самостоятельно вычислять:

- vault IDs;
- campaign tag scope;
- document IDs;
- file paths;
- checksums;
- diffs;
- git command;
- reindex task.

Все эти данные приходят от backend API.

---

## User flow

### Idle

В campaign chat показать кнопку:

```text
Обновить контекст
```

Если chat не связан с campaign:

- не показывать кнопку, либо показать disabled control с ясной причиной;
- не создавать специальный frontend-only state.

### Note input

После входа в режим:

- показать textarea для заметки;
- placeholder должен объяснять назначение:
  ```text
  Опишите новые события, факты или решения, которые нужно отразить в контексте кампании.
  ```
- запретить пустую note;
- frontend limit: 20,000 characters;
- показывать character counter;
- submit вызывает:
  ```text
  POST /api/chats/{chat_id}/update-mode/start
  ```

Во время start:

- disable repeat submit;
- показать loading state:
  ```text
  Ищу контекст и подготавливаю предложения…
  ```
- не открывать SSE для этого flow в MVP.

Start — обычный request/response endpoint. Existing chat SSE endpoint не изменяется и не переиспользуется для update mode. SSE — однонаправленный transport; для короткого request/response review flow он не нужен. [web:179][web:180][web:181]

### Resolved changes review

После successful start:

- показать `warnings`, если backend их вернул;
- показать каждую change отдельной review card;
- `pending` change имеет toggle/checkbox “Применить”;
- `resolution_failed` change показан disabled с user-safe message;
- `accepted` и `rejected` отображают текущее состояние при session reload;
- исходный diff показывается только как server-returned `unified_diff`;
- frontend не вычисляет diff самостоятельно.

Для каждого change обязательно показать:

| Поле | Отображение |
|---|---|
| `vault_id` | Имя/ID vault |
| `file_path` | Относительный путь markdown файла |
| `action` | Изменить или создать |
| `description` | Объяснение предложения |
| `unified_diff` | Diff исходного файла |
| `error_message` | Только для `resolution_failed` |

Для create change:

```text
Создать: _campaign_notes/session-2026-07-15.md
```

или путь рядом с parent document.

### Review state persistence

После пользовательского выбора:

```text
PATCH /api/chats/{chat_id}/update-mode/review
```

Не ждать Apply, чтобы сохранить accepted/rejected state только локально.

UI может:

- debounce review PATCH на короткий интервал;
- disable controls, пока PATCH in flight;
- повторить запрос при transient network failure;
- после response заменить local state server state.

UI не должен предполагать, что его local status authoritative.

### Session recovery

При открытии chat или reopening update panel:

```text
GET /api/chats/{chat_id}/update-mode/session
```

Поведение:

| Response | UI |
|---|---|
| `200` | Восстановить review cards и statuses |
| `410 session_expired` | Показать «Сессия review истекла. Запустите обновление заново»; очистить local state |
| `404`, если такой contract выбран | Не использовать для expiry; expiry должен быть `410` |
| `503` | Показать retry control, не терять local display немедленно |

Session имеет TTL 3 часа. UI должен показывать expiry time, полученный из `expires_at`.

Не пытаться продлевать session polling GET-запросами.

### Apply

Кнопка:

```text
Применить выбранные изменения
```

Активна только если:

- есть минимум один `accepted` change;
- нет active apply request;
- session не expired.

По нажатию:

```text
POST /api/chats/{chat_id}/update-mode/apply
```

Body:

```json
{
  "apply_id": "uuid"
}
```

Frontend генерирует `apply_id` один раз на нажатие и сохраняет его в component state до terminal response. Если request оборвался после отправки, retry использует **тот же** `apply_id`.

Во время apply:

- disable all review controls;
- показать:
  ```text
  Применяю изменения и запускаю индексацию…
  ```
- не отправлять second apply с новым UUID;
- не удалять local review state до final backend response.

### Apply result

Render results per vault, не как один общий успех/провал.

| Status | UI |
|---|---|
| `applied` | Показать applied count, snapshot SHA, commit SHA, reindex task |
| `conflict` | Показать file conflict; предложить начать новый update mode session |
| `failed` | Показать safe error; не обещать автоматический rollback |
| `no_changes` | Показать, что в vault не было применимых изменений |
| `reindex_error` | Показать commit success, но индекс ещё не подтверждён |

Если результаты частичные:

```text
Изменения применены не во всех vault.
```

UI обязан показывать ровно какие vault успешно получили commit, а какие требуют повторной подготовки.

### Targeted reindex status

Для каждого `reindex_task_id` UI использует уже существующий indexer status endpoint/API.

Показывать:

```text
Ожидает
Индексируется
Готово
Ошибка
```

Не реализовывать новый websocket/SSE protocol для этой задачи, если project уже имеет polling/status mechanism.

После `done` показать:

```text
Контекст обновлён и доступен для поиска.
```

После `error`:

```text
Файл сохранён и закоммичен, но индексация не завершилась.
```

Не откатывать git commit из UI.

---

## Error UX

### Expected errors

| Backend code | User-facing text | Действие |
|---|---|---|
| `campaign_required` | Этот чат не связан с кампанией | Вернуться в campaign chat |
| `campaign_tags_required` | У кампании нет тегов. Добавьте хотя бы один тег контекста | Открыть campaign tags |
| `no_enabled_vaults` | В домене нет доступных vault | Открыть vault settings |
| `campaign_has_no_indexed_markdown` | Для тегов кампании пока нет проиндексированных Markdown-файлов | Дождаться/запустить индексацию |
| `no_relevant_campaign_context` | По заметке не найден подходящий контекст кампании | Уточнить заметку |
| `no_usable_indexed_context` | Контекст недоступен для подготовки правок | Повторить позже или проверить indexing |
| `generation_provider_unavailable` | Не настроена активная генеративная модель | Открыть model settings |
| `indexer_unavailable` | Сервис работы с файлами недоступен | Повторить позже |
| `session_already_active` | Уже есть незавершённая сессия обновления | Открыть текущую review-сессию |
| `session_expired` | Сессия review истекла | Запустить обновление заново |
| `file_modified` | Файл был изменён после подготовки правки | Создать новую review-сессию |
| `target_exists` | Целевой файл уже существует | Создать новую review-сессию |
| `vault_lock_timeout` | Vault сейчас занят другой операцией | Повторить позже |
| `git_unavailable` | Git недоступен для этого vault | Проверить deployment |
| `git_ignored_target` | Файл исключён правилами Git и не может быть применён | Исправить правила Git вручную |
| `apply_already_started` | Эта операция уже выполняется | Повторить запрос с тем же состоянием или дождаться результата |

Не выводить raw exception, traceback, SQL, absolute server path, git command или git stderr.

### Network retry

- `GET session` и review PATCH можно retry безопасно;
- start retry после неизвестного network outcome сначала делает `GET session`;
- apply retry всегда использует тот же `apply_id`;
- UI не вызывает repeated start при `409 session_already_active`;
- UI не создаёт new apply ID при timeout.

---

## Accessibility and usability

- Все controls доступны с клавиатуры;
- Toggle имеет visible label, не только color;
- Diff отображается моноширинным шрифтом, с переносом длинных строк по настройке;
- Добавленные строки имеют `+`, удалённые `-`, но смысл не должен зависеть только от красного/зелёного цвета;
- Применение требует явного клика, без auto-apply;
- Cancel всегда доступен до начала apply;
- После apply UI показывает immutable result, а не editable stale cards.

---

## Frontend state model

Не хранить persistent update session в localStorage как source of truth.

Допустимое local state:

```typescript
type UpdateModePanelState =
  | { kind: "idle" }
  | { kind: "entering_note" }
  | { kind: "starting" }
  | { kind: "review"; session: UpdateModeSessionResponse }
  | { kind: "applying"; session: UpdateModeSessionResponse; applyId: string }
  | { kind: "result"; result: ApplyUpdateModeResponse }
  | { kind: "error"; error: ApiError }
```

При page reload:

1. Открыть panel в `loading`;
2. Выполнить `GET session`;
3. Восстановить server session либо перейти в `idle`.

Не доверять old diff/content из browser cache.

---

## API client additions

Добавить typed frontend client methods:

```typescript
startUpdateMode(
  chatId: string,
  body: StartUpdateModeRequest,
): Promise<StartUpdateModeResponse>

getUpdateModeSession(
  chatId: string,
): Promise<UpdateModeSessionResponse>

reviewUpdateMode(
  chatId: string,
  body: UpdateModeReviewRequest,
): Promise<UpdateModeSessionResponse>

applyUpdateMode(
  chatId: string,
  body: ApplyUpdateModeRequest,
): Promise<ApplyUpdateModeResponse>

cancelUpdateMode(
  chatId: string,
): Promise<void>
```

Client должен сохранить backend status/code в structured error type:

```typescript
class ApiError extends Error {
  status: number
  code?: string
  detail?: string
}
```

Не преобразовывать все failures в один generic “Something went wrong”.

---

## E2E сценарий

### Подготовка

1. Создать domain;
2. Создать минимум два enabled vault того же domain;
3. В каждом vault создать `.md` файлы;
4. Запустить indexing;
5. Создать campaign и назначить tags;
6. Связать documents из обоих vault с campaign tags;
7. Создать campaign chat;
8. Убедиться, что active generation model доступна.

### Сценарий: update существующего файла

1. Открыть campaign chat;
2. Enter Update Context;
3. Ввести note, релевантную документу в vault A;
4. Проверить, что diff показывает original `.md` path и exact changes;
5. Принять change;
6. Apply;
7. Проверить:
   - появился snapshot commit только если target file был dirty;
   - появился apply commit;
   - в commit нет unrelated dirty files;
   - returned `reindex_task_id`;
8. Дождаться `done`;
9. Через обычный chat retrieval проверить, что новое knowledge доступно.

### Сценарий: create рядом с parent

1. Ввести note для новой темы, относящейся к existing document;
2. Проверить create diff;
3. Проверить target directory совпадает с parent document directory;
4. Apply;
5. Проверить новый `.md`, git commit и Document/chunks после targeted reindex.

### Сценарий: create fallback

1. Подготовить campaign context, где LLM возвращает create без parent;
2. Проверить target:
   ```text
   _campaign_notes/<filename>.md
   ```
3. Проверить, что иных directories не создано;
4. Apply и проверить indexing.

### Сценарий: multi-vault partial conflict

1. Подготовить valid changes для vault A и vault B;
2. После review вручную изменить target file vault B;
3. Apply;
4. Проверить:
   - vault A получил commit/reindex;
   - vault B вернул `file_modified`;
   - UI показывает partial result;
   - нет silent overwrite.

### Сценарий: expiry

1. Создать session;
2. В тесте сократить TTL или advance time;
3. Выполнить GET/review/apply;
4. Проверить `410 session_expired` + `Cache-Control: no-store`;
5. UI предлагает start заново.

### Сценарий: idempotent apply

1. Принять change;
2. Отправить apply и сымитировать потерю ответа;
3. Повторить apply с тем же `apply_id`;
4. Проверить один apply commit и одинаковый response;
5. Повтор с другим `apply_id` возвращает conflict.

---

## Operational validation

### Docker deployment

Проверить:

```bash
docker compose config
docker compose --profile core up -d --build
docker compose ps
```

Убедиться:

- `rag-backend` healthy;
- `rag-indexer` healthy;
- `rag-db` healthy;
- Redis healthy;
- backend и indexer имеют mount `${VAULTS_PATH}:/data/vaults:rw`;
- indexer internal API не имеет external port publish;
- backend знает `INDEXER_API_URL`;
- git установлен внутри indexer image.

### File permissions

Проверить в indexer container:

```bash
git --version
test -w /data/vaults
```

Проверить ownership/permissions на real vault root:

```bash
docker compose exec rag-indexer sh -lc \
  'test -d /data/vaults/<vault_id> && test -r /data/vaults/<vault_id> && test -w /data/vaults/<vault_id>'
```

Не публиковать результат с real private filenames/contents в logs.

### Observability

Добавить structured logs с полями:

```text
request_id
chat_id
campaign_id
apply_id
vault_id
change_id
document_id
action
file_path
status
error_code
commit_sha
reindex_task_id
duration_ms
```

Не логировать:

```text
original_content
proposed_content
unified_diff
full LLM context
raw LLM output
user note
API key
git stderr
```

### Health and recovery

Проверить:

- missing vault root не убивает indexer;
- git unavailable означает controlled 503 только для update mode;
- restart backend во время review не теряет Redis session;
- restart indexer до apply не делает file writes;
- retry apply с same apply ID не создаёт второй commit;
- manual file change между review и apply возвращает 409;
- failed reindex после commit остаётся visible UI result.

---

## Documentation updates

Обновить:

```text
plan-update/status.md
plan-update/ai-work-prompt.md
README / deployment docs, если в них документируется Docker services
```

Документировать:

- Campaign Update Mode работает только с `.md`;
- campaign tags обязательны;
- context берётся из indexed chunks;
- diff/apply выполняются по original files через indexer;
- Git history локальна в vault;
- apply может вернуть partial per-vault result;
- commit success не равен reindex success;
- session TTL 3 hours;
- отсутствуют delete/move/rename в MVP.

---

## Acceptance criteria фазы

- [ ] UI запускает update mode только для campaign chat.
- [ ] UI отправляет note, показывает loading, warnings и server-resolved diff.
- [ ] Пользователь явно принимает/отклоняет каждую правку.
- [ ] Review state переживает reload через Redis session.
- [ ] Expired session корректно показывается как restart-required.
- [ ] Apply использует один idempotent `apply_id`.
- [ ] Multi-vault results отображаются раздельно.
- [ ] UI показывает commit/reindex distinction.
- [ ] Нет frontend filesystem, git, path или checksum logic.
- [ ] E2E покрывает update, create рядом с parent, fallback create, conflict, expiry и idempotent retry.
- [ ] Docker deployment проверен с реальными mounts, git и internal indexer API.
- [ ] Baseline и новые тесты backend/indexer/frontend проходят.