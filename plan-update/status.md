# Campaign Update Mode — Статус реализации

## Назначение

Этот документ — единственный operational status для Campaign Update Mode.

Он отвечает на вопросы:

- какая фаза выполняется;
- какие инварианты нельзя нарушать;
- какие команды подтверждают готовность;
- какие риски остаются;
- что должна сделать следующая модель или разработчик.

Не использовать этот файл как changelog пользовательских релизов. Статус implementation и пользовательский changelog решают разные задачи. [web:189][web:195]

---

## Текущий статус

```text
Состояние: План переписан, реализация не начата
Текущая фаза: 0 — Инварианты, контракты и baseline
Последнее решение: 2026-07-15
```

### Блокирующие условия перед началом кода

- [ ] Зафиксирован clean baseline после `git reset --hard`.
- [ ] Подтверждён фактический Alembic head.
- [ ] Выполнены backend и indexer test suites.
- [ ] Подтверждён Docker shared mount для backend и indexer.
- [ ] Подтверждён active generation provider.
- [ ] Подтверждён минимум один enabled vault с существующим `.md`.
- [ ] Подтверждено, что git доступен в indexer image.

Не начинать фазы 1–5, пока baseline содержит неизвестные regression failures.

---

## Архитектурные решения

| Область | Зафиксированное решение |
|---|---|
| Vault configuration | Только PostgreSQL; YAML/AppConfig/env не являются vault configuration |
| Vault path | Не хранится в БД; physical root — `/data/vaults/{vault_id}` |
| Filesystem owner | Только `rag-indexer` |
| Backend role | DB validation, retrieval, LLM orchestration, Redis session, public API |
| Context для LLM | Full indexed text документов, собранный из chunks |
| Source для diff/apply | Оригинальный `.md` файл, читаемый indexer |
| Поддерживаемые файлы | Только `.md` |
| Scope поиска | Campaign tags + all enabled vaults chat domain |
| Число документов | До 15 |
| Total LLM context | До 64k estimated tokens |
| Один документ в LLM | До 16k estimated tokens |
| Changes | До 10 |
| Review state | Redis, TTL 3 часа |
| Update operations | `update`, `append`, `create` |
| Запрещённые операции | delete, rename, move, arbitrary directory creation |
| Create рядом с document | В directory parent document |
| Create без parent | `<vault-root>/_campaign_notes/` |
| Git scope | Один local git repo на vault |
| Snapshot | Только changed target `.md` files |
| Git staging | Только explicit canonical path list |
| Apply concurrency | SHA-256 original file + vault lock |
| Multi-vault | Per-vault apply result; partial success допустим |
| Reindex | Targeted reindex после успешного apply commit |
| Authorization | Single-user local MVP |
| Audit | Metadata only; без note/content/diff/raw LLM output |

---

## Фазовый план

| Фаза | Файл | Цель | Статус |
|---:|---|---|---|
| 0 | `phase-0-invariants-and-recovery.md` | Baseline, boundaries, migration path, contracts | Not started |
| 1 | `phase-1-git-foundation.md` | Indexer path/file/git foundation | Not started |
| 2 | `phase-2-data-model-and-contracts.md` | DB fields, DTO, Redis session, router skeleton | Not started |
| 3 | `phase-3-context-and-intent-generation.md` | Campaign scope, retrieval, LLM intents, resolve | Not started |
| 4 | `phase-4-review-apply-and-reindex.md` | Review, apply, git commits, targeted reindex | Not started |
| 5 | `phase-5-ui-e2e-and-operational-readiness.md` | UI, E2E, deployment, observability | Not started |

Фазы выполняются строго по порядку. Не начинать реализацию последующей фазы при незакрытых acceptance criteria предыдущей.

---

## Проверенные факты репозитория

### Database и migrations

- Миграции находятся в `rag-backend/migrations/versions/`.
- Текущие приложенные migrations:
  ```text
  0001_initial
  0002_watchdog_interval
  0003_fulldoc_fields
  0004_fix_sent_full_document_ids_jsonb
  ```
- Новая migration не должна жёстко предполагать `0004` без проверки актуального `alembic heads`.
- `vaults` уже содержит DB-only operational settings, domain binding, embedding binding и indexing status.

### Backend

- Session dependency — `get_db()` в `rag-backend/app/db/session.py`.
- Active generation provider берётся через:
  ```python
  settings_service.get_active_provider()
  ```
- Chat flow уже может собирать enabled vaults domain.
- `VaultConfigService` — lazy process-local cache DB vault rows; не source of truth для update writes.
- `full_document_service.reconstruct_full_text()` уже может собрать полный indexed text документа через db-api-server chunks endpoint.

### Indexer

- Indexer строит vault path как:
  ```python
  /data/vaults/{vault_id}
  ```
- Parser поддерживает `.md` и `.pdf`, но Campaign Update Mode работает только с `.md`.
- Reindex текущего changed document удаляет старые chunks до upsert новых.
- Indexer обновляет document metadata, включая checksum, mtime, charcount, chunkcount и estimated tokens.

### Docker

- `rag-backend` и `rag-indexer` монтируют `${VAULTS_PATH}` в `/data/vaults:rw`.
- `rag-indexer` уже работает в Docker network и доступен backend по service URL.
- Новый internal indexer update-mode API не должен публиковаться наружу отдельным `ports` mapping.

---

## Обязательные runtime команды

### До каждой фазы

```bash
git status --short
docker compose config
docker compose ps
```

Если worktree не clean, записать текущие intentional changes перед продолжением. Не смешивать Campaign Update Mode с unrelated edit.

### Database migration

```bash
cd rag-backend
alembic heads
alembic current
alembic upgrade head
```

После migration:

```bash
alembic current
```

Должен показывать ожидаемый head.

### Backend tests

```bash
cd rag-backend
pytest -q
```

### Indexer tests

```bash
cd rag-indexer
pytest -q
```

### Docker smoke test

```bash
docker compose --profile core up -d --build
docker compose ps
docker compose logs --tail=200 rag-backend
docker compose logs --tail=200 rag-indexer
```

### Git capability внутри indexer

```bash
docker compose exec rag-indexer sh -lc 'git --version'
docker compose exec rag-indexer sh -lc 'test -d /data/vaults'
docker compose exec rag-indexer sh -lc 'test -w /data/vaults'
```

Никогда не вставлять private vault filename или file content в публичные logs/issue comments.

---

## API matrix

### Public backend API

| Endpoint | Назначение | Состояние |
|---|---|---|
| `POST /api/chats/{chat_id}/update-mode/start` | Note → retrieval → LLM intents → resolved diffs | Planned |
| `GET /api/chats/{chat_id}/update-mode/session` | Получить Redis review state | Planned |
| `PATCH /api/chats/{chat_id}/update-mode/review` | Accept/reject changes | Planned |
| `POST /api/chats/{chat_id}/update-mode/apply` | Применить accepted changes | Planned |
| `DELETE /api/chats/{chat_id}/update-mode/session` | Cancel session | Planned |

### Internal indexer API

| Endpoint | Назначение | Состояние |
|---|---|---|
| `POST /internal/update-mode/resolve` | Intent → original-file diff | Planned |
| `POST /internal/update-mode/apply` | Checksum → snapshot → write → commit → reindex | Planned |

---

## Error matrix

| Code | HTTP | Meaning | Client behavior |
|---|---:|---|---|
| `campaign_required` | 422 | Chat не связан с campaign | Выбрать/создать campaign chat |
| `campaign_tags_required` | 422 | Нет campaign tags | Добавить tags |
| `no_enabled_vaults` | 422 | В domain нет enabled vault | Проверить vault settings |
| `campaign_has_no_indexed_markdown` | 422 | Нет tagged indexed `.md` | Запустить/дождаться indexing |
| `no_relevant_campaign_context` | 422 | Retrieval не нашёл релевантный context | Уточнить note |
| `no_usable_indexed_context` | 422 | Context reconstruction/limits не дали usable docs | Проверить документы/indexer |
| `generation_provider_unavailable` | 503 | Нет active LLM provider | Настроить model |
| `indexer_unavailable` | 503 | Indexer недоступен | Retry позже |
| `session_already_active` | 409 | Review session уже существует | Открыть session |
| `session_expired` | 410 | Redis TTL истёк | Start заново |
| `file_modified` | 409 | Original file изменился после review | Start заново |
| `target_exists` | 409 | Create target уже существует | Start заново |
| `vault_root_missing` | 409 | Нет vault directory | Исправить deployment/storage |
| `vault_lock_timeout` | 409 | Vault занят другой apply/resolve | Retry позже |
| `git_unavailable` | 503 | Git отсутствует/недоступен | Исправить indexer image |
| `git_identity_missing` | 503 | Нет DB или fallback git identity | Настроить vault/env |
| `git_ignored_target` | 409 | Git игнорирует target `.md` | Исправить вручную |
| `apply_already_started` | 409 | Другой apply ID уже выполняется | Retry тем же ID |
| `apply_id_payload_mismatch` | 409 | Same apply ID, другой payload | Не retry с изменённым payload |
| `apply_in_progress` | 409 | Apply с тем же ID ещё выполняется | Poll/retry позже |

`410 Gone` для expired review session должен сопровождаться `Cache-Control: no-store`, чтобы response не кэшировался. [web:78][web:85]

---

## Лимиты

| Параметр | Значение |
|---|---:|
| Note | 20,000 chars |
| Selected documents | 15 |
| Full indexed context | 64,000 estimated tokens |
| One document | 16,000 estimated tokens |
| Proposed changes | 10 |
| Created file | 64 KiB UTF-8 |
| Changed content per change | 64 KiB UTF-8 |
| Relative path | 512 chars |
| Review session TTL | 3 hours |
| Vault lock TTL | 60 seconds |
| Lock wait timeout | 5 seconds |

Не менять limits молча. Любое изменение должно быть обновлено в `concept.md`, соответствующей phase и test cases.

---

## Известные риски

### Indexed text отличается от original Markdown

Indexed text проходит parsing, preprocessing и chunking. Поэтому он используется только для LLM understanding; indexer строит final diff по original file.

Mitigation:

- LLM возвращает intent, не full file replacement;
- indexer использует exact anchors;
- UI показывает diff original file;
- apply проверяет SHA-256.

### Partial multi-vault apply

Нет distributed transaction между отдельными git repositories vault.

Mitigation:

- обработка по vault groups;
- explicit per-vault result;
- AuditLog;
- UI не говорит «всё успешно», если часть vault конфликтует.

### Git commit прошёл, reindex не запустился

Файл и git history уже изменены, но retrieval может временно видеть старый индекс.

Mitigation:

- `reindex_error` возвращается отдельно;
- UI показывает distinction;
- watcher остаётся fallback;
- нет автоматического git rollback.

### Prompt injection в note/documents

Campaign note и indexed markdown являются untrusted model inputs.

Mitigation:

- system instructions отдельно;
- data delimiters;
- strict structured output;
- DTO validation;
- indexer path/operation validation;
- human review;
- no LLM direct filesystem/git access.

Prompt injection — известный риск, когда недоверенный текст может пытаться изменить поведение LLM, поэтому защита должна быть многоуровневой, а не ограничиваться одним prompt. [web:159][web:160]

### Git содержит историю sensitive campaign data

Git history является долговременной, даже если пользователь позднее удаляет текст из файла.

Mitigation:

- local-only repo MVP;
- explicit staging;
- не коммитить `.env`, `.gitignore`, arbitrary files;
- document это ограничение пользователю;
- не отправлять repository remote автоматически.

---

## Security debt

Допустимо в single-user local MVP:

```text
Indexer internal API доступен только внутри Docker network,
без отдельной service-to-service authentication,
если в проекте ещё нет общего token mechanism.
```

До remote/multi-user deployment обязательно:

- добавить service-to-service token/mTLS;
- разделить filesystem read/write permissions;
- добавить user authorization на campaign/vault;
- добавить audit actor identity;
- определить secret scanning/pre-commit policy;
- определить vault-level ACL.

---

## Commit discipline

### Кодовые коммиты разработки

Рекомендуемая последовательность:

```text
feat(update-mode): add indexer path and git foundation
feat(update-mode): add contracts and review session store
feat(update-mode): add retrieval and intent generation
feat(update-mode): add safe apply and targeted reindex
feat(update-mode): add update mode UI and e2e coverage
docs(update-mode): finalize operational plan
```

Перед каждым commit:

```bash
git diff --check
pytest -q
```

Не коммитить:

- `.env`;
- API keys;
- vault content, если это не сознательная часть отдельного vault local repo;
- generated test artifacts;
- Redis dumps;
- temporary diff files;
- private logs.

`.gitignore` полезен как защита от случайного добавления sensitive files, но staging explicit paths остаётся обязательным. [web:69][web:73][web:76]

---

## Definition of done

Campaign Update Mode считается готовым только если одновременно:

- [ ] Все acceptance criteria фаз 0–5 закрыты.
- [ ] Migration применена и downgrade проверен.
- [ ] Backend, indexer и frontend tests проходят.
- [ ] Docker E2E update существующего файла проходит.
- [ ] Docker E2E create рядом с parent проходит.
- [ ] Docker E2E fallback `_campaign_notes` проходит.
- [ ] Multi-vault partial conflict корректно отображается.
- [ ] Stale checksum не перезаписывает ручную правку.
- [ ] Apply retry с same `apply_id` создаёт ровно один commit.
- [ ] Unrelated dirty files не попадают в snapshot/apply commit.
- [ ] Targeted reindex task успешно обновляет changed documents.
- [ ] AuditLog не содержит file content/diff/note.
- [ ] Deployment documentation описывает git, mounts, limits и security assumptions.