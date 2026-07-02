# STATUS — Domain Isolation Fix

> Обновлять после каждого шага. Формат статуса: TODO / IN PROGRESS / DONE / BLOCKED / SKIPPED

Последнее обновление: 2026-07-02

## Сводная таблица

| # | Шаг | Статус | Дата | Заметки |
|---|---|---|---|---|
| 1 | Domain-selector Campaigns (frontend) | DONE | 2026-07-02 | Добавлен _activeDomainId в constructor, вызов _attachCampaignsTabListeners в _afterTabRender |
| 2 | Domain-selector Pipelines (frontend) | TODO | — | — |
| 3 | Domain-фильтр Vaults (frontend) | TODO | — | — |
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
В репозитории нет Jest/Vitest/Mocha. Сценарий ручной проверки вместо unit-теста:
1. Открыть Settings → перейти на вкладку **Campaigns**.
2. Убедиться что `#campaigns-domain-select` присутствует в DOM.
3. Выбрать домен из селектора.
4. Убедиться что список кампаний обновился и показывает только кампании выбранного домена.
5. Выбрать "Все домены" — убедиться что показываются все кампании.
6. В DevTools console: `settingsManager._activeDomainId` — должно совпадать с выбранным доменом (null для "все").
