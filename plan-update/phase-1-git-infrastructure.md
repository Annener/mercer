# Фаза 1 — Git foundation и безопасный файловый слой indexer

## Цель

Создать в `rag-indexer` единственный безопасный слой, который:

- резолвит vault root;
- читает только разрешённые оригинальные `.md`;
- валидирует относительные пути и имена новых файлов;
- инициализирует local git repository на vault;
- создаёт snapshot и apply commits только для явно перечисленных файлов;
- предоставляет точные checksum и atomic writes.

Эта фаза ещё не добавляет LLM, campaign retrieval, Redis review session или публичный update-mode UI.

---

## Результат фазы

После завершения фазы indexer умеет безопасно выполнить следующие локальные операции для одного vault:

```text
resolve existing .md file
read original content
calculate SHA-256
check git capability
initialize git repository
snapshot a supplied explicit list of changed .md files
atomically write supplied content
commit only supplied explicit .md files
```

`rag-backend` не вызывает эти helpers напрямую. Они будут использованы internal indexer API в следующих фазах.

---

## Новые файлы

```text
rag-indexer/
├── services/
│   ├── vault_paths.py
│   ├── vault_git_service.py
│   └── update_mode_file_service.py
└── tests/
    ├── test_vault_paths.py
    ├── test_vault_git_service.py
    └── test_update_mode_file_service.py
```

Если проект использует другую структуру package/imports, сохранить его текущие conventions, но не смешивать новый код с parser/scanner logic.

---

## `services/vault_paths.py`

### Назначение

Этот модуль является единственной точкой path validation для Campaign Update Mode.

Никакой другой новый module не должен самостоятельно делать:

```python
Path("/data/vaults") / vault_id / relative_path
```

### Constants

```python
from pathlib import Path

VAULT_ROOT = Path("/data/vaults")
MAX_RELATIVE_PATH_LENGTH = 512
```

Не читать root из user input или LLM response.

### `resolve_vault_root`

```python
def resolve_vault_root(vault_id: str) -> Path:
    ...
```

Правила:

1. `vault_id` уже должен быть подтверждён на уровне backend/DB;
2. helper всё равно защищается от slash, backslash, `.` и `..`;
3. root вычисляется как `VAULT_ROOT / vault_id`;
4. root нормализуется через `resolve(strict=False)`;
5. результат обязан быть прямым child of `VAULT_ROOT.resolve()`;
6. helper не создаёт root автоматически;
7. если root отсутствует, caller получает typed `VaultRootMissingError`;
8. если root существует, но не directory, caller получает typed `InvalidVaultRootError`.

Рекомендуемый паттерн:

```python
root_base = VAULT_ROOT.resolve()
candidate = (root_base / vault_id).resolve(strict=False)

if candidate.parent != root_base:
    raise InvalidVaultPathError("vault id resolves outside VAULT_ROOT")

if not candidate.exists():
    raise VaultRootMissingError(vault_id)

if not candidate.is_dir():
    raise InvalidVaultRootError(vault_id)

return candidate
```

Не использовать string prefix comparison вида:

```python
str(candidate).startswith(str(root_base))
```

Она небезопасна для sibling paths вроде `/data/vaults-a`.

`Path.resolve()` должен выполняться до проверки containment, потому что иначе `..` segments могут дать ложноположительный результат. `pathlib` предоставляет `resolve()` и `is_relative_to()`/`relative_to()` для работы с canonical paths. [web:142][web:143]

### `resolve_existing_markdown`

```python
def resolve_existing_markdown(
    vault_root: Path,
    relative_path: str,
) -> tuple[Path, str]:
    ...
```

Возвращает:

```python
(absolute_path, canonical_relative_posix_path)
```

Правила:

- `relative_path` не пустой;
- длина не больше `MAX_RELATIVE_PATH_LENGTH`;
- path не абсолютный;
- запрещены NUL, `..`, Windows drive syntax и backslash;
- исходный path обязан завершаться на `.md` без учёта case;
- итоговый `candidate.resolve(strict=True)` обязан находиться внутри `vault_root.resolve()`;
- candidate обязан существовать, быть regular file и не быть symlink, ведущим за пределы vault;
- `.git` segment и `.gitignore` запрещены;
- canonical relative path передаётся в git только в POSIX form;
- скрытые `.md` файлы допустимы только если они не находятся в `.git` и не являются `.gitignore`.

Если file не существует, вернуть typed `FileNotFoundError` домена update mode, не builtin exception напрямую.

### `validate_suggested_filename`

```python
def validate_suggested_filename(filename: str) -> str:
    ...
```

Правила:

- basename only: `Path(filename).name == filename`;
- нет `/`, `\`, NUL, `..`;
- не пустое;
- длина до 255 characters;
- заканчивается на lowercase `.md`;
- не равно `.gitignore`;
- не начинается с `.git`;
- не содержит control characters;
- не выполняет slugification молча.

Если LLM выдала невалидное имя, change получает `invalid_filename`. Нельзя заменять имя «по догадке».

### `resolve_create_target`

```python
def resolve_create_target(
    vault_root: Path,
    parent_relative_path: str | None,
    filename: str,
) -> tuple[Path, str]:
    ...
```

Правила:

1. Вызвать `validate_suggested_filename(filename)`;
2. Если есть parent:
   - parent сначала проходит `resolve_existing_markdown`;
   - target directory = `parent.absolute_path.parent`;
   - target directory уже должна существовать;
   - не создавать дополнительные промежуточные directories;
3. Если parent нет:
   - directory = `vault_root / "_campaign_notes"`;
   - только эта controlled directory может быть создана `mkdir(parents=False, exist_ok=True)`;
4. Target path нормализуется;
5. Target обязан находиться внутри vault root;
6. Target обязан иметь `.md`;
7. Если target существует, вернуть `TargetExistsError`;
8. Возвращать `(absolute_path, canonical_relative_posix_path)`.

`_campaign_notes` не может быть задан LLM в качестве произвольного directory name.

---

## `services/update_mode_file_service.py`

### Назначение

Сервис владеет операциями над оригинальным markdown content.

Он не знает:

- Redis;
- chat;
- campaign;
- tags;
- retrieval;
- LLM provider;
- PostgreSQL ORM.

На вход получает уже валидированный `vault_id`, canonical relative path и structured operation.

### Constants

```python
MAX_CREATED_FILE_BYTES = 64 * 1024
MAX_CHANGE_CONTENT_BYTES = 64 * 1024
```

Bytes проверяются как:

```python
len(content.encode("utf-8"))
```

Не измерять Python character count вместо bytes.

### Data structures

Создать Pydantic models или dataclasses, совместимые с project style:

```python
class FileSnapshot(BaseModel):
    vault_id: str
    file_path: str
    content: str
    sha256: str
    size_bytes: int

class ResolvedFileChange(BaseModel):
    change_id: str
    vault_id: str
    document_id: str | None
    file_path: str
    action: Literal["update", "create"]
    description: str
    original_content: str
    proposed_content: str
    unified_diff: str
    expected_sha256: str | None
    error_code: str | None = None
    error_message: str | None = None
```

В финальной фазе shared API DTO переносятся в `shared_contracts/models.py`. Внутренний сервис не должен импортировать ORM-модели backend.

### UTF-8 reading

Оригинальные `.md` читаются строго как UTF-8:

```python
path.read_text(encoding="utf-8")
```

Если decode невозможен, вернуть:

```text
invalid_utf8
```

Не использовать `errors="ignore"` или `errors="replace"`: это может создать diff, который повреждает файл.

### SHA-256

Checksum рассчитывается по точным raw bytes файла:

```python
hashlib.sha256(path.read_bytes()).hexdigest()
```

Не рассчитывать checksum от decoded/re-encoded string.

`FileSnapshot.content` используется для diff, а `FileSnapshot.sha256` — concurrency precondition.

### Поддерживаемые operations

#### `append_to_file`

```text
original + normalized separator + content
```

Правила newline:

- Если original непустой и не заканчивается на `\n`, добавить один `\n`;
- Между existing content и inserted section оставить один пустой line;
- Не менять остальные newline sequences;
- Empty content возвращает `content_limit_exceeded` или `empty_content`, не создаёт no-op diff.

#### `append_after_section`

Input содержит exact heading string:

```json
{
  "kind": "markdown_heading",
  "value": "## Последняя сессия"
}
```

Алгоритм:

1. Найти lines, точно равные heading после `rstrip()`;
2. Если 0 matches → `anchor_not_found`;
3. Если больше 1 → `anchor_ambiguous`;
4. Section заканчивается перед следующим markdown heading с уровнем `<=` уровня anchor, либо в EOF;
5. Вставить new content в конец section;
6. Сохранить остальной original file без перестроения.

Не выбирать «похожий» heading, не делать case-insensitive fallback и не использовать fuzzy matching в MVP.

#### `replace_unique_text`

Input содержит exact original text:

```json
{
  "kind": "exact_text",
  "value": "Старый утверждённый факт."
}
```

Алгоритм:

1. `original.count(anchor.value)` должен равняться 1;
2. `0` → `anchor_not_found`;
3. `> 1` → `anchor_ambiguous`;
4. Заменить только найденный exact fragment.

`replace_unique_text` не использует regex; content/anchor не интерпретируются как regex.

#### `create_file`

- `original_content = ""`;
- `proposed_content = content`;
- Content должен быть непустым и не больше `MAX_CREATED_FILE_BYTES`;
- Target path проходит `resolve_create_target`;
- File реально не создаётся на resolve.

### Diff

Использовать `difflib.unified_diff` с:

```text
fromfile=a/{canonical_relative_path}
tofile=b/{canonical_relative_path}
lineterm=""
```

`unified_diff` возвращается как UTF-8 text и хранится в Redis session.

Для create diff выглядит как file creation:

```text
--- /dev/null
+++ b/_campaign_notes/session-2026-07-15.md
```

Не использовать git diff, так как resolve не должен менять git working tree.

### Atomic write

Создать method:

```python
def atomic_write(
    absolute_path: Path,
    content: str,
    expected_sha256: str | None,
    is_create: bool,
) -> str:
    ...
```

Алгоритм:

1. Для update:
   - убедиться, что target file существует;
   - вычислить current SHA-256 raw bytes;
   - сравнить с `expected_sha256`;
   - при отличии вернуть `FileModifiedError`;
2. Для create:
   - повторно убедиться, что target не существует;
   - при существовании вернуть `TargetExistsError`;
3. Убедиться, что parent directory существует и находится внутри vault;
4. Записать content в temporary file в той же directory;
5. Использовать `flush()` и `os.fsync()`;
6. Выполнить `os.replace(temp_path, absolute_path)`;
7. При возможности сохранить file mode существующего update-file;
8. После `os.replace` вернуть SHA-256 записанного raw content.

Не использовать direct `path.write_text()` для apply.

Если процесс аварийно завершится до `os.replace`, оригинальный файл остаётся целым. `os.replace` делает замену atomic в пределах одной filesystem.

---

## `services/vault_git_service.py`

### Назначение

Сервис инкапсулирует исключительно git subprocess operations на одном vault root.

Он не получает:

- абсолютный путь от LLM;
- `chat_id`;
- raw request;
- произвольную shell command.

### Subprocess policy

Все команды:

```python
await asyncio.create_subprocess_exec(
    "git",
    *args,
    cwd=str(vault_root),
    env=git_env,
    stdout=PIPE,
    stderr=PIPE,
)
```

Запрещено:

```python
create_subprocess_shell(...)
shell=True
f"git {user_input}"
```

Нужны typed exceptions:

```text
GitUnavailableError
GitCommandError
GitIdentityError
GitIgnoredTargetError
```

Не отдавать subprocess stderr напрямую в UI response.

### `ensure_repository`

```python
async def ensure_repository(vault_root: Path) -> GitCapability:
    ...
```

Проверить:

1. `git --version`;
2. root exists and directory;
3. если `.git` отсутствует — `git init`;
4. после init проверить `git rev-parse --is-inside-work-tree`.

Возвращать structured capability:

```python
class GitCapability(BaseModel):
    available: bool
    repository_ready: bool
    error_code: str | None = None
```

`git init` не должен автоматически commit existing vault content.

### Relative path requirement

Любой git target path должен быть canonical relative POSIX path, уже полученный из `vault_paths.py`.

Перед каждой git command повторно проверить:

```python
not path.startswith("/")
".git" not in PurePosixPath(path).parts
path.endswith(".md")
```

### `status_for_paths`

```python
async def status_for_paths(
    vault_root: Path,
    relative_paths: list[str],
) -> dict[str, GitPathStatus]:
    ...
```

Использовать machine-readable porcelain output и explicit pathspec separator:

```bash
git status --porcelain=v1 -- <paths...>
```

Не вызывать `git status` без path list для принятия snapshot decision.

### Ignored target check

Перед snapshot и apply проверить каждый path:

```bash
git check-ignore -q -- <path>
```

Если command говорит, что файл ignored:

```text
git_ignored_target
```

Не применять `-f`.

### Git identity

Получать identity только как аргументы конструктора:

```python
GitIdentity(name: str, email: str)
```

Источники:

1. DB vault override fields;
2. deployment fallback env `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`;
3. если ни одного варианта нет — `git_identity_missing`.

Перед commit установить локально только для subprocess env:

```python
GIT_AUTHOR_NAME
GIT_AUTHOR_EMAIL
GIT_COMMITTER_NAME
GIT_COMMITTER_EMAIL
```

Не делать:

```bash
git config --global user.name ...
git config user.name ...
```

### Snapshot

```python
async def snapshot_paths(
    vault_root: Path,
    relative_paths: list[str],
    identity: GitIdentity,
) -> str | None:
    ...
```

Алгоритм:

1. Проверить git capability;
2. Проверить explicit paths;
3. Проверить ignored paths;
4. Получить `status_for_paths`;
5. Если target paths clean → `None`;
6. `git add -- <target paths>`;
7. Повторно проверить staged diff ограниченно target path list;
8. `git commit -m "snapshot: manual edits before campaign update" -- <target paths>`;
9. Вернуть commit SHA.

Важно: snapshot включает только выбранные target `.md`. Любые untracked/modified files вне target paths остаются нетронутыми.

### Apply commit

```python
async def commit_paths(
    vault_root: Path,
    relative_paths: list[str],
    message: str,
    identity: GitIdentity,
) -> str:
    ...
```

Алгоритм:

1. Валидация paths и identity;
2. Проверка ignored paths;
3. `git add -- <target paths>`;
4. Проверка, что staged diff существует для этих paths;
5. Если diff отсутствует, вернуть `NoChangesToCommitError`;
6. `git commit -m <safe message> -- <target paths>`;
7. `git rev-parse HEAD`;
8. Вернуть SHA.

`message`:

- fallback: `campaign-update: apply reviewed changes`;
- если LLM message допускается, ограничить до 72 Unicode characters;
- strip control characters/newlines;
- пустой результат заменять fallback;
- commit message не может менять command structure, так как передаётся отдельным argument.

---

## Git initialization integration

На старте indexer не должен сканировать и инициализировать все vault без проверки DB.

В дальнейшей фазе backend или indexer lifecycle может вызвать best-effort initialization только для enabled vault, полученных из DB.

Failure policy:

| Состояние | Поведение |
|---|---|
| Vault root missing | update mode resolve/apply возвращает typed error; indexer остаётся healthy |
| Git unavailable | соответствующий vault недоступен для update mode; indexer остаётся healthy |
| `git init` failed | логировать structured error; не crash process |
| Existing non-git vault | `git init`, без automatic initial commit |
| Existing git vault | no-op |

---

## Тесты

### `test_vault_paths.py`

Минимальные сценарии:

- valid vault root;
- root missing;
- root points to a file;
- `vault_id="../other"` rejected;
- existing normal `.md`;
- absolute path rejected;
- `../` rejected;
- backslash path rejected;
- `.git/config` rejected;
- `.gitignore` rejected;
- non-`.md` rejected;
- symlink to outside vault rejected;
- safe nested markdown accepted;
- valid filename accepted;
- filename with slash, `..`, NUL, control character rejected;
- create next to parent;
- fallback creates only `_campaign_notes`;
- existing target returns `target_exists`.

### `test_update_mode_file_service.py`

Минимальные сценарии:

- SHA-256 calculated from raw bytes;
- UTF-8 invalid file rejected;
- append keeps existing content and correct separator;
- append-after-section uses exact unique heading;
- missing heading returns `anchor_not_found`;
- duplicate heading returns `anchor_ambiguous`;
- replace exact unique text;
- duplicate text returns `anchor_ambiguous`;
- create produces `/dev/null` unified diff;
- max content size rejected;
- atomic update replaces file;
- atomic update rejects changed checksum;
- create rejects file created after resolve;
- temporary file cleanup after write failure.

### `test_vault_git_service.py`

Минимальные сценарии в temporary git repo:

- git unavailable returns typed error (mock subprocess);
- first `ensure_repository` initializes repo;
- repeated `ensure_repository` is no-op;
- init does not create initial commit;
- snapshot clean target returns `None`;
- snapshot commits only changed target markdown;
- unrelated dirty file is not staged/committed;
- ignored markdown returns `git_ignored_target`;
- apply commit contains only supplied explicit paths;
- fallback identity works;
- missing identity is rejected;
- commit message normalizes control characters;
- no shell command API is used.

---

## Acceptance criteria фазы

- [ ] Единственный indexer path layer используется всеми update-mode filesystem operations.
- [ ] Path traversal, symlink escape, `.git` и non-Markdown access блокируются тестами.
- [ ] Original file может быть прочитан с raw SHA-256 и корректным UTF-8 validation.
- [ ] Resolved diff строится без изменения working tree.
- [ ] Atomic write не перезаписывает изменённый после review файл.
- [ ] Git repo инициализируется только в существующем vault root.
- [ ] Snapshot и apply коммиты работают исключительно с explicit `.md` file list.
- [ ] Unrelated dirty files не попадают в snapshot/apply commit.
- [ ] Git identity не изменяет global/local git config.
- [ ] Все новые unit tests проходят.