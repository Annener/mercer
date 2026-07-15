# Фаза 2 — Data model, shared contracts и Redis review session

## Цель

Добавить минимальные долгоживущие DB-поля для git identity, определить строгие Pydantic contracts между UI, backend и indexer, а также реализовать Redis-хранилище review session.

Фаза не реализует retrieval, LLM generation, file resolution или apply. Её результат — валидируемые DTO и надёжный transient state.

---

## Принцип хранения состояния

| Тип данных | Где хранится | Причина |
|---|---|---|
| Git author override конкретного vault | PostgreSQL `vaults` | Долгоживущая DB-конфигурация vault |
| Active review session | Redis | Временное состояние с TTL |
| Accepted/rejected state changes | Redis session | Исчезает по cancel/expiry/final apply |
| File checksum и exact diff | Redis session | Привязаны к конкретному review |
| Git commit SHA и apply result | `AuditLog` | Долгоживущий audit trail |
| `update_mode_enabled` на Chat | Нигде | Избыточная и stale state |
| Vault filesystem path | Нигде | Deterministic deployment contract |
| Supported file extensions | Нигде | MVP поддерживает только `.md` |

---

## PostgreSQL migration

### Файл

Создать новую миграцию в фактическом configured path:

```text
rag-backend/migrations/versions/0005_campaign_update_git_identity.py
```

`down_revision` должен ссылаться на фактическую последнюю revision, которая на момент плана:

```text
0004_fix_sent_full_document_ids_jsonb
```

Перед созданием migration обязательно проверить текущий Alembic head:

```bash
cd rag-backend
alembic heads
```

Не использовать фиксированный revision filename, если после этого плана появились новые migrations. Нужно использовать следующий revision ID проекта и корректный `down_revision`.

### Upgrade

Добавить nullable fields в `vaults`:

```python
op.add_column(
    "vaults",
    sa.Column("git_author_name", sa.String(length=256), nullable=True),
)
op.add_column(
    "vaults",
    sa.Column("git_author_email", sa.String(length=320), nullable=True),
)
```

Требования:

- Нет server default;
- Existing rows остаются valid;
- Не добавлять `git_initialized`, `path`, `versioned_extensions`;
- Не менять текущие vault data;
- Не добавлять отдельную table для update sessions.

### Downgrade

```python
op.drop_column("vaults", "git_author_email")
op.drop_column("vaults", "git_author_name")
```

Использовать обычные Alembic operations, а не ручной DDL без необходимости. Alembic предоставляет операции изменения schema через `op`. [web:132]

---

## ORM update

### `rag-backend/app/db/models.py`

В SQLAlchemy ORM `Vault` добавить:

```python
git_author_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
git_author_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
```

Сохранить conventions текущей модели (`Mapped`, `mapped_column` или текущий project style).

Валидация email на ORM-уровне не нужна. В API/Pydantic DTO:

- `git_author_name`: trim, non-empty если задан;
- `git_author_email`: valid email format если задан.

Если project не использует Pydantic `EmailStr` и dependency отсутствует, использовать обычный `str` с консервативной validation; не добавлять новую dependency только для MVP.

### `VaultConfigService`

Расширить `VaultEntry`:

```python
git_author_name: str | None
git_author_email: str | None
```

Это нужно только для read/cache consistency. Update mode не должен использовать stale singleton cache для write decision.

После vault create/update/delete API должен продолжить вызывать текущий `VaultConfigService.refresh(db)` или invalidation pattern.

---

## Shared contracts

### Файл

Все cross-service DTO расположить в:

```text
shared_contracts/models.py
```

Не создавать duplicate Pydantic contracts отдельно в `rag-backend` и `rag-indexer`.

Models должны быть совместимы с Pydantic v2:

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator
```

Для Redis/HTTP JSON conversion применять:

```python
model.model_dump(mode="json")
```

и восстановление:

```python
Model.model_validate(payload)
```

`mode="json"` преобразует UUID, datetime и вложенные модели в JSON-compatible values. [web:151][web:154][web:156]

---

## Enums и базовые типы

Добавить:

```python
from enum import StrEnum
from typing import Literal
```

Если runtime Python version не поддерживает `StrEnum`, использовать:

```python
from enum import Enum

class StringEnum(str, Enum):
    pass
```

### `UpdateModeAction`

```python
class UpdateModeAction(str, Enum):
    UPDATE = "update"
    CREATE = "create"
```

### `UpdateModeOperation`

```python
class UpdateModeOperation(str, Enum):
    APPEND_AFTER_SECTION = "append_after_section"
    APPEND_TO_FILE = "append_to_file"
    REPLACE_UNIQUE_TEXT = "replace_unique_text"
    CREATE_FILE = "create_file"
```

### `UpdateModeChangeStatus`

```python
class UpdateModeChangeStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLUTION_FAILED = "resolution_failed"
```

### `UpdateModeVaultApplyStatus`

```python
class UpdateModeVaultApplyStatus(str, Enum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    FAILED = "failed"
    NO_CHANGES = "no_changes"
```

---

## LLM intent contracts

LLM output проходит Pydantic validation до отправки в indexer.

### `UpdateModeAnchor`

```python
class UpdateModeAnchor(BaseModel):
    kind: Literal["markdown_heading", "exact_text"]
    value: str = Field(min_length=1, max_length=16_384)
```

Validation:

- `markdown_heading` используется только с `append_after_section`;
- `exact_text` используется только с `replace_unique_text`;
- content не trim-ится автоматически, так как exact text может быть whitespace-sensitive;
- пустые и whitespace-only values запрещены.

### `UpdateModeIntent`

```python
class UpdateModeIntent(BaseModel):
    change_id: str
    action: UpdateModeAction
    description: str = Field(min_length=1, max_length=2_000)

    document_id: str | None = None
    parent_document_id: str | None = None

    operation: UpdateModeOperation
    anchor: UpdateModeAnchor | None = None

    suggested_filename: str | None = None
    content: str = Field(min_length=1, max_length=65_536)
```

`content` character limit — transport guard. Indexer дополнительно проверяет UTF-8 byte limit 64 KiB.

### Intent invariants

`model_validator(mode="after")` обязан enforce:

#### Update

```text
action == update
document_id is required
parent_document_id is null
suggested_filename is null
operation in:
  append_after_section
  append_to_file
  replace_unique_text
```

- `append_after_section` требует `anchor.kind == markdown_heading`;
- `replace_unique_text` требует `anchor.kind == exact_text`;
- `append_to_file` требует `anchor is None`.

#### Create

```text
action == create
document_id is null
operation == create_file
anchor is null
suggested_filename is required
parent_document_id optional
```

Нельзя принимать intent, где LLM одновременно передаёт `document_id` и `parent_document_id`.

### `UpdateModeIntentBatch`

```python
class UpdateModeIntentBatch(BaseModel):
    intents: list[UpdateModeIntent] = Field(min_length=1, max_length=10)
```

Validator:

- `change_id` уникален в batch;
- Ни один `document_id`/`parent_document_id` не может быть вне разрешённого `candidate_document_ids`;
- membership check выполняется backend executor после Pydantic validation, так как allowed IDs не являются свойством статической DTO.

---

## Internal indexer API contracts

### `UpdateModeResolveRequest`

```python
class UpdateModeResolveRequest(BaseModel):
    chat_id: str
    campaign_id: str
    domain_id: str
    vault_ids: list[str] = Field(min_length=1)
    intents: list[UpdateModeIntent] = Field(min_length=1, max_length=10)
    default_vault_id: str
    candidate_document_ids: list[str] = Field(min_length=0, max_length=15)
```

Rules:

- `vault_ids` — enabled vaults domain, найденные backend в момент start;
- `default_vault_id` выбирается backend deterministically;
- indexer не доверяет vault list без server-to-server boundary, но проверяет, что target каждого intent входит в request-vault scope;
- `default_vault_id` обязан входить в `vault_ids`;
- backend передаёт только validated LLM intents.

### `UpdateModeResolveResponse`

```python
class UpdateModeResolveResponse(BaseModel):
    changes: list["ResolvedUpdateModeChange"]
```

### `ResolvedUpdateModeChange`

```python
class ResolvedUpdateModeChange(BaseModel):
    change_id: str
    vault_id: str | None = None
    document_id: str | None = None
    file_path: str | None = None

    action: UpdateModeAction
    description: str

    original_content: str = ""
    proposed_content: str = ""
    unified_diff: str = ""
    expected_sha256: str | None = None

    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None
```

Invariants:

- `status == pending`:
  - `vault_id`, `file_path`, `unified_diff` required;
  - `expected_sha256` required for `update`;
  - `expected_sha256 is None` for `create`;
- `status == resolution_failed`:
  - `error_code` и user-safe `error_message` required;
  - no file write action is possible;
- `file_path` всегда canonical relative POSIX path, никогда absolute path.

### `UpdateModeApplyChange`

```python
class UpdateModeApplyChange(BaseModel):
    change_id: str
    vault_id: str
    file_path: str
    action: UpdateModeAction
    proposed_content: str
    expected_sha256: str | None = None
```

Apply request не принимает `original_content` и не принимает client-provided diff как source of truth.

### `UpdateModeApplyRequest`

```python
class UpdateModeApplyRequest(BaseModel):
    apply_id: str
    chat_id: str
    campaign_id: str
    accepted_changes: list[UpdateModeApplyChange] = Field(min_length=1, max_length=10)
```

Validation:

- `apply_id` UUID-formatted;
- unique `change_id`;
- unique `(vault_id, file_path)` pair;
- `file_path` is canonical relative path;
- update requires `expected_sha256`;
- create requires `expected_sha256 is None`.

### `UpdateModeVaultApplyResult`

```python
class UpdateModeVaultApplyResult(BaseModel):
    vault_id: str
    status: UpdateModeVaultApplyStatus
    applied_count: int = Field(ge=0)

    snapshot_commit_sha: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None

    reindex_task_id: str | None = None
    reindex_error: str | None = None

    error_code: str | None = None
    error_message: str | None = None
```

### `UpdateModeApplyResponse`

```python
class UpdateModeApplyResponse(BaseModel):
    apply_id: str
    results: list[UpdateModeVaultApplyResult] = Field(min_length=1)
```

---

## Public backend API contracts

### Start

```python
class StartUpdateModeRequest(BaseModel):
    note: str = Field(min_length=1, max_length=20_000)
```

```python
class StartUpdateModeResponse(BaseModel):
    chat_id: str
    expires_at: datetime
    changes: list[ResolvedUpdateModeChange]
    warnings: list[str] = Field(default_factory=list)
```

Start возвращает resolved changes в status:

```text
pending
resolution_failed
```

UI не должен автоматически принимать `pending`.

### Session

```python
class UpdateModeSessionResponse(BaseModel):
    chat_id: str
    campaign_id: str
    domain_id: str
    vault_ids: list[str]
    expires_at: datetime
    changes: list[ResolvedUpdateModeChange]
    warnings: list[str] = Field(default_factory=list)
```

### Review update

```python
class UpdateModeReviewRequest(BaseModel):
    accepted_change_ids: list[str] = Field(default_factory=list, max_length=10)
    rejected_change_ids: list[str] = Field(default_factory=list, max_length=10)
```

Rules:

- Sets не пересекаются;
- IDs должны существовать в current session;
- only `pending` changes may transition;
- `resolution_failed` changes нельзя accept;
- request может быть no-op только если UI явно refreshes session через GET; PATCH no-op вернуть `422`.

### Apply

```python
class ApplyUpdateModeRequest(BaseModel):
    apply_id: str | None = None
```

Если UI не передал `apply_id`, backend генерирует UUID и возвращает его.

```python
class ApplyUpdateModeResponse(BaseModel):
    apply_id: str
    results: list[UpdateModeVaultApplyResult]
```

### Cancel

```python
class CancelUpdateModeResponse(BaseModel):
    status: Literal["cancelled"]
```

Cancel удаляет Redis session. Он не меняет файлы и не создаёт git commit.

---

## Redis session contract

### Key

```text
update_mode:{chat_id}
```

### TTL

```text
3 hours
```

TTL обновляется только при explicit state-changing requests:

```text
start
review PATCH
apply begin
```

GET session не продлевает TTL бесконечно.

### `UpdateModeSession`

```python
class UpdateModeSession(BaseModel):
    session_id: str
    chat_id: str
    campaign_id: str
    domain_id: str

    vault_ids: list[str]
    default_vault_id: str
    candidate_document_ids: list[str]

    note: str
    warnings: list[str] = Field(default_factory=list)
    changes: list[ResolvedUpdateModeChange]

    created_at: datetime
    expires_at: datetime

    apply_id: str | None = None
    apply_started_at: datetime | None = None
```

Rules:

- `vault_ids` являются snapshot enabled vaults domain на момент start;
- `default_vault_id` обязан принадлежать `vault_ids`;
- `candidate_document_ids` — только document IDs, предоставленные LLM;
- `changes` максимум 10;
- `expires_at = created_at + 3 hours`;
- `apply_id` устанавливается atomically перед вызовом indexer apply;
- существующий `apply_id` не заменяется другим retry request.

### Redis serialization

```python
payload = session.model_dump(mode="json")
await redis.set(
    f"update_mode:{session.chat_id}",
    json.dumps(payload, ensure_ascii=False),
    ex=3 * 60 * 60,
)
```

Load:

```python
raw = await redis.get(key)
if raw is None:
    raise UpdateModeSessionExpiredError(chat_id)

session = UpdateModeSession.model_validate(json.loads(raw))
```

Для Pydantic v2 JSON-compatible dump использовать `model_dump(mode="json")`; UUID и datetime сериализуются без custom encoder. [web:151][web:154]

### Atomic update

Review PATCH и apply begin должны защищаться optimistic state update в Redis.

MVP implementation options:

1. `WATCH` + `MULTI/EXEC`;
2. Lua script;
3. existing project Redis helper, если он уже предоставляет compare-and-set.

Требование не зависит от механизма:

- два параллельных PATCH не должны терять accept/reject state друг друга;
- два параллельных apply не должны породить два разных `apply_id`;
- apply с уже установленным `apply_id` обязан вернуть тот же in-progress/final result, а не создать новую операцию.

---

## Backend service interfaces

### `UpdateModeStore`

Создать:

```text
rag-backend/app/services/update_mode_store.py
```

Методы:

```python
async def get(chat_id: str) -> UpdateModeSession | None: ...
async def create(session: UpdateModeSession) -> None: ...
async def update_review(
    chat_id: str,
    accepted_change_ids: set[str],
    rejected_change_ids: set[str],
) -> UpdateModeSession: ...
async def begin_apply(
    chat_id: str,
    requested_apply_id: str | None,
) -> UpdateModeSession: ...
async def delete(chat_id: str) -> None: ...
```

Store не знает:

- SQLAlchemy;
- LLM;
- filesystem;
- git;
- indexer HTTP details.

### `IndexerClient`

Создать:

```text
rag-backend/app/services/indexer_client.py
```

Методы:

```python
async def resolve_update_mode(
    request: UpdateModeResolveRequest,
) -> UpdateModeResolveResponse: ...

async def apply_update_mode(
    request: UpdateModeApplyRequest,
) -> UpdateModeApplyResponse: ...
```

Client:

- использует `httpx.AsyncClient`;
- timeout определён явно;
- преобразует connection/timeout/5xx в typed `IndexerUnavailableError`;
- не преобразует expected typed 4xx conflict в generic 500;
- логирует request correlation ID без original file contents;
- не пишет filesystem или git fallback.

`INDEXER_API_URL` остаётся deployment connection setting, не vault configuration.

---

## API route skeleton

Создать router:

```text
rag-backend/app/api/update_mode.py
```

Prefix:

```text
/api/chats/{chat_id}/update-mode
```

Endpoints:

```text
POST   /start
GET    /session
PATCH  /review
POST   /apply
DELETE /session
```

Подключить router к backend application.

Все routes используют:

```python
db: AsyncSession = Depends(get_db)
```

и response models из `shared_contracts.models`.

Не добавлять update-mode DTO как локальные router classes.

---

## Тесты

### Migration/ORM

- migration upgrade создаёт оба nullable column;
- migration downgrade удаляет оба column;
- existing `Vault` without identity валиден;
- `VaultConfigService.refresh()` отражает новые fields.

### Shared contracts

- valid update intents;
- invalid action/operation combinations;
- heading anchor required only for `append_after_section`;
- exact text required only for `replace_unique_text`;
- create intent cannot contain `document_id`;
- duplicate `change_id` rejected;
- `UpdateModeApplyRequest` rejects duplicate `(vault_id, file_path)`;
- update requires expected SHA;
- create requires no expected SHA;
- JSON roundtrip `model_dump(mode="json")` → `model_validate`;
- UUID/datetime values survive session roundtrip.

### Store

- create/get/delete;
- TTL exactly three hours;
- same chat second create produces `session_already_active`;
- accepted/rejected sets cannot overlap;
- unknown ID rejected;
- resolution failed cannot be accepted;
- concurrent review updates do not lose state;
- first apply sets `apply_id`;
- retry with same apply ID returns existing operation;
- retry with different apply ID after begin is conflict;
- expired key maps to `session_expired`.

### Indexer client

- successful resolve/apply contract serialization;
- 409 preserves typed conflict;
- 410 preserves session expired mapping where relevant;
- connection failure → indexer unavailable;
- timeout → indexer unavailable;
- response validation failure → internal integration error with safe logging.

---

## Acceptance criteria фазы

- [ ] Alembic migration добавляет только optional `git_author_name` и `git_author_email`.
- [ ] ORM и vault cache отражают новые fields.
- [ ] Все public/internal update-mode DTO живут в `shared_contracts/models.py`.
- [ ] LLM intent нельзя использовать для arbitrary file paths.
- [ ] Redis session содержит полный review state, имеет TTL 3 часа и безопасный JSON serialization.
- [ ] Нет persisted `Chat.update_mode_enabled` или Vault path/extensions state.
- [ ] Review и apply защищены от параллельных updates.
- [ ] Indexer client является единственным backend HTTP boundary к indexer.
- [ ] Router skeleton подключён, но business logic следующей фазы ещё может быть stubbed.
- [ ] Unit tests contracts, migration и store проходят.