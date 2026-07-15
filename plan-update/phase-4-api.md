# Фаза 4 — Review, apply, git и targeted reindex

## Цель

Реализовать безопасный путь от подготовленного Redis review session к фактическим изменениям файлов:

1. Пользователь принимает/отклоняет resolved changes;
2. Backend атомарно фиксирует review state в Redis;
3. Backend передаёт только accepted changes в indexer;
4. Indexer проверяет original file state;
5. Indexer snapshot’ит затрагиваемые `.md`;
6. Indexer применяет atomic writes;
7. Indexer коммитит только explicit target paths;
8. Indexer стартует targeted reindex;
9. Backend сохраняет AuditLog и возвращает per-vault results.

Фаза не добавляет frontend components; UI integration — фаза 5.

---

## Изменяемые файлы

```text
rag-backend/
├── app/
│   ├── api/update_mode.py
│   ├── services/update_mode_executor.py
│   ├── services/update_mode_store.py
│   ├── services/indexer_client.py
│   └── db/models.py
└── tests/
    ├── test_update_mode_store.py
    ├── test_update_mode_executor.py
    └── test_update_mode_api.py

rag-indexer/
├── api/update_mode.py
├── main.py
├── services/
│   ├── vault_paths.py
│   ├── vault_git_service.py
│   ├── update_mode_file_service.py
│   └── update_mode_apply_service.py
└── tests/
    ├── test_update_mode_internal_api.py
    └── test_update_mode_apply_service.py

shared_contracts/
└── models.py
```

Названия router registration и indexer app entrypoint должны соответствовать реальной project structure.

---

## Review API

### Получение сессии

```text
GET /api/chats/{chat_id}/update-mode/session
```

Поведение:

- Load Redis session;
- Если key отсутствует — `410 session_expired` + `Cache-Control: no-store`;
- Возвращает весь `UpdateModeSessionResponse`;
- Не продлевает Redis TTL;
- Не читает файлы и не обращается к LLM/indexer.

### Принятие/отклонение changes

```text
PATCH /api/chats/{chat_id}/update-mode/review
```

Request:

```json
{
  "accepted_change_ids": ["change-1", "change-2"],
  "rejected_change_ids": ["change-3"]
}
```

Backend rules:

1. Сессия должна существовать;
2. `accepted_change_ids` и `rejected_change_ids` не пересекаются;
3. Все IDs должны принадлежать current session;
4. Только `pending` changes могут менять state;
5. `resolution_failed` нельзя принять;
6. Repeated identical action:
   - accept already accepted → no-op допустим;
   - reject already rejected → no-op допустим;
   - accept rejected или reject accepted → `409 review_state_conflict`;
7. Полностью empty request → `422`;
8. После успешного PATCH Redis TTL refresh до 3 часов;
9. Return updated session.

Review state существует только в Redis. Никаких Chat flags или DB updates не добавлять.

### Cancel

```text
DELETE /api/chats/{chat_id}/update-mode/session
```

Поведение:

- Удаляет Redis key;
- Ничего не меняет в filesystem;
- Ничего не делает с git;
- Возвращает `204 No Content`;
- Повторный cancel отсутствующей/истекшей session также возвращает `204`, потому что желаемое состояние уже достигнуто.

---

## Apply API

### Public endpoint

```text
POST /api/chats/{chat_id}/update-mode/apply
```

Request:

```json
{
  "apply_id": "optional-uuid"
}
```

Response:

```json
{
  "apply_id": "uuid",
  "results": [
    {
      "vault_id": "dnd-main",
      "status": "applied",
      "applied_count": 2,
      "snapshot_commit_sha": "a1b2c3",
      "commit_sha": "d4e5f6",
      "commit_message": "campaign-update: apply reviewed changes",
      "reindex_task_id": "task-id",
      "reindex_error": null
    }
  ]
}
```

### Backend apply flow

#### 1. Begin apply atomically

`UpdateModeStore.begin_apply()` обязан выполнить compare-and-set.

Rules:

- Session missing → `410 session_expired`;
- Найти accepted changes;
- Если accepted changes нет → `422 no_accepted_changes`;
- Если `session.apply_id is None`:
  - принять client UUID, если он валиден, либо создать UUID;
  - установить `apply_id`;
  - установить `apply_started_at`;
  - обновить TTL до 3 часов;
- Если `session.apply_id == requested apply_id`:
  - это retry;
  - не вызывать indexer второй раз, если store уже содержит final result;
  - вернуть сохранённый in-progress/final result;
- Если `session.apply_id != requested apply_id`:
  - вернуть `409 apply_already_started`.

В этой фазе расширить `UpdateModeSession` полями:

```python
apply_result: UpdateModeApplyResponse | None = None
apply_state: Literal["review", "in_progress", "completed"] = "review"
```

`apply_state` должен меняться атомарно с `apply_id`.

#### 2. Построить internal apply request

В request включать только accepted changes:

```python
accepted_changes = [
    UpdateModeApplyChange(
        change_id=change.change_id,
        vault_id=change.vault_id,
        file_path=change.file_path,
        action=change.action,
        proposed_content=change.proposed_content,
        expected_sha256=change.expected_sha256,
    )
    for change in session.changes
    if change.status == UpdateModeChangeStatus.ACCEPTED
]
```

Не доверять client-provided file path, diff, content или accepted list.

#### 3. Вызвать indexer

```python
result = await indexer_client.apply_update_mode(
    UpdateModeApplyRequest(
        apply_id=session.apply_id,
        chat_id=session.chat_id,
        campaign_id=session.campaign_id,
        accepted_changes=accepted_changes,
    )
)
```

Если connection/timeout до indexer:

- Не очищать session;
- Оставить `apply_state = in_progress`;
- Return `503 indexer_unavailable`;
- Повтор с тем же `apply_id` не должен создать второй логический apply.

#### 4. Сохранить final result

Когда indexer вернул valid response:

```python
await store.complete_apply(chat_id, result)
```

`complete_apply` сохраняет result в session атомарно.

После этого backend:

1. Добавляет AuditLog;
2. Возвращает result;
3. Удаляет Redis session только если все vault results terminal и backend AuditLog write успешен.

### Session cleanup policy

| Состояние результата | Сессия |
|---|---|
| Все vault `applied` или `no_changes` | Удалить после AuditLog |
| Есть `conflict` или `failed` | Оставить до TTL для просмотра ошибок |
| Indexer unavailable/timeout | Оставить как `in_progress` |
| AuditLog failure после apply | Не удалять; залогировать критично |
| Retry с тем же apply ID | Вернуть сохранённый result, не применять повторно |

---

## Internal indexer router

### Endpoint

```text
POST /internal/update-mode/apply
```

Router должен быть подключён к indexer FastAPI application, но не опубликован наружу через Docker `ports`.

Endpoint принимает `UpdateModeApplyRequest` и возвращает `UpdateModeApplyResponse`.

Router не содержит git/file logic. Он:

1. Валидирует DTO;
2. Вызывает `UpdateModeApplyService`;
3. Преобразует typed domain exceptions в typed HTTP errors;
4. Логирует request ID, apply ID и vault IDs без content.

### Internal authorization

Если в проекте есть service token mechanism:

```text
X-Internal-Service-Token
```

— использовать его.

Если такой mechanism отсутствует, в MVP:

- endpoint остаётся только в Docker internal network;
- backend обращается через `INDEXER_API_URL`;
- `rag-indexer` не получает host port mapping;
- добавить TODO с явным security debt в `status.md`.

Не добавлять произвольную auth framework ради single-user local MVP.

---

## `UpdateModeApplyService`

### Responsibility

Создать:

```text
rag-indexer/services/update_mode_apply_service.py
```

Сервис владеет:

- grouping changes by vault;
- vault lock;
- path revalidation;
- checksum revalidation;
- snapshot;
- atomic write;
- git commit;
- targeted reindex;
- per-vault results;
- apply idempotency.

Он не знает campaign tags, LLM, chat history или UI.

### Per-vault processing

Группировать accepted changes:

```python
changes_by_vault: dict[str, list[UpdateModeApplyChange]]
```

Обрабатывать vault groups в deterministic `vault_id` order.

Для каждого vault вернуть отдельный `UpdateModeVaultApplyResult`.

Multi-vault apply не является distributed transaction. Если vault A применился, а vault B конфликтует, A не откатывается автоматически.

### Lock

Использовать Redis distributed lock с key:

```text
update_mode:lock:vault:{vault_id}
```

Parameters:

```text
TTL: 60 seconds
wait timeout: short and explicit, например 5 seconds
```

Lock scope включает:

```text
checksum verify
snapshot
atomic writes
git commit
targeted reindex start
```

Не отпускать lock между checksum verification и write.

Всегда освобождать lock в `finally`, только если owner token совпадает.

Если lock не получен:

```text
status: conflict
error_code: vault_lock_timeout
```

Не блокировать обработку других vault groups.

### Final path revalidation

Перед apply для каждой change:

1. Вызвать `resolve_vault_root(vault_id)`;
2. Вызвать `resolve_existing_markdown()` для update;
3. Для create повторно вызвать `resolve_create_target()`;
4. Проверить file path из request против freshly resolved canonical path;
5. Не использовать path string без повторной validation.

При invalid path вернуть per-vault failure, не выполнять частичный write для этого vault.

### Preflight first, write second

Для каждого vault до любого write выполнить preflight всех changes:

- все targets валидны;
- paths не дублируются;
- update file существует;
- update checksum совпадает с expected SHA;
- create target отсутствует;
- content лимиты соблюдены;
- git capability и identity доступны;
- targets не git ignored.

Если хотя бы один change в vault не проходит preflight:

- не snapshot;
- не писать никакой файл этого vault;
- вернуть vault result `conflict` или `failed`;
- остальные vault могут продолжить processing.

Это даёт atomicity на уровне одного vault apply group.

### Duplicate target prohibition

Backend DTO уже запрещает duplicate `(vault_id, file_path)`, но indexer повторяет проверку.

Для одного vault нельзя одновременно:

```text
update same file twice
create same file twice
create and update same file
```

Это `failed: duplicate_target`.

### Snapshot flow

После successful preflight:

1. Получить target canonical relative paths;
2. Выполнить `vault_git_service.snapshot_paths(...)`;
3. Сохранить `snapshot_commit_sha`, если commit был создан;
4. Если snapshot failed — прекратить этот vault, не писать files.

Snapshot имеет право закоммитить только modifications target `.md` files, существовавшие до apply.

Unrelated dirty files остаются untouched и uncommitted.

### Atomic writes

После snapshot:

1. Для каждого change применить `atomic_write`;
2. Порядок — canonical relative path sort;
3. Если write одной change неожиданно fails:
   - не выполнять последующие writes;
   - вернуть `failed: write_failed`;
   - логировать какие files были уже заменены;
   - не пытаться автоматически делать сложный rollback поверх ручных concurrent edits;
   - snapshot commit остаётся recovery point;
   - apply result должен явно включать `manual_recovery_required`.

Перед каждым write дополнительно повторить checksum/absence, даже если проверка уже была в preflight.

`os.replace()` заменяет file атомарно при работе в одной filesystem; temporary file должен создаваться в той же directory target file. [web:174][web:176][web:177]

### Apply commit

Если все atomic writes vault group прошли:

```python
commit_sha = await vault_git_service.commit_paths(
    vault_root=vault_root,
    relative_paths=target_paths,
    message=commit_message,
    identity=identity,
)
```

Fallback message:

```text
campaign-update: apply reviewed changes
```

Если commit failed после writes:

- result: `failed`;
- `error_code: git_commit_failed`;
- `manual_recovery_required: true`;
- не запускать targeted reindex;
- files остаются изменёнными в working tree;
- snapshot commit служит recovery point.

Не выполнять rollback файлов автоматически: rollback может затереть внешнюю правку, появившуюся после atomic write.

### Targeted reindex

После successful commit вызвать существующий indexer task mechanism.

Нужно добавить/расширить API task contract так, чтобы он поддерживал список конкретных relative markdown paths:

```python
class StartIndexTaskRequest(BaseModel):
    vault_id: str
    force_reindex: bool = False
    source_paths: list[str] | None = None
```

Rules:

- `source_paths` optional, чтобы не ломать существующие callers;
- если `source_paths is None`, current full-vault behavior остаётся;
- если list задан, indexer обрабатывает только validated supplied source paths;
- source paths берутся только из successfully committed canonical target list;
- scanner/parser не должен принимать raw user path.

### Изменения indexer worker

В `run_indexing(...)` добавить optional parameter:

```python
source_paths: set[str] | None = None
```

Когда set задан:

1. Scanner всё ещё получает filesystem files безопасно;
2. После scan фильтрует по canonical relative path membership;
3. Не обрабатывает файлы вне target list;
4. Корректно создаёт/обновляет `Document` для new files;
5. Старые chunks для changed document удаляются до new upsert, как делает текущая reindex logic;
6. Task state включает только target files.

Не передавать `source_paths` непосредственно в `parse_file()` без scan/path validation.

### Reindex failure

Если git commit успешен, но targeted reindex start failed:

```text
status: applied
commit_sha: set
reindex_task_id: null
reindex_error: safe message
```

Это не откатывает commit.

Ручной watchdog остаётся fallback и может всё равно поймать change, но UI должен явно показать, что indexed state ещё не подтверждён.

---

## Apply idempotency в indexer

### Key

```text
update_mode:apply:{apply_id}
```

### State

```python
class IndexerApplyState(BaseModel):
    apply_id: str
    request_fingerprint: str
    status: Literal["in_progress", "completed"]
    response: UpdateModeApplyResponse | None = None
    created_at: datetime
```

`request_fingerprint` — SHA-256 canonical JSON payload без volatile fields.

### Rules

1. Перед началом apply atomically проверить key;
2. Если key отсутствует:
   - записать `in_progress` с TTL не меньше Redis session TTL;
   - продолжить processing;
3. Если key `completed` и fingerprint совпадает:
   - вернуть сохранённый response;
4. Если key существует и fingerprint отличается:
   - return `409 apply_id_payload_mismatch`;
5. Если key `in_progress`:
   - return `409 apply_in_progress`, либо short poll existing final result;
   - не запускать второй apply;
6. После final result сохранить completed response с TTL 3 hours.

Backend retry обязан передавать идентичный `apply_id` и accepted changes.

---

## Audit log

После final indexer response backend создаёт один `AuditLog`:

```python
AuditLog(
    action="campaign_update.apply",
    entity_type="chat",
    entity_id=str(chat_id),
    details={
        "apply_id": apply_id,
        "campaign_id": campaign_id,
        "vault_results": [
            {
                "vault_id": result.vault_id,
                "status": result.status,
                "applied_count": result.applied_count,
                "snapshot_commit_sha": result.snapshot_commit_sha,
                "commit_sha": result.commit_sha,
                "reindex_task_id": result.reindex_task_id,
                "error_code": result.error_code,
            }
            for result in response.results
        ],
    },
)
```

Запрещено записывать в AuditLog:

- original file content;
- proposed content;
- diff;
- note, если она потенциально содержит чувствительную campaign information;
- LLM raw output;
- git stderr.

---

## Ошибки и status mapping

### Backend public API

| Ситуация | HTTP | Code |
|---|---:|---|
| Нет session | 410 | `session_expired` |
| Нет accepted changes | 422 | `no_accepted_changes` |
| Другой apply уже начат | 409 | `apply_already_started` |
| Indexer unavailable | 503 | `indexer_unavailable` |
| Indexer returns conflict only | 409 | `apply_conflict` |
| Partial success | 200 | `results` содержат per-vault states |
| All vault failed internal | 502/503 по причине | typed safe code |

### Indexer internal API

| Ситуация | HTTP | Code |
|---|---:|---|
| Невалидный payload | 422 | FastAPI/Pydantic |
| Lock unavailable | 409 | `vault_lock_timeout` |
| File checksum changed | 409 | `file_modified` |
| Create target exists | 409 | `target_exists` |
| Root missing | 409 | `vault_root_missing` |
| Git missing | 503 | `git_unavailable` |
| Unexpected internal failure | 500 | `internal_update_mode_error` |

Per-vault errors при multi-vault processing предпочтительно возвращать `200` с result list, когда хотя бы один vault обработан или все errors являются expected per-vault outcomes. HTTP error использовать для request-level failures.

---

## Тесты

### Backend review/session

- get existing session does not refresh TTL;
- expired session returns 410 + `Cache-Control: no-store`;
- review accepts/rejects valid pending changes;
- review rejects overlapping IDs;
- review rejects unknown IDs;
- resolution failed cannot be accepted;
- repeated same state is no-op;
- contradictory state change returns 409;
- cancel removes session and is idempotent.

### Backend apply

- apply with no accepted changes returns 422;
- begin apply is atomic;
- second concurrent apply does not call indexer twice;
- retry same apply ID returns stored result;
- different apply ID after start returns 409;
- indexer unavailable retains session;
- completed success creates AuditLog and cleans session;
- partial conflict creates AuditLog and retains session;
- audit log never includes content/diff/note.

### Indexer apply service

- groups changes by vault deterministically;
- one vault conflict does not prevent second vault processing;
- lock is released in `finally`;
- lock timeout creates per-vault conflict;
- preflight detects stale checksum before any write;
- create collision before write creates conflict;
- duplicate target prevents all writes in vault;
- snapshot only targets changed markdown;
- unrelated dirty file remains unstaged;
- atomic write only after preflight success;
- git commit uses explicit target paths;
- commit failure after writes returns manual recovery marker;
- successful commit starts targeted reindex with exact canonical paths;
- reindex start failure preserves successful commit result;
- same apply ID returns stored response;
- same apply ID with altered payload returns 409;
- in-progress duplicate does not execute another write.

### Targeted indexing

- existing full-vault index request remains backward compatible;
- targeted request processes only supplied source paths;
- source path outside vault is rejected before task start;
- new markdown creates Document record and chunks;
- changed markdown deletes/replaces old chunks;
- task state contains only target file paths;
- normal watchdog path remains functional.

---

## Acceptance criteria фазы

- [ ] Review API безопасно меняет accepted/rejected state в Redis.
- [ ] Apply использует только server-side resolved changes из current session.
- [ ] Indexer является единственным writer и git owner.
- [ ] Каждый vault проходит full preflight до первой записи.
- [ ] Checksum conflict не перезаписывает ручное изменение.
- [ ] Snapshot и apply commits stage’ят только explicit affected markdown files.
- [ ] Write выполняется атомарно через temp file в той же directory и `os.replace`.
- [ ] Multi-vault partial result прозрачно возвращается.
- [ ] Apply idempotency предотвращает duplicate commits при retry.
- [ ] После commit запускается targeted reindex и response содержит per-vault task IDs.
- [ ] AuditLog содержит только metadata, без campaign contents.
- [ ] Backend/indexer/unit/integration tests проходят.