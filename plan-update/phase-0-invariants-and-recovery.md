# Фаза 0 — Инварианты, контракты и baseline

## Цель

До любой реализации Campaign Update Mode зафиксировать реальные contracts текущего Mercer, устранить ложные предположения старого плана и создать проверяемый baseline.

Эта фаза не добавляет пользовательскую функциональность. Её результат — безопасная основа для следующих фаз.

---

## Обязательные инварианты

### Vault configuration

- Таблица PostgreSQL `vaults` — единственный source of truth для свойств vault.
- `VaultConfigService` — только in-process cache DB-строк.
- Нельзя добавлять vault settings в YAML, `AppConfig`, `.env` или Python constants.
- В `Vault` не добавляется filesystem path.
- Pipeline и generation/embedding settings остаются DB-driven.

### Filesystem ownership

- Canonical vault root внутри контейнера: `/data/vaults/{vault_id}`.
- `rag-indexer` — единственный сервис, который читает оригинальные vault-файлы, строит diff, создаёт/изменяет markdown и вызывает git.
- `rag-backend` не должен читать или писать `/data/vaults` для update mode.
- Shared volume сохраняется для runtime, но ownership обеспечивается кодом и internal API contract.
- Backend обращается к indexer только по internal HTTP endpoint в `rag-net`.

### Document source separation

- Indexed chunks применяются для поиска и LLM context.
- Оригинальный `.md` применяется для preview, diff, checksum и apply.
- Полный indexed text никогда не записывается в файл напрямую.
- `full_document_service.reconstruct_full_text()` можно использовать только для reconstruction indexed context, не для подготовки write payload.

### MVP scope

Разрешено:

```text
update
append
create .md
```

Запрещено:

```text
delete
rename
move
create arbitrary directories
edit non-.md
edit .gitignore
edit .git/*
```

### Git safety

- Один local git repository в root каждого vault.
- Любой stage использует только explicit relative `.md` path list.
- Нельзя использовать `git add .`, `git add -A`, `git add -f`.
- Git subprocess запускается через argument list, без `shell=True`.
- Snapshot коммит включает только target files текущего apply.
- Git author identity берётся из DB vault override или deployment fallback env.

---

## Проверка текущей структуры

### Проверить migration location

Текущая миграционная история находится в:

```text
rag-backend/migrations/versions/
```

Новые миграции Campaign Update Mode добавляются туда же.

Не использовать:

```text
rag-backend/alembic/versions/
```

если такого runtime-configured пути нет.

### Проверить shared contracts

Проверить в `shared_contracts/models.py`:

- Pydantic v2 style (`model_config`, `model_validate`, `model_dump`);
- UUID сериализуются строками в API/Redis;
- новые DTO добавляются без duplicate local Pydantic models в router;
- back-compat поля `vault_id` в chat не удаляются этой фичей.

### Проверить DB session dependency

Новые backend API используют только существующий:

```python
from app.db.session import get_db

db: AsyncSession = Depends(get_db)
```

Не создавать новый engine, `sessionmaker`, global connection или отдельный database client для update mode.

### Проверить provider lifecycle

LLM provider берётся через существующий `SettingsService`:

```python
provider = settings_service.get_active_provider()
```

Если provider отсутствует:

```python
raise HTTPException(
    status_code=503,
    detail="No active generation model configured",
)
```

Нельзя создавать provider из `AppConfig`, импортировать API key в executor или повторно реализовывать provider factory.

### Проверить indexer file contract

Indexer уже строит filesystem location из:

```python
vault_path = f"/data/vaults/{vault_id}"
```

Перед созданием new services зафиксировать один shared helper внутри indexer:

```python
VAULT_ROOT = Path("/data/vaults")

def resolve_vault_root(vault_id: str) -> Path:
    root = (VAULT_ROOT / vault_id).resolve()
    if root.parent != VAULT_ROOT.resolve():
        raise ValueError("Invalid vault id")
    return root
```

Этот helper должен использоваться всеми новыми indexer update-mode services.

---

## Baseline тесты

До начала следующих фаз выполнить и сохранить результат:

```bash
docker compose config
docker compose --profile core up -d --build
docker compose ps
```

Backend:

```bash
cd rag-backend
pytest -q
```

Indexer:

```bash
cd rag-indexer
pytest -q
```

Если проект использует иной test command, зафиксировать фактическую команду в `plan-update/status.md`.

Также вручную проверить:

1. В PostgreSQL есть минимум один enabled vault.
2. У vault существует root `<VAULTS_PATH>/<vault_id>`.
3. В root есть хотя бы один `.md`.
4. Indexer индексирует этот `.md` в `documents` и chunks.
5. Backend и indexer видят один и тот же файл через `/data/vaults`.
6. У active generation model есть рабочий provider.

Не продолжать к следующей фазе, если baseline тесты уже падают по причинам, не связанным с Campaign Update Mode.

---

## Контракт internal indexer API

В этой фазе только зафиксировать contract; endpoint реализуется в следующих фазах.

### Authentication and network

- Endpoint не публикуется наружу через `ports`.
- Backend вызывает indexer по `INDEXER_API_URL`, default `http://rag-indexer:9000`.
- Endpoint доступен только внутри Docker network.
- Если в проекте уже есть service-to-service token, он обязателен.
- Если такого token нет, это допустимо для single-host local MVP, но endpoint всё равно не должен быть externally exposed.

### Resolve

```text
POST /internal/update-mode/resolve
```

Назначение: принять LLM intents, прочитать original files, построить resolved diffs.

Ответ возвращает change-by-change result; ошибка одной change не отменяет весь request.

### Apply

```text
POST /internal/update-mode/apply
```

Назначение: применить accepted resolved changes.

Indexer:

1. Захватывает lock по каждому vault;
2. Повторно проверяет checksum/absence;
3. Делает snapshot target files;
4. Атомарно пишет новые contents;
5. Создаёт git commit explicit file list;
6. Стартует targeted reindex;
7. Возвращает per-vault result.

### Health capability

Indexer должен предоставить либо расширить health/capability endpoint так, чтобы backend мог отличить:

```text
indexer unavailable
git unavailable
vault root missing
vault git initialization failed
```

Backend не должен пытаться выполнять git fallback самостоятельно.

---

## Ошибки и HTTP semantics

| Ситуация | Код | Payload code |
|---|---:|---|
| Chat/campaign/document не найден | 404 | `not_found` |
| Campaign не имеет tags | 422 | `campaign_tags_required` |
| Нет enabled vault domain | 422 | `no_enabled_vaults` |
| Невалидный request DTO | 422 | FastAPI validation |
| Нет active LLM provider | 503 | `generation_provider_unavailable` |
| Indexer недоступен | 503 | `indexer_unavailable` |
| Active review session уже есть | 409 | `session_already_active` |
| Redis session истекла | 410 | `session_expired` |
| Файл изменён после review | 409 | `file_modified` |
| File уже существует при create | 409 | `target_exists` |
| Root vault отсутствует | 409 | `vault_root_missing` |
| Git unavailable | 503 | `git_unavailable` |
| Vault lock не получен | 409 | `vault_lock_timeout` |

Для `410` response добавить:

```http
Cache-Control: no-store
```

Ответы backend не должны пробрасывать raw traceback или subprocess stderr пользователю. Полные технические детали остаются в structured logs.

---

## План DB изменений

В этой фазе определить, какие данные должны быть persisted, а какие нет.

### В PostgreSQL

Добавить только то, что относится к долгоживущей DB-конфигурации vault:

```text
vaults.git_author_name  nullable string
vaults.git_author_email nullable string
```

Оба поля — optional vault override.

### Не добавлять в PostgreSQL

Не добавлять:

```text
Chat.update_mode_enabled
Chat.update_mode_pending
Vault.path
Vault.versioned_extensions
Vault.git_initialized
```

Причины:

- active review state принадлежит Redis TTL session;
- файловый path является deterministic deployment contract;
- MVP работает только с `.md`;
- git initialization — runtime capability, не DB setting.

### Redis

Redis хранит transient review session:

```text
update_mode:{chat_id}
```

TTL: 3 часа.

Сессия включает:

- chat/campaign/domain identity;
- discovered vault IDs;
- candidate document IDs;
- warnings об исключённых больших документах;
- resolved changes;
- chosen statuses (`pending`, `accepted`, `rejected`);
- `apply_id`, когда apply начат;
- timestamps.

Redis payload сериализуется через Pydantic v2:

```python
model.model_dump(mode="json")
```

и восстанавливается через:

```python
Model.model_validate(data)
```

---

## Acceptance criteria фазы

Фаза завершена, когда:

- [ ] Подтверждён актуальный baseline тестов backend/indexer.
- [ ] Фиксирован единственный migration path.
- [ ] Нет планов добавить Vault.path, Vault.versioned_extensions или persisted chat mode flag.
- [ ] Зафиксирован internal API boundary: backend orchestrates, indexer owns file/git.
- [ ] Зафиксированы resolve/apply contracts и error semantics.
- [ ] Зафиксирована multi-vault логика: все enabled vault domain, campaign tags ограничивают documents.
- [ ] Зафиксированы TTL, lock, conflict и idempotency правила.
- [ ] Все последующие фазы ссылаются на этот документ как на источник архитектурных инвариантов.