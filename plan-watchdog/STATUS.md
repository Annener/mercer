# Статус реализации — Vault Watchdog

> Этот файл актуализируется после каждого завершённого этапа.
> Модель, работающая над этапом, **обязана** обновить строку таблицы:
> - поставить ✅ в колонку **Статус**
> - вписать коммит/ветку в колонку **Коммит**
> - добавить строку в раздел «История изменений»:
> text
> | {дата} | {этап №} | Реализация: {краткое описание что создано/изменено} |

## Этапы

| # | Название | Файл с деталями | Статус | Коммит | Примечания |
|---|---|---|---|---|---|
| 1 | БД: миграция platform_settings | [step-01-db-migration.md](step-01-db-migration.md) | ✅ завершён | c79fad31968d100645c37d94a92a097b0ef28ca7 | Добавить `watchdog_auto_index_extensions` в `platform_settings`. Default `.md,.pdf` |
| 2 | rag-indexer: вспомогательные методы IndexerDBClient + RedisStateManager | [step-02-indexer-support-methods.md](step-02-indexer-support-methods.md) | ✅ завершён | a633cfb9b339b73e96f0748a7031476e4c40f3f5 | `delete_document`, `get_setting`, `mark_file_pending`, `remove_file_from_vault_cache`, `get_vault_file_entry`, `get_all_vault_file_entries`. LanceDB-удаление покрыто существующим `StorageClient.delete_document()` |
| 3 | rag-indexer: vault_watchdog.py | [step-03-watchdog-core.md](step-03-watchdog-core.md) | ✅ завершён | c25209bf20c81d518c9d27921f0fa5254797741c | `watchdog_loop`, `_run_once`, `_process_vault`, `_handle_deleted`; `is_vault_indexing` в RedisStateManager; 6 unit-тестов |
| 4 | rag-indexer: интеграция watchdog в lifespan | [step-04-lifespan.md](step-04-lifespan.md) | ✅ завершён | 815545b3343c89165b6e8a30c970edffd54da681 | `main.py`: `+watchdog_loop`, `+StorageClient`, `+watchdog_task`; `docker-compose.yml`: `+WATCHDOG_INTERVAL_SEC`; `.env.example`: `+WATCHDOG_INTERVAL_SEC`; 2 unit-теста |
| 5 | rag-backend: API настроек + pending-files | [step-05-backend-api.md](step-05-backend-api.md) | ✅ завершён | 815545b3343c89165b6e8a30c970edffd54da681 | `watchdog_settings.py`: 5 эндпоинтов (GET/PATCH settings, per-vault + domain pending-files, domain index); `main.py`: `+watchdog_router`; 6 unit-тестов |
| 6 | Фронтенд: настройки (вкладка Параметры) | [step-06-frontend-settings.md](step-06-frontend-settings.md) | ✅ завершён | 936dc3b7f2cbf1bba7ebff2b4af732b0d9971bac | `tab-indexing.js` создан; `settings.js`: `case 'indexing'` в `loadTab()` и `_dispatch()`; `index.html`: кнопка вкладки + `<script>` тег; `api.js`: `getWatchdogSettings` + `saveWatchdogSettings` |
| 7 | Фронтенд: баннер в чате | [step-07-frontend-banner.md](step-07-frontend-banner.md) | ✅ завершён | eaff3bc8cfb342d53e115c518c52d1f751f580c3 | `pending-banner.js` создан (класс `PendingFilesBanner`); `.pending-banner` стили добавлены в `chat-area.css`; интеграция в `chat.js` и `index.html` уже присутствовала |
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
| 2026-06-22 | Этап 1 | Реализация: создан `0020_add_watchdog_setting.py` — миграция добавляет `watchdog_auto_index_extensions` в `platform_settings` |
| 2026-06-22 | Этап 2 | Реализация: добавлены `IndexerDBClient.delete_document` + `get_setting`; `RedisStateManager.mark_file_pending` + `remove_file_from_vault_cache` + `get_vault_file_entry` + `get_all_vault_file_entries`; unit-тесты |
| 2026-06-22 | Этап 3 | Реализация: создан `parser/watchdog/vault_watchdog.py` (все 4 функции); добавлен `RedisStateManager.is_vault_indexing`; создан `parser/watchdog/__init__.py`; 6 unit-тестов |
| 2026-06-22 | Этап 4 | Реализация: `main.py` — добавлены импорты `watchdog_loop`/`StorageClient`, `watchdog_task` в lifespan, отмена в finally; `docker-compose.yml` + `.env.example`: `+WATCHDOG_INTERVAL_SEC`; 2 unit-теста |
| 2026-06-22 | Этап 5 | Реализация: создан `watchdog_settings.py` (5 эндпоинтов: GET/PATCH settings, GET per-vault pending-files, GET domain pending-files, POST domain index); `main.py`: `+watchdog_router`; 6 unit-тестов |
| 2026-06-22 | Этап 6 | Реализация: создан `tab-indexing.js` (IndexingTabMixin: renderIndexingTab + handleIndexingAction); все интеграционные точки уже присутствовали (api.js, settings.js, index.html) |
| 2026-06-22 | Этап 7 | Реализация: создан `pending-banner.js` (класс PendingFilesBanner: polling, show/hide, triggerIndex, склонение); добавлены стили `.pending-banner` в `chat-area.css`; интеграция в `chat.js` и `index.html` уже присутствовала |
