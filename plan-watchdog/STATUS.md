# Статус реализации — Vault Watchdog

> Этот файл актуализируется после каждого завершённого этапа.
> Модель, работающая над этапом, **обязана** обновить строку таблицы:
> - поставить ✅ в колонку **Статус**
> - вписать коммит/ветку в колонку **Коммит**
> - добавить строку в **Историю изменений**

## Этапы

| # | Название | Файл с деталями | Статус | Коммит | Примечания |
|---|---|---|---|---|---|
| 1 | БД: миграция platform_settings | [step-01-db-migration.md](step-01-db-migration.md) | ⬜ не начат | — | Добавить `watchdog_auto_index_extensions` в `platform_settings`. Default `.md,.pdf` |
| 2 | rag-indexer: вспомогательные методы IndexerDBClient + RedisStateManager | [step-02-indexer-support-methods.md](step-02-indexer-support-methods.md) | ⬜ не начат | — | `delete_document`, `get_setting`, `mark_file_pending`, `remove_file_from_vault_cache`, `get_vault_file_entry`, `get_all_vault_file_entries`. LanceDB-удаление покрыто существующим `StorageClient.delete_document()` |
| 3 | rag-indexer: vault_watchdog.py | [step-03-watchdog-core.md](step-03-watchdog-core.md) | ⬜ не начат | — | Scan+diff, mtime-оптимизация, логика авто/mark/delete |
| 4 | rag-indexer: интеграция watchdog в lifespan | [step-04-lifespan.md](step-04-lifespan.md) | ⬜ не начат | — | `asyncio.create_task(watchdog_loop(...))`, `WATCHDOG_INTERVAL_SEC` env |
| 5 | rag-backend: API настроек + pending-files | [step-05-backend-api.md](step-05-backend-api.md) | ⬜ не начат | — | `GET/PATCH /api/v1/settings/watchdog`; `GET /api/v1/vaults/{vault_id}/pending-files` (per-vault); `GET /api/v1/domains/{domain_id}/pending-files` (агрегированный, для баннера) |
| 6 | Фронтенд: настройки (вкладка Параметры) | [step-06-frontend-settings.md](step-06-frontend-settings.md) | ⬜ не начат | — | Секция «Индексация», чекбоксы расширений |
| 7 | Фронтенд: баннер в чате | [step-07-frontend-banner.md](step-07-frontend-banner.md) | ⬜ не начат | — | Polling `/domains/{domain_id}/pending-files` каждые 30с, баннер + кнопка запуска. ⚠️ Отклонение от CONCEPT: баннер работает на уровне домена, а не vault — vault_id берётся из `chat.domain_id` |
| 8 | Интеграционный тест | [step-08-integration-test.md](step-08-integration-test.md) | ⬜ не начат | — | Ручной сценарий: new/changed/deleted file, смена настройки |

## Статусы

- ⬜ не начат
- 🔄 в работе
- ✅ завершён
- ❌ заблокирован (причина в примечаниях)

## Зависимости между этапами

```
1 (миграция БД)
  └─► 2 (вспомогательные методы IndexerDBClient + RedisStateManager)
        └─► 3 (vault_watchdog.py — core)
               └─► 4 (lifespan интеграция)
                     └─► 8 (интеграционный тест)
1 ──────────────► 5 (rag-backend API)
                  └─► 6 (настройки UI)
                  └─► 7 (баннер в чате)
                        └─► 8
```

## Отклонения от CONCEPT

| Тема | CONCEPT | Принятое решение | Обоснование |
|---|---|---|---|
| Баннер: уровень агрегации | `GET /api/v1/vaults/pending-files` (без ID) | `GET /api/v1/domains/{domain_id}/pending-files` | Чат всегда привязан к домену; vault-агрегация без `domain_id` неприменима без авторизации |
| LanceDB delete | Новый метод `delete_chunks_by_document_id` | Используется существующий `StorageClient.delete_document()` | Метод уже присутствует в кодовой базе и покрывает задачу |

## История изменений

| Дата | Этап | Действие |
|---|---|---|
| 2026-06-21 | — | Файл создан, план утверждён |
| 2026-06-21 | план | Добавлена строка 2b (step-02-indexer-support-methods); уточнен endpoint этапа 5; зафиксировано отклонение от CONCEPT по уровню агрегации баннера |
| 2026-06-21 | план | Удалена строка 2a (step-02-lancedb-delete): LanceDB-удаление покрыто существующим StorageClient; шаги 2a/2b объединены в шаг 2 |
