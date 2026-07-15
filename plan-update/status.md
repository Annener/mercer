# Campaign Update Mode — Статус реализации

## Назначение

Этот документ — единственный operational status для Campaign Update Mode.

Он отвечает на вопросы:

- какая фаза выполняется;
- какие инварианты нельзя нарушать;
- какие команды подтверждают готовность;
- какие риски остаются;
- что должна сделать следующая модель или разработчик.

Не использовать этот файл как changelog пользовательских релизов.

---

## Текущий статус

```text
Состояние: Фаза 1 завершена, готовны к фазе 2
Текущая фаза: 2 — DB fields, DTO, Redis session, router skeleton
Последнее обновление: 2026-07-15
```

### Baseline checklist

- [x] Alembic head: `0004_fulldoc_jsonb_fix (head)` — подтверждён 2026-07-15.
- [x] Backend tests: 136 passed, 11 pre-existing failures (unrelated).
- [x] Indexer tests: 95 passed + 39 new — **134 passed**, 3 pre-existing failures.
- [x] `/data/vaults` mount: `mount ok`.
- [x] `git version 2.47.3` в indexer image.

---

## Pre-existing test failures (not Campaign Update Mode)

Не исправлять в рамках Campaign Update Mode.

### rag-backend (11 failed, 136 passed)

| Файл | Тесты | Причина |
|---|---|---|
| `test_pipeline_executor_integration.py` | `TestParallelDagIntegration` (2) | `_retrieve_for_step_dag` получил новый 3й аргумент `provider`; mock пишет 2 |
| `test_pipeline_resume.py` | `TestPipelineResume` (2) | patch по неверному import path / ключ `_validation_` не совпадает с production |
| `test_planner_td03.py` | `TestPlannerMissingFields` (4) | `Planner._missing_fields` удалён/переименован в production |
| `test_redis_endpoints.py` | (2) | роуты вернули 404 |
| `test_watchdog_api.py` | (1) | indexer отклоняет task с 404 для unknown vault |

### rag-indexer (3 failed)

| Файл | Тест | Причина |
|---|---|---|
| `test_embed_batch.py` | `test_parallel_not_sequential` | `embed_batch` sequential, не `asyncio.gather` |
| `test_watchdog_lifespan.py` | (2) | `watchdog_loop()` не принимает `interval_sec` |

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
| 0 | `phase-0-invariants-and-recovery.md` | Baseline, boundaries, migration path, contracts | **Done** |
| 1 | `phase-1-git-infrastructure.md` | Indexer path/file/git foundation | **Done** |
| 2 | `phase-2-data-model.md` | DB fields, DTO, Redis session, router skeleton | In progress |
| 3 | `phase-3-executor.md` | Campaign scope, retrieval, LLM intents, resolve | Not started |
| 4 | `phase-4-api.md` | Review, apply, git commits, targeted reindex | Not started |
| 5 | `phase-5-sse-frontend.md` | UI, E2E, deployment, observability | Not started |

---

## Проверенные факты репозитория

### Database и migrations

- Миграции: `rag-backend/migrations/versions/`.
- Фактический head: `0004_fulldoc_jsonb_fix` — подтверждён 2026-07-15.
- Новая migration ссылается на `0004_fulldoc_jsonb_fix` как `down_revision`.

### Backend

- Session dependency: `get_db()` в `rag-backend/app/db/session.py`.
- Active provider: `settings_service.get_active_provider()`.
- `full_document_service.reconstruct_full_text()` собирает indexed text документа.
- Baseline: 136 passed, 11 pre-existing failures.

### Indexer

- Vault path: `/data/vaults/{vault_id}`.
- `/data/vaults` mount: `mount ok` — подтверждено.
- `git version 2.47.3` — подтверждено.
- Baseline: 134 passed (95 + 39 new), 3 pre-existing failures.
- `app/update_mode/fs_git.py` — path validation, file I/O, git primitives: **39/39 tests pass**.

### Docker

- `rag-backend` и `rag-indexer` монтируют `${VAULTS_PATH}` в `/data/vaults:rw`.
- `rag-indexer` доступен backend по service URL внутри Docker network.
- Internal update-mode API не публикуется наружу.

---

## Обязательные runtime команды

```bash
git status --short
docker compose config
docker compose ps
```

```bash
cd rag-backend && alembic heads && alembic current
cd rag-backend && pytest -q
cd rag-indexer && pytest -q
```

```bash
docker compose exec rag-indexer sh -lc 'git --version'
docker compose exec rag-indexer sh -lc 'test -d /data/vaults && test -w /data/vaults && echo "mount ok"'
```

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
| `vault_lock_timeout` | 409 | Vault занят другой apply/resolve | Retry пожже |
| `git_unavailable` | 503 | Git отсутствует/недоступен | Исправить indexer image |
| `git_identity_missing` | 503 | Нет DB или fallback git identity | Настроить vault/env |
| `git_ignored_target` | 409 | Git игнорирует target `.md` | Исправить вручную |
| `apply_already_started` | 409 | Другой apply ID уже выполняется | Retry тем же ID |
| `apply_id_payload_mismatch` | 409 | Same apply ID, другой payload | Не retry с изменённым payload |
| `apply_in_progress` | 409 | Apply с тем же ID ещё выполняется | Poll/retry пожже |

`410 Gone` для expired review session должен сопровождаться `Cache-Control: no-store`.

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

---

## Известные риски

### Indexed text отличается от original Markdown
Mitigation: LLM возвращает intent; indexer использует exact anchors; apply проверяет SHA-256.

### Partial multi-vault apply
Mitigation: обработка по vault groups; explicit per-vault result; AuditLog.

### Git commit прошёл, reindex не запустился
Mitigation: `reindex_error` возвращается отдельно; watcher остаётся fallback.

### Prompt injection
Mitigation: system instructions отдельно; strict structured output; DTO validation; indexer path validation; human review.

### Git history sensitive data
Mitigation: local-only repo; explicit staging; не отправлять remote автоматически.

---

## Security debt

Допустимо в single-user local MVP: indexer internal API доступен только внутри Docker network без service-to-service auth.

---

## Definition of done

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
