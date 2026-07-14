# Фаза 2 — Модель данных

**Цель фазы**: Добавить в БД и shared_contracts все поля, необходимые для
Campaign Update Mode. После фазы: Vault хранит `versioned_extensions`,
`git_author_name/email`; Chat хранит `update_mode_enabled`;
shared_contracts содержат `ProposedChange` и `UpdateModeSession`.

**Зависимости**: [Фаза 1](phase-1-git-infrastructure.md) завершена
**Следующая фаза**: [Фаза 3 — Сбор контекста и генерация правок](phase-3-executor.md)

---

## Контекст для чтения

Перед началом работы прочитай:
- `context/db_schema.md` — текущая схема БД
- `context/shared_contracts.md` — текущие Pydantic-схемы
- `rag-backend/app/db/models.py` — ORM Vault и Chat
- `shared_contracts/models.py` — добавить новые типы
- Последнюю Alembic-миграцию в `rag-backend/alembic/versions/` — понять naming convention

---

## Задачи

### 2.1 — ORM: новые поля Vault

В `rag-backend/app/db/models.py` в класс `Vault` добавить:

```python
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy import String

# --- Campaign Update Mode ---
versioned_extensions: Mapped[list[str]] = mapped_column(
    ARRAY(String(16)),
    nullable=False,
    default=list,
    server_default="'{\"  .md\"}'",  # PostgreSQL ARRAY literal
)
git_author_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
git_author_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
```

**Важно**: дефолт `versioned_extensions = [".md"]` — это default для **новых** vault.
Для существующих vault после миграции поле будет `[]` (пустой массив),
что нужно обработать в `vault_git_service`: если пусто — использовать `[".md"]`.

### 2.2 — ORM: новые поля Chat

В `rag-backend/app/db/models.py` в класс `Chat` добавить:

```python
# --- Campaign Update Mode ---
update_mode_enabled: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False, server_default="false"
)
```

Pending changes (список ProposedChange) **не хранятся в PostgreSQL** —
они живут в Redis с TTL. В БД только флаг режима.

### 2.3 — Alembic-миграция

Создать новый файл миграции в `rag-backend/alembic/versions/`.
Название по convention проекта: `NNNN_campaign_update_mode_fields.py`

Миграция должна:
```python
def upgrade():
    # vaults
    op.add_column('vaults', sa.Column(
        'versioned_extensions', 
        postgresql.ARRAY(sa.String(16)), 
        nullable=False, 
        server_default="'{}'"  # пустой массив для существующих
    ))
    op.add_column('vaults', sa.Column('git_author_name', sa.String(128), nullable=True))
    op.add_column('vaults', sa.Column('git_author_email', sa.String(256), nullable=True))
    # chats
    op.add_column('chats', sa.Column(
        'update_mode_enabled', sa.Boolean(), 
        nullable=False, server_default='false'
    ))

def downgrade():
    op.drop_column('chats', 'update_mode_enabled')
    op.drop_column('vaults', 'git_author_email')
    op.drop_column('vaults', 'git_author_name')
    op.drop_column('vaults', 'versioned_extensions')
```

### 2.4 — Shared Contracts: новые типы

В `shared_contracts/models.py` добавить:

```python
# ---------------------------------------------------------------------------
# Campaign Update Mode contracts
# ---------------------------------------------------------------------------

class ProposedChange(BaseModel):
    """Одно предложенное изменение файла из Campaign Update Mode."""
    change_id: str                          # uuid4 как строка
    file_path: str                          # относительный путь внутри vault
    action: Literal["update", "create"]
    description: str                        # краткое описание для UI
    original_content: str                   # текущее содержимое ("" для create)
    proposed_content: str                   # предложенное содержимое
    status: Literal["pending", "accepted", "rejected"] = "pending"


class UpdateModeSession(BaseModel):
    """Сессия Campaign Update Mode, хранится в Redis.
    
    Ключ Redis: update_mode:{chat_id}
    TTL: 3600 секунд (1 час)
    """
    chat_id: str
    campaign_id: str
    vault_id: str
    original_note: str                      # исходная заметка пользователя
    changes: list[ProposedChange]
    context_token_count: int = 0            # для отображения в UI
    created_at: datetime


class UpdateModeStartRequest(BaseModel):
    """POST /chats/{chat_id}/update-mode/start"""
    note: str                               # заметка пользователя


class UpdateModeChangeAction(BaseModel):
    """POST /chats/{chat_id}/update-mode/changes/{change_id}/action"""
    action: Literal["accept", "reject", "rephrase"]
    instruction: str | None = None          # обязателен для action=rephrase


class UpdateModeApplyRequest(BaseModel):
    """POST /chats/{chat_id}/update-mode/apply"""
    # apply применяет все accepted changes
    # можно передать commit_message или система сгенерирует через LLM
    commit_message: str | None = None
```

### 2.5 — VaultRead / VaultUpdate: новые поля

В `shared_contracts/models.py` в `VaultRead` добавить:
```python
versioned_extensions: list[str] = Field(default_factory=lambda: [".md"])
git_author_name: str | None = None
git_author_email: str | None = None
```

В `VaultUpdate` добавить:
```python
versioned_extensions: list[str] | None = None
git_author_name: str | None = None
git_author_email: str | None = None
```

В `ChatRecord` добавить:
```python
update_mode_enabled: bool = False
```

---

## Тесты — `rag-backend/app/tests/test_update_mode_models.py`

```python
def test_proposed_change_defaults():
    """ProposedChange создаётся с status=pending"""

def test_update_mode_session_serialization():
    """UpdateModeSession сериализуется в JSON и обратно без потерь"""

def test_vault_read_versioned_extensions_default():
    """VaultRead.versioned_extensions дефолтится в [\".md\"] при пустом поле БД"""

def test_update_mode_change_action_rephrase_requires_instruction():
    """UpdateModeChangeAction action=rephrase без instruction — допустима (instruction nullable),
    но executor должен это проверять"""
```

---

## Критерий готовности фазы

- [ ] Alembic-миграция создана и применяется без ошибок
- [ ] `Vault` ORM содержит `versioned_extensions`, `git_author_name`, `git_author_email`
- [ ] `Chat` ORM содержит `update_mode_enabled`
- [ ] `VaultRead`, `VaultUpdate`, `ChatRecord` обновлены в shared_contracts
- [ ] `ProposedChange`, `UpdateModeSession`, `UpdateModeStartRequest`,
  `UpdateModeChangeAction` добавлены в shared_contracts
- [ ] Тесты модели проходят
- [ ] `context/shared_contracts.md` и `context/db_schema.md` обновлены
