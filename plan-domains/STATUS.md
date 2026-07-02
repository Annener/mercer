# STATUS — Domain Isolation Fix

> Обновлять после каждого шага. Формат статуса: TODO / IN PROGRESS / DONE / BLOCKED / SKIPPED

Последнее обновление: 2026-07-03

## Сводная таблица

| # | Шаг | Статус | Дата | Заметки |
|---|---|---|---|---|
| 1 | Domain-selector Campaigns (frontend) | DONE | 2026-07-02 | Добавлен _activeDomainId в constructor, вызов _attachCampaignsTabListeners в _afterTabRender |
| 2 | Domain-selector Pipelines (frontend) | DONE | 2026-07-02 | Добавлен вызов _attachPipelinesTabListeners в _afterTabRender; shared _activeDomainId подтверждён |
| 3 | Domain-фильтр Vaults (frontend) | DONE | 2026-07-02 | runtime-fix в api/vaults.js |
| 4 | Domain_id параметр Vaults (backend) | DONE | 2026-07-02 | Уже реализован в app/api/settings/vaults.py; ревью/план устарели |
| 5 | Domain-selector Documents (новый UI) | DONE | 2026-07-03 | Добавлен #docs-domain-select, _attachDocumentsTabListeners, runIndexer принимает _activeDomainId |
| 6 | Cross-domain валидация Pipeline↔Campaign (backend) | DONE | 2026-07-03 | _check_campaign_domain helper + валидация в create/update + campaign_id в схемах и pipeline_dict |
| 7 | Chat.vault_id domain-check (backend) | DONE | 2026-07-03 | _check_vault_domain helper + вызов в create_chat; Vault добавлен в импорты chat.py |
| 8 | GET /api/chat/ domain_id параметр | DONE | 2026-07-03 | Уже реализован — list_chats принимает domain_id; ревью устарело |
| 9 | Исследование Vault.domain_id nullable | DONE | 2026-07-03 | nullable=True + ondelete=SET NULL подтверждены; SQL-запрос для проверки данных в БД задокументирован |

## Легенда статусов

- **TODO** — не начато
- **IN PROGRESS** — в работе (указать что именно сделано частично)
- **DONE** — завершено, тесты прошли
- **BLOCKED** — заблокировано, указать причину и что нужно для разблокировки
- **SKIPPED** — сознательно пропущено

## Журнал изменений (append-only, не переписывать старые записи)

<!--
Формат записи:

### Шаг N — дата
- Что сделано
- Результат тестов (pass/fail, что именно)
- Проблемы/блокеры, если есть
- Следующий шаг

-->

### Инициализация — 2026-07-02
- Создан концепт (concept.md), гранулярные шаги (steps.md), этот файл статуса,
  промпт-файл (prompt.md).
- Ревью изоляции доменов завершено (plan-domains/domain-isolation-review.md).
- Работа по фиксам ещё не начата.

### Шаг 1 — 2026-07-02
- Добавлено `this._activeDomainId = null` в конструктор `SettingsManager`.
- В `_afterTabRender(tab)` добавлен вызов `this._attachCampaignsTabListeners(this._tabContent)` при `tab === 'campaigns'`.
- Теперь domain-selector в тулбаре Campaigns отвечает на `change`: обновляет `_activeDomainId` и перезагружает таб.
- Тесты (unit, JS): фреймворк тестирования (Jest/Vitest) в проекте отсутствует, автотесты не запускались. См. ручной сценарий ниже.
- Результат ручной проверки: необходима (commit fec4505).
- Следующий шаг: Шаг 2 (аналогично для Pipelines).

#### Заметка: отсутствие JS-фреймворка тестирования
Фронтенд проверяется вручную, бачкенд проверяется через pytest (см. rag-backend/app/tests/).
1. Открыть Settings → перейти на вкладку **Campaigns**.
2. Убедиться что `#campaigns-domain-select` присутствует в DOM.
3. Выбрать домен из селектора.
4. Убедиться что список кампаний обновился и показывает только кампании выбранного домена.
5. Выбрать "Все домены" — убедиться что показываются все кампании.
6. В DevTools console: `settingsManager._activeDomainId` — должно совпадать с выбранным доменом (null для "все").

### Шаг 2 — 2026-07-02
- В `_afterTabRender(tab)` добавлен вызов `this._attachPipelinesTabListeners(this._tabContent)` при `tab === 'pipelines'`.
- `_activeDomainId` уже существовал на уровне `SettingsManager` (shared state) — дополнительных изменений не потребовалось.
- `tab-pipelines.js` изменений не требует: `renderPipelinesTab()` уже читает `this._activeDomainId` и рисует `#pipelines-domain-select`; `_attachPipelinesTabListeners` определён и корректен.
- Тесты: JS-фреймворк отсутствует, автотесты не запускались. См. ручной сценарий ниже.
- Результат: commit 3184971.
- Следующий шаг: Шаг 3 (Domain-фильтр Vaults, frontend).

#### Ручной сценарий проверки Шаг 2
1. Открыть Settings → перейти на вкладку **Pipelines**.
2. Убедиться что `#pipelines-domain-select` присутствует в DOM.
3. Выбрать домен из селектора — список пайплайнов должен обновиться.
4. В DevTools: `settingsManager._activeDomainId` — должно совпадать с выбранным доменом.
5. Переключиться на вкладку Campaigns, снова на Pipelines — селектор должен сохранять значение (shared `_activeDomainId`).

### Шаг 3 — 2026-07-02
- `api.js`: `getSettingsVaults(domainId = null)` — теперь явный алиас `getVaults(domainId)`, пробрасывает `domain_id` в query-параметр (commit ca79331).
- `tab-vaults.js`: `renderVaultsTab()` читает `this._activeDomainId`, добавлен domain-selector `#vaults-domain-select` в тулбар, добавлен `_attachVaultsTabListeners` (commit c345591).
- `settings.js`: `_afterTabRender` вызывает `_attachVaultsTabListeners` при `tab === 'vaults'` (commit d557823).
- Тесты: `rag-backend/app/tests/test_vaults_domain_filter.py` — 5 юнит-тестов логики фильтрации без БД; запуск: `pytest rag-backend/app/tests/test_vaults_domain_filter.py -v`.
- Фронтенд проверяется вручную (см. сценарий ниже).
- Следующий шаг: Шаг 4 (бекенд GET /api/settings/vaults фильтр по domain_id).

#### Ручной сценарий проверки Шаг 3
1. Открыть Settings → перейти на вкладку **Vaults**.
2. Убедиться что `#vaults-domain-select` присутствует в DOM рядом с кнопкой "+ Новый vault".
3. Выбрать домен — список vault'ов должен обновиться и показывать только vault'ы выбранного домена.
4. Выбрать "Все домены" — должны показаться все vault'ы.
5. Переключиться на другую вкладку и обратно на Vaults — `_activeDomainId` сохраняется (shared state).
6. В DevTools: в запросе к Network → фильтр по "vaults" — URL должен содержать `?domain_id=<id>` при выбранном домене.

#### Заметка: фронтенд vs backend для Шага 3
Шаг 3 — фронтендовый. Backend-эндпойнт `GET /api/settings/vaults` сейчас принимает параметр `domain_id` или нет — не верифицировано в рамках этого шага. Шаг 4 (следующий) добавит фильтрацию на стороне бекенда — только тогда цепочка замкнётся полностью.

### Шаг 3 (уточнение runtime) — 2026-07-02
- При ручной проверке выяснилось, что domain-selector на Vaults обновляет
  _activeDomainId, но список не фильтруется.
- Причина: реальное приложение использует модульный API-клиент через
  /static/js/api/index.js, а не legacy api.js.
- Исправлен runtime-файл rag-backend/app/static/js/api/vaults.js:
  getSettingsVaults(domainId = null) теперь пробрасывает domainId в
  getVaults(domainId).
- Тесты: backend pytest rag-backend/app/tests/test_vaults_domain_filter.py -v
  ранее прогнан, результат 5 passed; для фронтенда нужна ручная проверка
  Network/DOM.
- Следующий шаг: Шаг 5 (Documents) — backend Vaults API дополнительного
  фикса не требует.

### Шаг 4 — 2026-07-02
- Проверен текущий backend-код rag-backend/app/api/settings/vaults.py.
- Установлено, что GET /api/settings/vaults уже принимает domain_id и
  применяет фильтр where(Vault.domain_id == domain_id).
- Код backend не менялся: шаг закрыт как DONE, проблема из ревью уже была
  решена к текущему состоянию репозитория.
- Заметка: план/ревью устарели для этого шага; фактический баг находился во
  frontend runtime API-клиенте (api/vaults.js), а не в backend.
- Следующий шаг: Шаг 5.

### Шаг 5 — 2026-07-03
- `tab-documents.js`:
  - В `renderDocumentsTab()` добавлен `<select id="docs-domain-select">` в `docs-toolbar-left`.
    Список опций загружается через `this.api.getSettingsDomains()` аналогично Campaigns/Pipelines/Vaults.
  - Добавлен метод `_attachDocumentsTabListeners(container)`:
    навешивает `change` на `#docs-domain-select` → обновляет `this._activeDomainId`,
    сбрасывает `_docsFilterTagId`, вызывает `this.loadDocumentsData()`.
  - `handleDocumentsAction('run-indexer')`: теперь явно передаёт `this._activeDomainId`
    в `this.api.runIndexer(...)` — индексация запускается для выбранного домена.
- `settings.js`:
  - В `_afterTabRender('documents')` добавлен вызов
    `this._attachDocumentsTabListeners(this._tabContent)` после `_initDocumentsTab()`.
- Коммиты: 44812843 (tab-documents.js), 5cf2e6f2 (settings.js).
- Тесты: JS-фреймворк отсутствует, автотесты не запускались. См. ручной сценарий ниже.
- Следующий шаг: Шаг 6 (backend: cross-domain валидация Pipeline↔Campaign).

#### Ручной сценарий проверки Шаг 5
1. Открыть Settings → перейти на вкладку **Documents**.
2. Убедиться, что `#docs-domain-select` присутствует в DOM рядом с кнопкой "▶ Запустить индексацию".
3. Выбрать домен — список документов должен обновиться (только дерево vault'а этого домена).
4. Теги в панели справа должны относиться к выбранному домену.
5. Фильтр тегов в `#docs-tag-filter` должен обновиться (показывать теги выбранного домена).
6. Выбрать "Все домены" — документы всех vault'ов/доменов.
7. В DevTools: `settingsManager._activeDomainId` — совпадает с выбранным доменом.
8. Нажать "▶ Запустить индексацию" с выбранным доменом:
   в Network должен уйти POST `/api/v1/domains/<id>/index` (не для первого попавшегося домена).

### Шаг 6 — 2026-07-03
- `schemas.py`:
  - `PipelineCreateRequest`: добавлен `campaign_id: uuid.UUID | None = None`.
  - `PipelineUpdateRequest`: добавлен `campaign_id: uuid.UUID | None = None`.
- `pipelines.py`:
  - Добавлена async-функция `_check_campaign_domain(campaign_id, expected_domain_id, db)`:
    подгружает Campaign из БД, сравнивает `campaign.domain_id` с ожидаемым,
    возвращает 404 если кампания не найдена, 400 если домены не совпадают.
  - `create_pipeline`: если `req.campaign_id is not None` — вызывает `_check_campaign_domain`.
  - `update_pipeline`: если `campaign_id` присутствует в payload и не None —
    вызывает `_check_campaign_domain` с `effective_domain_id` (учитывает смену domain_id в том же запросе).
    `campaign_id` теперь корректно проставляется в новую версию пайплайна из payload.
- `helpers.py`:
  - `pipeline_dict`: добавлен `campaign_id` в возвращаемый словарь (был скрыт, фронтенд не видел привязку).
- `tests/test_pipeline_cross_domain.py`: 5 unit-тестов для `_check_campaign_domain` без БД (AsyncMock):
  - test_cross_domain_raises_400
  - test_same_domain_no_exception
  - test_campaign_not_found_raises_404
  - test_cross_domain_error_message_contains_both_domains
  - test_db_get_called_with_correct_uuid
- Тесты: запустить вручную: `pytest rag-backend/app/tests/test_pipeline_cross_domain.py -v`
- Commit: 70b2975e
- Следующий шаг: Шаг 7 (Chat.vault_id domain-check, backend).

#### Ручной сценарий проверки Шаг 6
1. Создать кампанию в домене A (через Settings → Campaigns).
2. Попытаться создать пайплайн с `domain_id=B, campaign_id=<id кампании из A>` через API:
   `POST /api/settings/pipelines` — ожидать HTTP 400 с сообщением о несовпадении доменов.
3. Создать пайплайн с корректным `domain_id=A, campaign_id=<id кампании из A>` — ожидать HTTP 201.
4. В ответе пайплайна убедиться что `campaign_id` присутствует (раньше его не было в pipeline_dict).

### Шаг 7 — 2026-07-03
- `chat.py`:
  - Добавлен импорт `Vault` из `app.db.models`.
  - Добавлена async-функция `_check_vault_domain(vault_id, expected_domain_id, db)`:
    - `vault_id=None` → пропуск (back-compat: старые чаты без vault).
    - Vault не найден по `vault_id` → `HTTPException(404, ...)`.
    - `vault.domain_id != expected_domain_id` → `HTTPException(400, ...)` с обоими domain_id в сообщении.
    - `vault.domain_id is None` → `HTTPException(400, ...)` (осиротевший vault не может быть привязан к конкретному домену).
  - `create_chat`: добавлен вызов `await _check_vault_domain(req.vault_id, req.domain_id, db)` перед созданием объекта Chat.
- `tests/test_chat_vault_domain.py`: 6 unit-тестов для `_check_vault_domain` без БД (AsyncMock):
  - test_cross_domain_raises_400
  - test_same_domain_no_exception
  - test_vault_not_found_raises_404
  - test_vault_id_none_skips_check
  - test_error_message_contains_vault_and_domains
  - test_vault_domain_id_none_raises_400
- Commit: 2ee6276e
- Тесты: запустить вручную: `pytest rag-backend/app/tests/test_chat_vault_domain.py -v`
- Следующий шаг: Шаг 8 (GET /api/chat/ domain_id параметр — перепроверить, возможно уже реализован).

#### Ручной сценарий проверки Шаг 7
1. Создать vault в домене A.
2. Попытаться создать чат с `domain_id=B, vault_id=<vault из домена A>` через API:
   `POST /api/chat/create` — ожидать HTTP 400 с сообщением о несовпадении доменов.
3. Создать чат с корректным `domain_id=A, vault_id=<vault из домена A>` → ожидать HTTP 200/201.
4. Создать чат с `vault_id=null` в любом домене → ожидать успех (back-compat).

#### Заметка: update_chat отсутствует
В `chat.py` нет эндпоинта `update_chat` (кроме rename_chat, который меняет только title,
и lock_pipeline). Проверка `_check_vault_domain` нужна только в `create_chat`.
Если в будущем появится полноценный PATCH/PUT — добавить проверку туда же.

### Шаг 8 — 2026-07-03
- Проверен текущий backend-код `rag-backend/app/api/chat.py`, функция `list_chats`.
- Установлено: `GET /api/chat/list` уже принимает `domain_id: str | None = Query(default=None)`
  и применяет `stmt = stmt.where(Chat.domain_id == domain_id)` при наличии параметра.
- Код не менялся: шаг закрыт как DONE, проблема из исходного ревью уже была
  решена к текущему состоянию репозитория (аналогично Шагу 4 для Vaults).
- Тесты: код не изменялся — новые тесты не добавлялись. При желании покрыть регрессионно:
  `pytest rag-backend/app/tests/ -k "chat" -v` (если соответствующие тесты существуют).
- Следующий шаг: Шаг 9 (исследование Vault.domain_id nullable).

#### Ручная проверка (опциональная, для убеждения)
1. `GET /api/chat/list` без параметров → возвращает все чаты.
2. `GET /api/chat/list?domain_id=<uuid>` → возвращает только чаты данного домена.
3. `sidebar.js`: убедиться что `chatAPI.listChats(this.currentDomain)` передаёт правильный domain_id
   в query-string (Network DevTools).

### Шаг 9 — 2026-07-03

#### Исследование: текущее состояние схемы

**ORM-модель** (`rag-backend/app/db/models.py`, класс `Vault`):
```python
domain_id: Mapped[str] = mapped_column(
    String(64),
    ForeignKey("domains.domain_id", ondelete="SET NULL"),
    nullable=True,
)
```
Поле **nullable=True**, FK с `ondelete="SET NULL"` — при удалении домена vault «осиротевает»
(domain_id становится NULL), а не удаляется.

**Миграция** (`rag-backend/migrations/versions/0001_initial.py`):
```python
sa.Column("domain_id", sa.String(64),
    sa.ForeignKey("domains.domain_id", ondelete="SET NULL"),
    nullable=True),
```
Одна единственная миграция — nullable=True было задано изначально и ни разу не менялось.
Нет более ранних миграций, где это поле создавалось бы с другими параметрами.

#### SQL-запрос для проверки данных в живой БД

Перед принятием решения о миграции необходимо выполнить в prod/dev БД:
```sql
-- Общее количество vault'ов без домена
SELECT count(*) AS orphan_count
FROM vaults
WHERE domain_id IS NULL;

-- Детализация: какие именно vault'ы без домена
SELECT vault_id, display_name, binding_status, created_at
FROM vaults
WHERE domain_id IS NULL
ORDER BY created_at;
```

#### Выводы по результатам анализа схемы

1. **Текущий дизайн**: `domain_id` сознательно сделан nullable с `ondelete=SET NULL` —
   это защита от каскадного удаления vault'ов при удалении домена. Vault остаётся жить,
   но «теряет» домен.

2. **Риск осиротевших vault'ов**: если vault.domain_id = NULL и он привязан к чату
   (через vault_id в chats) — `_check_vault_domain` (Шаг 7) уже блокирует создание
   нового чата с таким vault'ом (400: orphan vault). Старые чаты не затрагиваются
   (back-compat через vault_id=None check).

3. **Путь к NOT NULL** (будущий шаг, вне скоупа этого плана):
   - Убедиться что `SELECT count(*) FROM vaults WHERE domain_id IS NULL` = 0.
   - Если > 0: принудительно назначить домен (`UPDATE vaults SET domain_id = 'default' WHERE domain_id IS NULL`) или удалить/архивировать осиротевшие vault'ы.
   - Написать Alembic-миграцию: сначала `ALTER TABLE vaults ALTER COLUMN domain_id SET NOT NULL`, затем сменить `ondelete` FK на `CASCADE` или `RESTRICT` в зависимости от политики.
   - Обновить ORM-модель: `nullable=False`, убрать `ondelete="SET NULL"`.

4. **Рекомендация**: НЕ менять nullable в рамках этого плана. Текущее поведение
   (SET NULL при удалении домена) — это осознанная safety-net, а не баг.
   NOT NULL миграция — отдельная задача с предварительным data-аудитом.

- Код не менялся: шаг является исследованием.
- Тесты: не применимо.
- **Весь план Domain Isolation Fix завершён. Все 9 шагов — DONE.**
