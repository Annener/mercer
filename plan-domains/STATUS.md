# STATUS — Domain Isolation Fix

> Обновлять после каждого шага. Формат статуса: TODO / IN PROGRESS / DONE / BLOCKED / SKIPPED

Последнее обновление: 2026-07-02

## Сводная таблица

| # | Шаг | Статус | Дата | Заметки |
|---|---|---|---|---|
| 1 | Domain-selector Campaigns (frontend) | DONE | 2026-07-02 | Добавлен _activeDomainId в constructor, вызов _attachCampaignsTabListeners в _afterTabRender |
| 2 | Domain-selector Pipelines (frontend) | DONE | 2026-07-02 | Добавлен вызов _attachPipelinesTabListeners в _afterTabRender; shared _activeDomainId подтверждён |
| 3 | Domain-фильтр Vaults (frontend) | DONE | 2026-07-02 | domain-selector в тулбаре, _attachVaultsTabListeners, getSettingsVaults(domainId) |
| 4 | Domain_id параметр Vaults (backend) | TODO | — | — |
| 5 | Domain-selector Documents (новый UI) | TODO | — | — |
| 6 | Cross-domain валидация Pipeline↔Campaign (backend) | TODO | — | — |
| 7 | Chat.vault_id domain-check (backend) | TODO | — | — |
| 8 | GET /api/chat/ domain_id параметр | TODO | — | — |
| 9 | Исследование Vault.domain_id nullable | TODO | — | — |

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
Шаг 3 — фронтендовый. Backend-эндпоинт `GET /api/settings/vaults` сейчас принимает параметр `domain_id` или нет — не верифицировано в рамках этого шага. Шаг 4 (следующий) добавит фильтрацию на стороне бекенда — только тогда цепочка замкнется полностью.
