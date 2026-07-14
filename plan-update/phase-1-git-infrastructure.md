# Фаза 1 — Git-инфраструктура

**Цель фазы**: Добавить в каждый vault собственный локальный git-репозиторий.
После фазы: при старте сервиса все vault имеют инициализированный `.git`,
новые vault получают git при создании, `vault_git_service.py` покрыт тестами.

**Зависимости**: нет (первая фаза)
**Следующая фаза**: [Фаза 2 — Модель данных](phase-2-data-model.md)

---

## Контекст для чтения

Перед началом работы прочитай:
- `context/architecture.md` — понять структуру сервисов и как vault хранится на диске
- `context/db_schema.md` — понять модель Vault
- `rag-backend/app/config.py` — понять VaultConfig и AppConfig
- `rag-backend/app/main.py` — найти lifespan/startup хук
- `rag-backend/app/db/models.py` — ORM Vault

---

## Задачи

### 1.1 — Новый сервис `vault_git_service.py`

Создать файл `rag-backend/app/services/vault_git_service.py`.

Сервис должен реализовывать:

```python
async def ensure_repo(vault_path: str) -> None:
    """
    Если .git не существует — выполнить git init.
    Idempotent: повторный вызов на уже инициализированном репо — no-op.
    """

async def init_all_vaults(vaults: list[dict]) -> dict[str, str]:
    """
    Принимает список {vault_id, path} из БД.
    Для каждого vault вызывает ensure_repo(path).
    Возвращает dict vault_id -> status ("ok" | "skipped" | "error: <msg>").
    Логирует результат каждого vault.
    """

def get_git_env(author_name: str, author_email: str) -> dict:
    """
    Возвращает dict с GIT_AUTHOR_NAME, GIT_AUTHOR_EMAIL, GIT_COMMITTER_NAME,
    GIT_COMMITTER_EMAIL для передачи в subprocess.
    НЕ трогает глобальный git config.
    """

async def snapshot_commit(vault_path: str, git_env: dict) -> str | None:
    """
    Если рабочее дерево 'грязное' (есть незакоммиченные изменения) — 
    добавить staged только versioned_extensions файлы и сделать commit:
    'snapshot: manual edits before AI campaign update'
    Возвращает sha коммита или None если nothing to commit.
    """

async def apply_commit(
    vault_path: str,
    git_env: dict,
    versioned_extensions: list[str],
    commit_message: str,
) -> str:
    """
    git add только файлы с разрешёнными расширениями,
    git commit с указанным message.
    Возвращает sha нового коммита.
    """
```

**Важные требования реализации**:
- Все subprocess-вызовы через `asyncio.create_subprocess_exec` (не `subprocess.run`)
- `cwd=vault_path` для всех git-команд
- Передавать git identity через `env=git_env`, не через `--global`
- При `git add` — использовать `versioned_extensions`: `git add -- $(find . -name "*.md")`
  или через Python `pathlib.Path.rglob("*.md")` → `git add <files>`
- Логировать все вызовы через `logging.getLogger(__name__)`
- Все ошибки subprocess оборачивать в `VaultGitError(Exception)` с vault_id в message

### 1.2 — Добавить GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL в конфиг

В `rag-backend/app/config.py` в класс `AppConfig` добавить:

```python
git_author_name: str = "Mercer"
git_author_email: str = "mercer@local"
```

Читать из environment variables через Pydantic `Field(default=..., alias=...)` или
стандартный `os.getenv` в lifespan.

### 1.3 — Lifespan: git init всех vault при старте

В `rag-backend/app/main.py` в startup-хуке (lifespan):

```python
# После инициализации БД и загрузки конфига:
vault_paths = [(v.vault_id, v.path) for v in config.vaults.values()]
results = await vault_git_service.init_all_vaults(vault_paths)
logger.info(f"Vault git init: {results}")
```

**Важно**: init_all_vaults не должна падать при ошибке одного vault.
Логировать ошибку и продолжать для остальных.

### 1.4 — Git init при создании нового vault

Найти эндпоинт создания vault (скорее всего в `rag-backend/app/api/`).
После успешного создания vault в БД вызвать:

```python
await vault_git_service.ensure_repo(vault_config.path)
```

---

## Тесты — `rag-backend/app/tests/test_vault_git_service.py`

Создать файл с тестами:

```python
# test_vault_git_service.py

async def test_ensure_repo_creates_git(tmp_path):
    """ensure_repo создаёт .git в пустой директории"""

async def test_ensure_repo_idempotent(tmp_path):
    """Повторный вызов ensure_repo на уже инициализированном репо — no-op, не падает"""

async def test_snapshot_commit_dirty(tmp_path):
    """snapshot_commit создаёт коммит если есть незакоммиченные .md файлы"""

async def test_snapshot_commit_clean(tmp_path):
    """snapshot_commit возвращает None если working tree чистый"""

async def test_apply_commit_only_versioned(tmp_path):
    """apply_commit добавляет в коммит только файлы с разрешёнными расширениями"""
    # Создать .md и .pdf в vault_path
    # apply_commit с versioned_extensions=[".md"]
    # Проверить что .pdf не попал в коммит

async def test_get_git_env_does_not_touch_global_config():
    """get_git_env возвращает корректный dict без изменения глобального git config"""
```

Использовать `pytest-asyncio`, моки через `unittest.mock.AsyncMock` для subprocess.

---

## Критерий готовности фазы

- [ ] `vault_git_service.py` создан и покрыт тестами
- [ ] `AppConfig` содержит `git_author_name`, `git_author_email`
- [ ] При старте сервиса все vault получают git init (логи видны)
- [ ] При создании нового vault через API — git init вызывается
- [ ] Все тесты фазы 1 проходят
- [ ] Глобальный git config пользователя не изменяется
