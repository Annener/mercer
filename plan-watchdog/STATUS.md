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
| 2 | rag-indexer: LanceDB delete + db_client методы | [step-02-lancedb-delete.md](step-02-lancedb-delete.md) | ⬜ не начат | — | `delete_chunks_by_document_id`, `delete_document`, `remove_file_from_vault_cache`, `get_setting` |
| 3 | rag-indexer: vault_watchdog.py | [step-03-watchdog-core.md](step-03-watchdog-core.md) | ⬜ не начат | — | Scan+diff, mtime-оптимизация, логика авто/mark/delete |
| 4 | rag-indexer: интеграция watchdog в lifespan | [step-04-lifespan.md](step-04-lifespan.md) | ⬜ не начат | — | `asyncio.create_task(watchdog_loop(...))`, `WATCHDOG_INTERVAL_SEC` env |
| 5 | rag-backend: API настроек + pending-files | [step-05-backend-api.md](step-05-backend-api.md) | ⬜ не начат | — | `GET/PATCH /api/v1/settings/watchdog`, `GET /api/v1/vaults/pending-files` |
| 6 | Фронтенд: настройки (вкладка Параметры) | [step-06-frontend-settings.md](step-06-frontend-settings.md) | ⬜ не начат | — | Секция «Индексация», чекбоксы расширений |
| 7 | Фронтенд: баннер в чате | [step-07-frontend-banner.md](step-07-frontend-banner.md) | ⬜ не начат | — | Polling `/pending-files` каждые 30с, баннер + кнопка запуска |
| 8 | Интеграционный тест | [step-08-integration-test.md](step-08-integration-test.md) | ⬜ не начат | — | Ручной сценарий: new/changed/deleted file, смена настройки |

## Статусы

- ⬜ не начат
- 🔄 в работе
- ✅ завершён
- ❌ заблокирован (причина в примечаниях)

## Зависимости между этапами

```
1 (миграция БД)
  └─► 2 (db_client методы + LanceDB delete)
        └─► 3 (vault_watchdog.py — core)
              └─► 4 (lifespan интеграция)
                    └─► 8 (интеграционный тест)
1 ──────────────────► 5 (rag-backend API)
                        └─► 6 (настройки UI)
                        └─► 7 (баннер в чате)
                              └─► 8
```

## История изменений

| Дата | Этап | Действие |
|---|---|---|
| 2026-06-21 | — | Файл создан, план утверждён |
