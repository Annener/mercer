# Гранулярные шаги — Domain Isolation Fix

> Каждый шаг рассчитан на отдельный чат с моделью. Не смешивать шаги.
> Перед каждым шагом — прочитать concept.md и STATUS.md.

---

## Шаг 1 — Подключить domain-selector в Campaigns

**Файлы:** `rag-backend/app/static/js/settings.js`, `rag-backend/app/static/js/settings/tab-campaigns.js`

**Проблема:** `_attachCampaignsTabListeners(container)` определён в миксине, но
никогда не вызывается. Domain-selector в тулбаре рисуется, но не работает.

**Действия:**
1. В `settings.js._afterTabRender(tab)` добавить вызов
   `this._attachCampaignsTabListeners(this._tabContent)` при `tab === 'campaigns'`.
2. Проверить, что `this._activeDomainId` инициализируется как `null` в конструкторе
   `SettingsManager` (если нет — добавить).
3. Убедиться что после смены домена в селекторе `loadTab('campaigns')` вызывается
   заново и подтягивает актуальные данные.

**Тесты (unit, JS):**
- Тест на `_attachCampaignsTabListeners`: симулировать `change` event на
  `#campaigns-domain-select`, проверить что `this._activeDomainId` обновился и
  `loadTab` был вызван с `'campaigns'`.
- Если есть фреймворк тестов (Jest/Vitest) — использовать его; если нет unit-тестов
  во фронтенде вообще, задокументировать это в STATUS.md и сделать ручной сценарий
  проверки вместо теста.

**Ручная проверка:** открыть Settings → Campaigns, переключить домен в селекторе,
убедиться что список кампаний обновился и показывает только кампании выбранного домена.

---

## Шаг 2 — Подключить domain-selector в Pipelines

**Файлы:** `rag-backend/app/static/js/settings.js`, `rag-backend/app/static/js/settings/tab-pipelines.js`

**Проблема:** аналогична Шагу 1, но для `_attachPipelinesTabListeners`.

**Действия:**
1. В `_afterTabRender(tab)` добавить вызов `this._attachPipelinesTabListeners(this._tabContent)`
   при `tab === 'pipelines'`.
2. Проверить что `_activeDomainId` общий (shared state) между Campaigns и Pipelines
   табами или раздельный — определить желаемое поведение (рекомендация: общий,
   через `this._activeDomainId` на уровне SettingsManager).

**Тесты:** аналогично Шагу 1, для `#pipelines-domain-select`.

**Ручная проверка:** Settings → Pipelines, переключить домен, проверить список.

---

## Шаг 3 — Добавить domain-фильтр в Vaults (Frontend)

**Файлы:** `rag-backend/app/static/js/api.js`, `rag-backend/app/static/js/settings/tab-vaults.js`

**Проблема:** `getSettingsVaults()` не принимает `domainId`, нет domain-selector в тулбаре.

**Действия:**
1. В `api.js` изменить `getSettingsVaults(domainId)` — добавить query-параметр
   `domain_id` если передан.
2. В `tab-vaults.js` добавить domain-selector в тулбар (аналогично Campaigns/Pipelines —
   скопировать паттерн), подключить listener сразу (не откладывать на след. шаг).
3. Обновить `renderVaultsTab()` чтобы использовать `this._activeDomainId`.

**Тесты:** unit-тест на `api.js.getSettingsVaults(domainId)` — проверить что URL
содержит `?domain_id=...` при передаче параметра и не содержит без него.

**Ручная проверка:** Settings → Vaults, переключить домен, проверить список vault'ов.

---

## Шаг 4 — Добавить domain_id параметр в backend Vaults API

**Файлы:** `rag-backend/app/api/settings/vaults.py` (уточнить точный путь по коду)

**Проблема:** эндпоинт `GET /api/settings/vaults/` не фильтрует по домену.

**Действия:**
1. Добавить query-параметр `domain_id: str | None = None` в `list_vaults`.
2. Если передан — фильтровать `.where(Vault.domain_id == domain_id)`.
3. Свериться с ORM-моделью `Vault` в `db/models.py` (там `domain_id` nullable —
   не менять это в этом шаге, только читать).

**Тесты (pytest):**
- Тест: создать 2 vault'а в разных доменах, вызвать эндпоинт с `domain_id=A`,
  убедиться что вернулся только vault домена A.
- Тест: вызов без `domain_id` — возвращает все vaults (обратная совместимость).

**Прогон тестов:** выполнить `pytest` в контейнере/окружении rag-backend после изменений.

---

## Шаг 5 — Добавить domain-selector в Documents (новый UI)

**Файлы:** `rag-backend/app/static/js/settings/tab-documents.js`, `rag-backend/app/static/js/settings.js`

**Проблема:** в Documents нет domain-selector вообще — домен резолвится автоматически
через `_resolveDomainId()` (берёт первый включённый домен), что не позволяет
пользователю выбрать нужный домен вручную.

**Действия:**
1. В `renderDocumentsTab()` добавить HTML domain-selector в `docs-toolbar-left`
   (по аналогии с Campaigns/Pipelines: `<select id="docs-domain-select">`).
2. Список опций — загрузить через `this.api.getSettingsDomains()`.
3. Добавить обработчик `change` → обновляет `this._activeDomainId`, вызывает
   `this.loadDocumentsData()`.
4. Подключить listener в `settings.js._afterTabRender` или в `_initDocumentsTab()`.
5. Убедиться, что `_resolveVaultId()` и `_resolveDomainId()` больше не единственный
   источник домена — приоритет у явного выбора пользователя.

**Тесты:**
- Unit-тест на обработчик смены домена в Documents (аналогично Campaigns).
- Тест на `loadDocumentsData()` — что `domainId` из `_activeDomainId` передаётся
  в `getSettingsDocuments()`.

**Ручная проверка:** Settings → Documents, переключить домен, убедиться что список
документов и теги в панели справа изменились.

---

## Шаг 6 — Backend: cross-domain валидация Pipeline ↔ Campaign

**Файлы:** `rag-backend/app/api/settings/pipelines.py`

**Проблема:** `create_pipeline` и `update_pipeline` не проверяют, что
`campaign.domain_id == pipeline.domain_id`, если `campaign_id` передан.

**Действия:**
1. В `create_pipeline`: если `req.campaign_id` передан — подгрузить `Campaign`,
   проверить `campaign.domain_id == req.domain_id`, иначе `HTTPException(400, ...)`.
2. В `update_pipeline`: аналогичная проверка, если `campaign_id` присутствует
   в `payload`.

**Тесты (pytest):**
- Тест: создать campaign в домене A, попытаться создать pipeline с
  `domain_id=B, campaign_id=<campaign из A>` → ожидать 400.
- Тест: создать pipeline с корректным соответствием domain_id/campaign_id → 201.

**Прогон:** `pytest` в rag-backend окружении.

---

## Шаг 7 (средний приоритет) — Chat.vault_id domain-check

**Файлы:** `rag-backend/app/api/chat.py` (или сервисный слой создания чата), `db/models.py` (только чтение)

**Проблема:** при создании/обновлении чата нет проверки что `vault_id` принадлежит
тому же домену что и `chat.domain_id`.

**Действия:**
1. Найти место создания/обновления Chat (`create_chat` / `update_chat`).
2. Если `vault_id` передан — подгрузить Vault, проверить `vault.domain_id == chat.domain_id`.
3. При несовпадении — `HTTPException(400, "Vault belongs to a different domain")`.

**Тесты (pytest):**
- Тест: создать vault в домене A, попытаться создать чат в домене B с этим vault_id → 400.
- Тест: корректное соответствие → успех.

---

## Шаг 8 — GET /api/chat/ добавить domain_id параметр

**Файлы:** `rag-backend/app/api/chat.py`

**Проблема:** согласно ревью — эндпоинт списка чатов не принимает `domain_id` вообще
(хотя sidebar.js уже вызывает `chatAPI.listChats(this.currentDomain)` — нужно
перепроверить реальный код эндпоинта, возможно параметр уже есть и ревью устарело).

**Действия:**
1. Открыть `chat.py`, найти `list_chats` / аналог, проверить сигнатуру.
2. Если `domain_id` отсутствует — добавить `domain_id: str | None = None` и фильтр.
3. Если уже есть — зафиксировать это в STATUS.md как "уже ок, ревью устарело" и
   закрыть шаг без изменений кода.

**Тесты (pytest):** аналогично Шагу 4, для чатов.

---

## Шаг 9 (низкий приоритет) — Исследование Vault.domain_id nullable

**Файлы:** нет изменений кода, только SQL-исследование + отдельный документ-вывод.

**Действия:**
1. Выполнить SQL: `SELECT count(*) FROM vaults WHERE domain_id IS NULL;`
2. Если 0 — можно безопасно писать миграцию на NOT NULL (отдельный будущий шаг,
   не в рамках этого плана, т.к. требует Alembic migration + review).
3. Если > 0 — задокументировать какие vaults без домена и решить что с ними делать
   (архивировать / удалить / принудительно назначить домен).
4. Результат зафиксировать в STATUS.md, миграцию НЕ писать в этом шаге.

**Тест:** не применимо (это исследование, не код).

---

## Явно НЕ в скоупе (напоминание)

Не трогать: `tab-params.js`, `tab-models.js`, `tab-gen-models.js`, `tab-emb-models.js`,
`tab-rerank-models.js`, `tab-domains.js` (кроме использования как источника списка
доменов для селекторов в других шагах).
