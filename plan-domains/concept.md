# Концепт: Domain Isolation Fix — Mercer

> Источник: plan-domains/domain-isolation-review.md
> Дата создания: 2026-07-02

## Проблема

Mercer — мульти-доменная RAG-платформа. Домен (`domain_id`) — это изолированный
контекст (например "D&D" и "Работа"), у которого свои документы, теги, кампании
и пайплайны. Изоляция домена задумана в архитектуре, но не соблюдается полностью
на уровне API и фронтенда.

## Что ВХОДИТ в скоуп (домен-зависимые сущности)

- **Campaigns** (кампании) — привязаны к domain_id
- **Pipelines** (пайплайны) — привязаны к domain_id
- **Vaults** (хранилища документов) — привязаны к domain_id (nullable — под вопросом)
- **Documents** (документы) — принадлежат vault → домену
- **Tags** (теги) — привязаны к domain_id
- **Chats** (чаты) — привязаны к domain_id

## Что НЕ входит в скоуп (домен-независимые сущности)

- **Params** (общие параметры системы) — глобальные, домен не при чём
- **Models** (gen-models, emb-models, rerank-models) — глобальные модели, домен не при чём
- **Domains** (сама вкладка управления доменами) — не трогаем логику, кроме как источник списка доменов для селекторов

Важно: НЕ добавлять domain-selector/фильтр на страницы Params и Models — это
архитектурно неверно, они не принадлежат ни одному домену.

## Текущее состояние по каждой сущности (по факту ревью кода)

| Сущность | UI Selector есть? | Подключён (listener)? | API принимает domain_id? | Backend валидирует cross-domain? |
|---|---|---|---|---|
| Campaigns | Да (в тулбаре tab-campaigns.js) | НЕТ — `_attachCampaignsTabListeners` не вызывается | Да | Да (link_global_tag проверяет domain) |
| Pipelines | Да (в тулбаре tab-pipelines.js) | НЕТ — `_attachPipelinesTabListeners` не вызывается | Да | НЕТ — create_pipeline не проверяет campaign.domain_id == pipeline.domain_id |
| Vaults | НЕТ | — | НЕТ — getSettingsVaults() без параметров | — |
| Documents | НЕТ (авторезолв через _resolveDomainId) | — | Да, но выбор домена скрыт от юзера | — |
| Chats (sidebar, не settings) | Да, работает штатно | Да | Да | Да |

## Корневая причина

`SettingsManager` (settings.js) не имеет понятия "текущий домен" вообще.
Табы campaigns/pipelines сами хранят `this._activeDomainId`, рисуют
domain-selector в своём HTML, но обработчик `change` на этом селекторе
(`_attachCampaignsTabListeners` / `_attachPipelinesTabListeners`) никогда не
вызывается, потому что `settings.js._afterTabRender()` не знает о его
существовании — вызывает только `_initDocumentsTab()` и `_loadSidecarStatus()`.

## Цель работы

1. Подключить существующие domain-selector'ы в Campaigns/Pipelines (малый фикс).
2. Добавить domain-фильтр в Vaults (селектор + API-параметр).
3. Добавить domain-selector в Documents (новый UI-элемement, т.к. его никогда не было).
4. Защитить backend от cross-domain ошибок (pipeline.campaign_id vs domain_id).
5. Опционально (низкий приоритет): миграция Vault.domain_id → NOT NULL, если данные позволяют.

## Принцип проверки на каждом шаге

Перед началом любого шага — свериться с этим концептом: относится ли
затрагиваемая сущность к domain-scope. Если нет (Params, Models) — шаг не нужен,
даже если кажется что "для консистентности неплохо бы".

После каждого шага — юнит-тест (где возможно) + ручная проверка логики
(переключение домена реально меняет выдачу).
