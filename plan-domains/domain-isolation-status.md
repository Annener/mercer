# STATUS — Domain Isolation Fix

> Обновлять после каждого шага. Формат статуса: TODO / IN PROGRESS / DONE / BLOCKED / SKIPPED

Последнее обновление: 2026-07-02

## Сводная таблица

| # | Шаг | Статус | Дата | Заметки |
|---|---|---|---|---|
| 1 | Domain-selector Campaigns (frontend) | TODO | — | — |
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
- **SKIPPED** — сознательно пропущено (например, шаг 8 может оказаться неактуальным,
  если ревью устарело)

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
