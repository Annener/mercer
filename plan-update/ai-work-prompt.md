# Рабочий промпт для реализации Campaign Update Mode

## Роль

Ты senior full-stack engineer для Mercer. Реализуй Campaign Update Mode строго по документам в текущей папке `plan-update/`.

Приоритет требований:

1. Явные инструкции пользователя;
2. `plan-update/concept.md`;
3. Текущий файл `plan-update/status.md`;
4. Файлы фаз, уже существующие в `plan-update/`;
5. Этот рабочий промпт;
6. Существующие conventions репозитория.

Не выдумывай альтернативную архитектуру, не подменяй принятые решения и не меняй scope без явного согласования.

---

## Критическое правило имён файлов

Пользователь **не менял названия существующих файлов планов**.

Перед любыми изменениями:

```bash
find plan-update -maxdepth 1 -type f -name '*.md' -print | sort
```

Затем:

1. Прочитай каждый существующий Markdown-файл в `plan-update/`;
2. Сопоставь существующие файлы с фазами из `concept.md` по содержанию, а не по предполагаемому имени;
3. Переписывай существующие файлы на месте;
4. Не переименовывай существующие файлы;
5. Не удаляй существующие плановые файлы;
6. Не создавай duplicate файлы с альтернативными именами фаз без явного запроса пользователя.

Если в плане существует, например:

```text
phase-1-*.md
phase-2-*.md
phase-3-*.md
phase-4-*.md
phase-5-*.md
```

то новая подготовительная фаза 0 должна быть добавлена:

- в существующий `concept.md`;
- в существующий `status.md`;
- в начало первого существующего phase-file либо как отдельный новый `phase-0-*.md` **только если пользователь явно подтвердил создание нового файла**.

Не предполагай, что имена `phase-0-invariants-and-recovery.md`, `phase-1-git-foundation.md` и т.п. уже существуют.

Перед созданием любого нового `.md` файла сообщи пользователю:

```text
Нужен новый файл <path>, потому что <reason>. Подтверждаете создание?
```

и дождись явного подтверждения.

---

## Режим работы

Работай строго итерациями:

```text
Inspect → Plan → Implement → Verify → Report
```

Для сложной multi-service задачи недопустимо писать большой объём кода без inspection и тестов. Сначала исследуй ближайшие реальные implementation paths и tests, затем делай минимальное изменение, затем механически проверяй результат. [web:199][web:205]

### Inspect

Перед каждой фазой:

1. Прочитай `plan-update/concept.md` и `plan-update/status.md`;
2. Прочитай соответствующий существующий phase file;
3. Найди реальную структуру репозитория:
   ```bash
   find rag-backend rag-indexer shared_contracts -maxdepth 3 -type f | sort
   ```
4. Найди ближайшие существующие аналоги через `rg`;
5. Проверь текущие tests рядом с изменяемыми модулями;
6. Подтверди фактические imports, router registration, migration path и test commands;
7. Сформулируй короткий implementation plan до первого edit.

Не доверяй устаревшим комментариям плана больше, чем реальному коду. Если код и план противоречат друг другу в архитектурно важном месте, остановись и сообщи конкретное расхождение.

### Implement

- Делай только изменения текущей фазы;
- Следуй существующему code style;
- Предпочитай небольшие responsibility-focused modules;
- Не делай unrelated refactor;
- Не заменяй существующую working functionality ради «чистоты»;
- Сначала добавь или обнови regression tests;
- Затем добавь production code, достаточный для их прохождения;
- Не скрывай ошибки fallback поведением;
- Не добавляй новые dependencies без необходимости и явного обоснования.

### Verify

После каждого логического блока:

```bash
git diff --check
```

Затем выполнить точные tests, относящиеся к изменениям, и в конце фазы — полные suite:

```bash
cd rag-backend && pytest -q
cd rag-indexer && pytest -q
```

Если команда падает по unrelated причине:

1. Не исправляй unrelated code;
2. Зафиксируй точную команду;
3. Сохрани краткий релевантный output;
4. Объясни вероятную причину;
5. Отметь фазу как blocked в `plan-update/status.md`;
6. Остановись и запроси решение.

---

## Архитектурные инварианты

Нарушение любого пункта — ошибка реализации.

### DB-only vault settings

- PostgreSQL — единственный source of truth vault configuration;
- `VaultConfigService` — только кэш DB-строк;
- Не добавлять vault settings в YAML, `AppConfig`, `.env`, Python constants;
- Не добавлять `Vault.path`;
- Не добавлять `Vault.versioned_extensions`;
- Не использовать `AppConfig.vaults`;
- Не добавлять persisted `Chat.update_mode_enabled` или аналогичный stale boolean.

Допустимые новые DB поля только для этой feature:

```text
vaults.git_author_name
vaults.git_author_email
```

Они nullable и используются как per-vault override git identity.

### Ownership файлов

- Original vault files принадлежат `rag-indexer`;
- Только indexer читает original `.md`, строит diff, вычисляет file checksum, пишет файл и вызывает git;
- `rag-backend` не читает и не пишет `/data/vaults` для Campaign Update Mode;
- Backend обращается к indexer через internal HTTP API;
- Canonical filesystem root:
  ```text
  /data/vaults/{vault_id}
  ```

### Two representations

- Indexed chunks — для retrieval и LLM context;
- Original markdown — для preview, diff, checksum, apply;
- Никогда не записывай reconstructed indexed text как целый original file;
- `reconstruct_full_text()` допустим только для reconstruction LLM context.

### Scope

- Только `.md`;
- Только documents с `status == indexed`;
- Только documents с campaign tags;
- Все enabled vault текущего chat domain;
- Не делать search по всему vault/domain, если у campaign нет tags;
- Без tags возвращать `422 campaign_tags_required`;
- Максимум 15 documents;
- Максимум 64k estimated tokens total;
- Максимум 16k estimated tokens на документ;
- Максимум 10 changes;
- Review TTL 3 hours.

### Разрешённые операции

```text
update
append
create .md
```

Запрещены:

```text
delete
rename
move
arbitrary directory creation
non-markdown writes
.gitignore editing
.git/* editing
```

### Create policy

- Если есть `parent_document_id`, новый файл создаётся рядом с parent в том же vault;
- Если parent отсутствует:
  1. Использовать `chat.vault_id`, если он enabled и принадлежит domain;
  2. Иначе vault наиболее релевантного document;
  3. Иначе первый enabled domain vault по `vault_id ASC`;
- Fallback directory:
  ```text
  _campaign_notes/
  ```
- Только `_campaign_notes` может быть автоматически создана;
- File collision не перезаписывается: `409 target_exists`.

### Security

Все данные от LLM, браузера и Redis считаются недоверенными.

Indexer обязан:

- Нормализовать paths через `Path.resolve()`;
- Проверять, что path остаётся внутри конкретного vault root;
- Запрещать absolute paths, `..`, NUL, slash/backslash в filename;
- Запрещать `.git` path segments;
- Проверять только `.md`;
- Не использовать shell strings или `shell=True`;
- Не использовать prefix string checks для containment;
- Повторно валидировать file paths на apply.

Нельзя применять fuzzy file matching или «догадку» при отсутствии/неоднозначности anchor.

### Git

- Один local repository на vault root;
- `git init` только на существующем directory;
- Нет automatic initial commit;
- Snapshot только target `.md` files;
- Apply commit только explicit target `.md` paths;
- Запрещено:
  ```text
  git add .
  git add -A
  git add -f
  ```
- Git commands выполняются argument list через subprocess exec;
- Git author identity:
  1. `Vault.git_author_name/email`;
  2. deployment fallback `GIT_AUTHOR_NAME/EMAIL`;
  3. иначе typed `git_identity_missing`;
- Не менять global/local git config;
- Git commit failure после write не должен запускать automatic rollback поверх возможных ручных правок.

### Concurrency

- Redis key:
  ```text
  update_mode:{chat_id}
  ```
- Один active review session на chat;
- Vault lock только на resolve/apply;
- Lock TTL 60 seconds;
- Apply имеет stable `apply_id`;
- Same `apply_id` + same payload возвращает сохранённый result;
- Same `apply_id` + другой payload → `409`;
- Checksum mismatch → `409 file_modified`;
- Apply preflight всех changes vault group до первого write;
- Multi-vault apply допускает partial success, не является distributed transaction.

### Reindex

После успешного apply git commit:

- Indexer запускает targeted reindex только changed/created `.md`;
- Backend/UI получают `reindex_task_id`;
- Apply не ждёт completion;
- Git success и reindex success должны быть отображены отдельно;
- Если reindex start failed после commit, commit не откатывается;
- Existing full-vault indexing behavior не должен сломаться.

---

## Обязательные contracts

### Provider

Использовать текущий lifecycle:

```python
provider = settings_service.get_active_provider()
```

При отсутствии provider:

```text
503 generation_provider_unavailable
```

Не создавай новый provider из `AppConfig` или raw environment keys.

### DB session

Использовать существующий:

```python
db: AsyncSession = Depends(get_db)
```

Не создавать новый engine/sessionmaker для update mode.

### Shared models

Cross-service DTO добавлять только в:

```text
shared_contracts/models.py
```

Не дублировать Pydantic models в backend/indexer routers.

Для Redis:

```python
model.model_dump(mode="json")
Model.model_validate(payload)
```

### Public backend routes

```text
POST   /api/chats/{chat_id}/update-mode/start
GET    /api/chats/{chat_id}/update-mode/session
PATCH  /api/chats/{chat_id}/update-mode/review
POST   /api/chats/{chat_id}/update-mode/apply
DELETE /api/chats/{chat_id}/update-mode/session
```

### Internal indexer routes

```text
POST /internal/update-mode/resolve
POST /internal/update-mode/apply
```

Internal endpoint не публикуется через external Docker port.

---

## Phase execution order

### Phase 0 — Baseline и contracts

1. Найди актуальные плановые файлы без переименования;
2. Подтверди migration path:
   ```text
   rag-backend/migrations/versions/
   ```
3. Выполни baseline tests;
4. Проверь Docker mounts и git availability;
5. Зафиксируй любой blocker в existing `status.md`;
6. Не пиши feature code до clean/understood baseline.

### Phase 1 — Indexer filesystem/git foundation

Реализуй:

- canonical path validation;
- original UTF-8 read;
- raw-byte SHA-256;
- exact anchor resolution;
- unified diff;
- atomic write;
- git capability/init;
- explicit-path snapshot and apply commit;
- strict tests path traversal, symlink escape, `.git`, ignored paths и unrelated dirty files.

Не добавляй LLM, Redis или public update endpoints в этой фазе.

### Phase 2 — DB, contracts, Redis

Реализуй:

- Alembic migration двух nullable git identity fields;
- ORM/cache update;
- shared Pydantic DTO;
- Redis review session TTL 3 hours;
- atomic review/apply state updates;
- backend indexer client;
- router skeleton.

Не реализуй LLM retrieval или file apply до прохождения contract/store tests.

### Phase 3 — Retrieval, generation, resolve

Реализуй:

- chat/campaign/domain/tag validation;
- fresh DB query all enabled vaults domain;
- document scope: tag + indexed + `.md` + enabled vault;
- semantic retrieval;
- full indexed reconstruction;
- 15/64k/16k limits;
- strict prompt and LLM structured output validation;
- indexer resolve call;
- Redis session creation.

Не выполняй file write, git commit или reindex.

### Phase 4 — Review, apply, reindex

Реализуй:

- session GET/PATCH/DELETE;
- idempotent apply begin;
- indexer apply endpoint;
- per-vault lock/preflight/snapshot/write/commit;
- targeted reindex;
- per-vault partial result;
- audit log metadata only.

### Phase 5 — UI, E2E, operations

Реализуй:

- campaign chat update panel;
- note input;
- review cards/diff;
- accepted/rejected persistence;
- expiry/retry states;
- per-vault apply/reindex result;
- E2E, Docker and recovery checks;
- documentation/status completion.

---

## Обязательные тесты

Минимально должны быть покрыты:

### Path and filesystem

- traversal;
- absolute path;
- `.git`;
- symlink outside vault;
- invalid filename;
- non-`.md`;
- missing root;
- missing file;
- duplicate/ambiguous anchor;
- stale checksum;
- create collision;
- atomic write failure.

### Git

- init idempotency;
- no initial commit;
- explicit paths only;
- unrelated dirty files excluded;
- ignored target rejected;
- identity fallback;
- missing identity;
- snapshot/apply commit behavior;
- no shell execution.

### Backend flow

- campaign missing;
- campaign tags missing;
- no enabled vault;
- only tagged indexed markdown scope;
- multi-vault scope;
- document/context limits;
- invalid LLM output;
- unknown document ID;
- indexer unavailable;
- session TTL;
- accept/reject conflict;
- apply idempotency;
- audit redaction.

### E2E

- update existing markdown;
- create beside parent;
- fallback `_campaign_notes`;
- multi-vault partial conflict;
- expired session;
- same apply ID retry creates one commit;
- commit success with reindex failure.

---

## Logging и redaction

Structured logs могут содержать:

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

Запрещено писать в logs и AuditLog:

```text
original_content
proposed_content
unified_diff
full indexed context
raw LLM output
user note
API keys
git stderr
```

---

## Что делать при неопределённости

Остановись и задай один конкретный вопрос, если:

- требуется создать новый плановый файл, а пользователь не подтвердил это;
- существующее file naming/structure не соответствует плану;
- нет реального service/module, на который ссылается phase;
- existing test failures не связаны с текущим изменением;
- migration head отличается от ожидаемого;
- current code делает filesystem writes в backend и исправление требует architecture change вне плана;
- нужно принять продуктовое решение, не указанное в `concept.md`.

Не заменяй вопрос скрытым предположением.

---

## Финальный отчёт после каждой фазы

После завершения фазы сообщи:

```text
Фаза:
Изменённые существующие файлы:
Новые файлы:
Миграции:
API changes:
Тесты и результаты:
Docker/runtime checks:
Оставшиеся риски:
Следующая фаза:
```

Если фаза blocked:

```text
Статус: BLOCKED
Точная команда:
Релевантный output:
Причина:
Минимальный вопрос для разблокировки:
```

Не объявляй фазу завершённой без выполнения её acceptance criteria.