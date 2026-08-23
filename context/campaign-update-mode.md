# Campaign Update Mode

## Назначение

Campaign Update Mode — управляемый процесс актуализации markdown-контекста кампании.

Пользователь вводит заметку о новых событиях. Система:

1. Ищет связанные знания в уже проиндексированных chunks;
2. Передаёт LLM полный **индексированный** текст найденных markdown-документов;
3. Получает от LLM намерения правок (`edit intents`), а не готовые перезаписанные файлы;
4. Передаёт intents в `rag-indexer`;
5. Indexer читает реальные оригинальные `.md`-файлы, разрешает место правки, строит точный diff;
6. Пользователь делает review, принимает или отклоняет каждую правку;
7. Indexer безопасно применяет подтверждённые изменения, создаёт локальные git-коммиты и запускает targeted reindex.

Режим не предназначен для автоматического применения изменений. Review и явный Apply обязательны.

---

## Границы MVP

| В scope | Вне scope |
|---|---|
| Только `.md`-файлы | PDF, DOCX, изображения, бинарные файлы |
| Update, append и create `.md` | Delete, rename, move существующих файлов |
| Локальный git внутри каждого vault | Remote, push, pull, merge, ветки |
| Single-user local instance | Multi-user authorization и роли |
| Campaign tags + indexed chunks | Поиск по всему vault без tags |
| Один vault git-repo на vault | Отдельный git-repo на campaign |
| Targeted reindex после apply | Ожидание полного watchdog scan |
| Новый файл рядом с parent-документом | Создание произвольных директорий |
| `_campaign_notes/` как controlled fallback | Управление структурой каталогов LLM |

---

## Архитектурные инварианты

### DB-only для vault

Все настройки vault — только PostgreSQL.

`VaultConfigService` является process-local кэшированной проекцией таблицы `vaults`; он не является отдельным конфигом и не должен быть source of truth для write-операций.

Запрещено:

- Добавлять vault-настройки в YAML, `AppConfig`, `.env` или статические Python-словари;
- Добавлять физический `path` в ORM-модель `Vault`;
- Читать vault-список из `AppConfig.vaults`.

### Файловый contract

Физический root vault определяется deployment mount:

```text
/data/vaults/{vault_id}
```

`VAULT_ROOT=/data/vaults` — infrastructure-level путь внутри контейнера, а не пользовательская настройка vault.

- `rag-indexer` является единственным владельцем операций чтения оригинальных файлов, diff, записи и git.
- `rag-backend` не читает и не пишет файлы vault напрямую.
- `rag-backend` и `rag-indexer` видят общий `${VAULTS_PATH}` mount в `/data/vaults`.
- `vault_id` существует только после проверки в PostgreSQL.

### Security

Любой путь, полученный от LLM, API-клиента или Redis, считается недоверенным.

Indexer обязан:

1. Разрешать путь только относительно `VAULT_ROOT / vault_id`;
2. Нормализовать путь через `Path.resolve()`;
3. Проверять, что итог находится внутри root конкретного vault;
4. Запрещать абсолютные пути, `..`, NUL, path separators в `suggested_filename`;
5. Разрешать только `.md`;
6. Никогда не принимать путь к `.git`, `.gitignore` или служебным файлам;
7. Никогда не использовать `git add .`, `git add -A`, `git add -f` или shell interpolation.

---

## Multi-vault scope

Campaign Update Mode всегда использует все enabled vault текущего domain:

```sql
SELECT *
FROM vaults
WHERE domain_id = chat.domain_id
  AND enabled = true;
```

Пользователь не выбирает vault вручную.

Документ может участвовать в update mode только если одновременно:

- принадлежит enabled vault текущего domain;
- имеет `status = 'indexed'`;
- имеет `.md` расширение;
- связан хотя бы с одним tag активной campaign.

Если у campaign нет tags, start возвращает `422`:

```text
Campaign Update Mode requires at least one campaign tag.
```

Если в domain нет enabled vault, start возвращает `422`.

---

## Два представления документа

### Indexed representation

Используется для поиска и понимания контекста:

1. Backend ищет релевантные chunks среди разрешённых `.md`-документов.
2. Выбирает до 15 документов.
3. Через `db-api-server` восстанавливает полный индексированный текст выбранного документа из chunks.
4. Передаёт полный indexed text в LLM.

### Original file representation

Используется только для подготовки и применения реальных изменений:

1. LLM возвращает edit intent.
2. Indexer читает оригинальный `.md` в vault.
3. Indexer разрешает anchor или operation в оригинальном файле.
4. Indexer возвращает фактические `original_content`, `proposed_content`, unified diff и checksum.
5. Пользователь review-ит именно diff оригинального файла.
6. Перед apply indexer повторно проверяет checksum оригинального файла.

Индексированный текст не является write-source и не должен полностью перезаписывать оригинальный markdown.

---

## Поток операции

```text
UI
 │  POST /api/chats/{chat_id}/update-mode/start
 ▼
rag-backend
 │  validate chat + campaign + campaign tags
 │  select enabled vaults of chat.domain_id
 │  retrieve relevant indexed .md chunks
 │  reconstruct full indexed documents
 │  call LLM for edit intents
 ▼
rag-indexer (internal HTTP)
 │  read original .md files
 │  resolve anchors / create targets
 │  calculate SHA-256
 │  build exact diffs
 ▼
rag-backend
 │  stores review session in Redis
 ▼
UI review
 │  accept / reject / rephrase
 ▼
rag-backend
 │  POST accepted changes to rag-indexer
 ▼
rag-indexer
 │  acquire vault locks
 │  verify checksums
 │  snapshot affected .md files
 │  atomic writes
 │  git add explicit file list
 │  apply commit
 │  start targeted reindex
 ▼
rag-backend
 │  AuditLog + remove Redis session after final result
 ▼
UI
    per-vault commits and reindex task IDs
```

---

## LLM output: edit intent

LLM не возвращает complete `proposed_content` всего файла и не задаёт произвольный абсолютный путь.

### Update / append

```json
{
  "change_id": "uuid4",
  "action": "update",
  "document_id": "uuid документа из предоставленного контекста",
  "description": "Добавить результат последней игровой сессии",
  "anchor": {
    "kind": "markdown_heading",
    "value": "## Последняя сессия"
  },
  "operation": "append_after_section",
  "content": "### 2026-07-15\n- Группа заключила союз с ..."
}
```

Поддерживаемые MVP operations:

| Action | Operation | Назначение |
|---|---|---|
| `update` | `append_after_section` | Добавить контент после секции heading |
| `update` | `append_to_file` | Добавить контент в конец файла |
| `update` | `replace_unique_text` | Заменить один точный уникальный фрагмент |
| `create` | `create_file` | Создать новый markdown-файл |

Для `replace_unique_text` anchor обязан совпасть в оригинальном файле ровно один раз.

### Create

```json
{
  "change_id": "uuid4",
  "action": "create",
  "parent_document_id": "uuid релевантного документа или null",
  "suggested_filename": "session-2026-07-15.md",
  "description": "Создать отдельную заметку с итогами сессии",
  "content": "# Сессия 15 июля\n\n- ..."
}
```

LLM может выбрать `parent_document_id` только из document IDs, переданных в её контексте.

Indexer определяет конечный `vault_id` и `file_path`:

1. Если есть `parent_document_id`, файл создаётся рядом с ним в том же vault;
2. Если parent отсутствует, target vault выбирается детерминированно:
   - `chat.vault_id`, если vault существует, enabled и принадлежит domain;
   - иначе vault самого релевантного найденного документа;
   - иначе первый enabled vault domain по `vault_id ASC`;
3. При fallback файл создаётся в `<vault-root>/_campaign_notes/<suggested_filename>`;
4. Только `_campaign_notes/` может быть создана автоматически;
5. Если целевой файл уже существует, change получает `target_exists`; файл не перезаписывается.

---

## Resolved change

После обработки indexer backend хранит в Redis не raw LLM intent, а resolved change:

```python
class ResolvedChange(BaseModel):
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
    status: Literal["pending", "accepted", "rejected", "resolution_failed"] = "pending"
    error_code: str | None = None
    error_message: str | None = None
```

`original_content` и `proposed_content` относятся к оригинальному файлу, не к реконструированному indexed text.

Для `create`:

- `original_content = ""`;
- `expected_sha256 = None`;
- apply обязан повторно проверить, что файл всё ещё не существует.

---

## Ошибки разрешения правок

Indexer возвращает typed result для каждой правки. Ошибка одной правки не отменяет остальные.

```text
invalid_target
file_not_found
file_modified
anchor_not_found
anchor_ambiguous
target_exists
git_ignored_target
content_limit_exceeded
unsupported_operation
invalid_filename
invalid_path
vault_root_missing
vault_lock_timeout
```

Indexer не должен применять fuzzy replacement, угадывать другой файл или менять intent молча.

---

## Concurrency и идемпотентность

### Redis session

- Redis key: `update_mode:{chat_id}`;
- TTL: 3 часа;
- одна активная review session на chat;
- повторный start для того же chat возвращает `409`, пока существующая сессия не отменена или не истекла;
- истёкшая сессия на action/apply возвращает `410 Gone` с `Cache-Control: no-store`.

### Vault lock

Indexer использует отдельный lock на каждый vault только во время `resolve` и `apply`.

- Redis key: `update_mode:vault_lock:{vault_id}`;
- TTL lock: 60 секунд;
- lock не держится всё время review;
- при невозможности получить lock возвращается `vault_lock_timeout`;
- apply группирует accepted changes по `vault_id`.

### Apply idempotency

Каждый apply имеет `apply_id: UUID`.

Indexer хранит краткоживущий результат применённого `apply_id` в Redis. Повторный запрос с тем же `apply_id` возвращает тот же результат и не создаёт второй commit.

### Проверка конфликтов

Перед записью indexer:

- для `update` повторно читает оригинальный файл;
- вычисляет SHA-256;
- сравнивает с `expected_sha256`;
- при несовпадении не пишет файл и возвращает `file_modified`.

Для `create` indexer повторно проверяет отсутствие target file.

`file_modified` является конфликтом состояния и наружный API возвращает `409 Conflict`.

---

## Git-стратегия

### Инициализация

У каждого существующего vault root свой локальный git-repo.

```text
/data/vaults/{vault_id}/.git
```

При backend/indexer startup допускается best-effort `git init` только если root существует и является каталогом.

| Состояние root | Результат |
|---|---|
| Каталог, `.git` отсутствует | `git init` |
| Каталог, `.git` существует | no-op |
| Root отсутствует | `missing_root`, warning, сервис не падает |
| Root не каталог | `invalid_root`, error, сервис не падает |
| git недоступен/ошибка | update mode для vault вернёт `503`, сервис не падает |

### Identity

Git author identity берётся из PostgreSQL:

- `Vault.git_author_name`;
- `Vault.git_author_email`.

Если vault override отсутствует, используется deployment fallback через environment variables:

```text
GIT_AUTHOR_NAME=Mercer
GIT_AUTHOR_EMAIL=mercer@local
```

Environment fallback не является настройкой vault и не должен быть записан в `AppConfig`.

Identity передаётся process-local в subprocess environment (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`). Глобальный git config пользователя не изменяется.

### Snapshot

Перед apply indexer делает snapshot только для `.md`-файлов, затрагиваемых accepted changes в конкретном vault.

- Проверяется status только explicit target path list;
- В snapshot не должны попасть другие dirty-файлы;
- Если среди target paths есть изменения, создаётся commit: `snapshot: manual edits before campaign update`;
- Если нет target изменений, snapshot commit не создаётся;
- Игнорируемый git-файл не добавляется принудительно.

### Apply commit

После успешных atomic writes indexer выполняет:

```text
git add -- <explicit relative md path list>
git commit -m "<message>"
```

Запрещены `git add .`, `git add -A`, `git add -f` и shell command strings.

Fallback message: `campaign-update: apply reviewed changes`

LLM-generated message опционален, ограничен 72 символами и не должен блокировать apply.

---

## Targeted reindex

После apply commit indexer запускает targeted reindex только изменённых/созданных markdown-файлов.

- Apply не ждёт завершения индексации;
- Для каждого vault результат содержит `reindex_task_id`;
- UI использует существующий индексатор task/status API;
- Если commit успешен, но reindex не удалось стартовать, результат явно содержит `reindex_error`;
- Redis review session не удаляется до получения финального per-vault apply result.

Watcher остаётся дополнительным механизмом обнаружения внешних ручных изменений, но не является основным trigger для Campaign Update Mode.

---

## Multi-vault apply result

Apply не является распределённой транзакцией между разными git-repositories. Изменения группируются и применяются по vault. Возможен частичный успех.

```json
{
  "apply_id": "uuid4",
  "results": [
    {
      "vault_id": "dnd-main",
      "status": "applied",
      "applied_count": 2,
      "snapshot_commit_sha": "abc123",
      "commit_sha": "def456",
      "commit_message": "campaign-update: record session outcomes",
      "reindex_task_id": "task-uuid",
      "reindex_error": null
    },
    {
      "vault_id": "dnd-lore",
      "status": "conflict",
      "applied_count": 0,
      "error_code": "file_modified",
      "error_message": "lore/factions.md changed after review"
    }
  ]
}
```

Backend сохраняет AuditLog с `chat_id`, `campaign_id`, `apply_id`, vault results, commit SHA, accepted `change_id` и reindex task ID.

---

## Лимиты MVP

| Ограничение | Значение |
|---|---:|
| Максимум выбранных документов | 15 |
| Максимум full indexed context | 64,000 tokens |
| Максимум full indexed текста одного документа | 16,000 tokens |
| Максимум предложенных изменений | 10 |
| Максимальная длина user note | 20,000 символов |
| Максимальный размер created file | 64 KiB UTF-8 |
| Максимальный объём изменяемого контента одного change | 64 KiB UTF-8 |
| Максимальная длина относительного пути | 512 символов |
| Redis review session TTL | 3 часа |
| Vault lock TTL | 60 секунд |

Если документ превышает per-document limit, он не передаётся в LLM full text; backend добавляет warning в session. Полный контекст не обрезается молча.

---

## Ключевые файлы реализации

```text
rag-backend/
├── app/
│   ├── api/update_mode.py                  — Public API роутер
│   ├── services/update_mode_executor.py    — Orchestrator: retrieval → LLM → resolve
│   ├── services/update_mode_store.py       — Redis review session CRUD
│   ├── services/indexer_client.py          — HTTP-клиент к rag-indexer internal API
│   ├── services/campaign_state_value_service.py — Versioned state + patch apply (Stage 5 dependency)
│   ├── db/models.py                        — ORM (Vault.git_author_name/email, AuditLog, CampaignState*)
│   └── main.py
├── migrations/versions/
│   └── NNNN_campaign_update_mode.py        — Alembic-миграция (до 0005_campaign_update_git_identity)
└── app/tests/
    ├── test_update_mode_models.py
    ├── test_update_mode_executor.py
    ├── test_update_mode_store.py
    ├── test_update_mode_api.py
    └── test_update_mode_state_patch.py     — state_patch decisions, apply, audit

rag-indexer/
├── api/update_mode.py                      — Internal endpoints /internal/update-mode/*
├── services/update_mode_file_service.py    — Чтение файлов, diff, path validation
├── services/vault_git_service.py           — Git: init, snapshot, commit
└── tests/
    ├── test_update_mode_file_service.py
    ├── test_vault_git_service.py
    └── test_update_mode_internal_api.py

shared_contracts/
└── models.py                               — ResolvedChange, EditIntent, Apply*, Stage 5 state-patch DTO
```

---

## Stage 5: state_patch в proposal

Помимо file-intent правок, Update Mode возвращает **state_patch** — точечные операции над Campaign State.

### Семантика

- Каждая сессия `POST /start` дополнительно возвращает:
  - `state_field_snapshot` — упорядоченный снимок enabled-полей кампании (`field_id`, `key`, `label`, `mode`);
  - `state_patch_operations` — массив операций, каждая с серверным `op_index`, `field_key`, `field_label`, `mode`, `operation`, `previous_text`, `proposed_text`, `status: pending`.
- LLM получает в `<campaign_state>` user-message блок текущих значений полей (single — текст, list — `<item key="...">`) и возвращает JSON:
  ```json
  {
    "intents": [...],
    "no_change_reason": null,
    "state_patch": [
      { "type": "replace_single", "field_key": "current_focus",
        "text": "...", "reason": "...", "source_refs": ["file:<doc_id>:sha:<md5>"] }
    ],
    "state_patch_questions": []
  }
  ```
- Допустимые операции (см. спека §6.1):
  - `single`: `replace_single`, `clear_single`;
  - `list`: `add_list_item`, `update_list_item`, `resolve_list_item`, `remove_list_item`.

### Pre-validation

Перед сохранением в Redis backend отбрасывает операции, нарушающие snapshot-инварианты:
- `field_key` не найден в snapshot;
- `mode ↔ type` mismatch (например, `replace_single` для list-поля);
- `update_list_item | resolve_list_item | remove_list_item` ссылаются на несуществующий `item_key` в текущем state;
- `replace_single | update_list_item | add_list_item` имеют пустой текст.

Отброшенные операции добавляются в `warnings` сессии (`state_patch_dropped:*`).

### Review

`PATCH /review` принимает `state_patch_decisions`:

```json
{
  "accepted_change_ids": ["chg-1"],
  "rejected_change_ids": [],
  "state_patch_decisions": {
    "accepted_op_indexes": [0, 2],
    "rejected_op_indexes": [1],
    "edited": [{"op_index": 0, "text": "правленый текст"}]
  }
}
```

- Inline-edit допустим только для операций с text-полем (`replace_single | update_list_item | add_list_item`);
- edited применяется к `operation.text` атомарно в Lua-скрипте `_REVIEW_LUA`;
- `rejected` и `accepted` не должны пересекаться;
- `edited` не должен ссылаться на `rejected` op_index.

### Apply

`POST /apply`:
1. Применяет file changes через `rag-indexer` (как раньше).
2. Применяет принятые state-patch операции через `campaign_state_value_service.apply_patch`, формируя новую `CampaignStateVersion` (как при Stage 2 patch).
3. edited_text подставляется в `op.text` перед apply.
4. Failure (config_version conflict, source stale) → `state_patch_result.failed_op_indexes`, file-apply продолжается.
5. Audit log `update_mode.apply` дополнен блоком `state_patch` (accepted/rejected/edited op_indexes, applied_state_version, config_version).
6. Audit log `update_mode.reject_state_patch` (отдельная запись) пишется при наличии rejected state ops.

Файл-изменения и state-patch принимаются независимо: файл-apply продолжается даже при провале state-apply (spec §7.1).

---

## Stage 6: prompt assembly с Campaign State

После применения активной версии Campaign State блок попадает в `system_prompt`
любого чат-turn кампании. Это делает модель осведомлённой о текущем контексте
кампании без обязательного retrieval.

### Где инжектируется

Скомпилированный блок добавляется через `app/services/effective_context.compose_full_system_prompt`,
которая склеивает `system_prompt + campaign_state_block` через `filter(None)`.

Точки интеграции:

| Путь | Назначение |
|---|---|
| `rag-backend/app/api/chat.py::plain_stream` | SSE-стрим plain RAG fallback |
| `rag-backend/app/api/chat.py::_plain_llm_reply` | Не-стриминговый путь |
| `rag-backend/app/api/pipeline_resume.py::_plain_rag_stream` | Подтверждение пайплайна отменено |
| `rag-backend/app/services/pipeline_executor.py::PipelineExecutor._run_final_composition` | Конечная композиция пайплайна (после `_resolve_prompt`) |
| `rag-backend/app/services/pipeline_executor.py::PipelineExecutor.resume_from_full_doc_selection` | Plain-fallback ветка full-doc resume |

`_run_final_composition` использует `compose_state_block_only` (только блок state,
без system_prompt) — это сохраняет существующие шаблоны с `{query}`/`{STEP_ID.*}`
нетронутыми и добавляет state как дополнительный блок.

### Token budget

По умолчанию ~800 токенов на скомпилированный блок (см. `chat.campaign_state_token_budget`
в `app/services/settings_service.py`). Поля исключаются целиком, не обрезаются
посередине. Превышение лимита попадает в `truncated_fields` debug-view.

Эвристика токенов: `math.ceil(len(text) / 4)` — согласована с остальным кодом
(`update_mode_executor.py`, `pipeline_executor.py`, `full_document_service.py`).

### Debug-view: `GET /api/settings/campaigns/{id}/effective-context`

Возвращает `EffectiveContextRead` с блоками:

- `system_prompt`;
- `campaign_state` (если есть active state);
- `rag_context` (если задан `include_rag=True`, для debug не заполняется);
- `history` / `user_message` (опционально).

Endpoint всегда возвращает 200 даже если state отсутствует. Не выполняет
retrieval и не запускает LLM. Используется для инспекции prompt assembly.

### Ключевые модули

- `rag-backend/app/services/campaign_state_compiler.py` — детерминированный
  компилятор (`compile_campaign_state`, чистая функция);
- `rag-backend/app/services/effective_context.py` — общие helper-функции для
  runtime и debug (`compose_full_system_prompt`, `build_effective_context`);
- `rag-backend/app/services/campaign_state_value_service.py::list_enabled_fields_ordered` —
  загрузка enabled-полей кампании в порядке `display_order ASC, key ASC`;
- `shared_contracts/models.py::CampaignStateCompiledBlock`, `EffectiveContextRead`,
  `EffectiveContextBlock`, `CampaignStateCompiledFieldRead` — DTO.

### Чего этап 6 НЕ делает

- Не вводит `search_knowledge` tool и bounded agent loop (§12 — отдельный этап 8);
- Не меняет `_resolve_system_prompt` контракт (для обратной совместимости
  `_resolve_system_prompt` остался в `chat.py` и использует helper из
  `effective_context._resolve_system_prompt_text`);
- Не хранит compiled state в БД — это чистая функция от active state;
- Не обновляет UI рендер effective-context — endpoint готов, визуальная
  панель остаётся отдельной задачей.
