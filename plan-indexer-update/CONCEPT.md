# Концепт: внедрение Redis в систему индексации

## Репозиторий
`Annener/mercer` — монорепо, ветка `main`.

## Текущая архитектура (до изменений)

```
rag-backend  ──HTTP──►  rag-indexer  ──HTTP──►  db-api-server
                │              │                      │
                │         JSON-файлы             PostgreSQL
                │         /app/state/             LanceDB
                └──WS proxy──► rag-indexer WS endpoint
```

- `rag-indexer` хранит прогресс задач индексации в JSON-файлах на диске (`/app/state/tasks/*.json`, `/app/state/last_successful_*.json`)
- cancel-флаги хранятся в памяти процесса (`dict[str, bool]`)
- Прогресс доставляется по WebSocket: `rag-indexer` → `rag-backend` проксирует → фронт
- `rag-backend` зависит от WS-соединения с `rag-indexer` для трансляции прогресса

## Целевая архитектура (после изменений)

```
rag-backend  ──HTTP──►  rag-indexer  ──HTTP──►  db-api-server
     │                       │                       │
     └──────── Redis ─────────┘                  PostgreSQL
                                                  LanceDB
```

- Redis — единое хранилище state задач и vault-кэша
- Прогресс: фронт делает polling `GET /index-tasks/{task_id}/state` → `rag-backend` читает из Redis напрямую
- WebSocket удаляется полностью из обоих сервисов
- `rag-backend` больше не зависит от прямого соединения с `rag-indexer` для получения прогресса

## Ключевые решения

| Решение | Обоснование |
|---|---|
| WS → HTTP polling | Упрощение, нет stateful-соединений, rag-backend не проксирует |
| JSON-файлы → Redis | Атомарность, TTL, distributed cancel, нет накопления файлов |
| `chunk_ids` удаляются из state | Рудимент — нигде не используются, удаление чанков идёт через `document_id` из PostgreSQL |
| Только новые/изменённые файлы в task state | Пропущенные файлы — только счётчик, не засоряют список прогресса |
| `vault:{vault_id}:files` без TTL | Восстанавливается из PostgreSQL + disk scan при старте rag-indexer |
| `task:{task_id}` с TTL 24ч | Задачи не хранятся вечно |
| Redis AOF + named volume | Защита task state от потери при рестарте контейнера во время индексации |
| PostgreSQL — источник правды | vault-кэш в Redis всегда можно восстановить |

## Структура данных Redis

### `task:{task_id}` — HASH, TTL 24ч
Общий статус задачи индексации.
```
status, vault_id, started_at, finished_at,
files_total, files_skipped, files_to_index, files_done, error
```

### `task:{task_id}:files` — HASH, TTL 24ч
Статус только индексируемых (новых/изменённых) файлов.
Ключ = relative_path, значение = JSON: `{stage, chunks_total, chunks_done, checksum_md5, error}`

Стадии файла: `pending → parsing → chunking → indexing → done / error / empty`

### `vault:{vault_id}:files` — HASH, без TTL
Актуальное состояние всех файлов vault'а.
Ключ = relative_path, значение = JSON: `{md5, index_status, indexed_md5, chunks_total}`

Статусы: `indexed | stale | pending | deleted`

### `cancel:{task_id}` — STRING, TTL 1ч
Флаг отмены. `SET cancel:{task_id} 1 EX 3600`

### `active_tasks` — SET, без TTL
Список активных task_id. `SADD` при старте, `SREM` при завершении.

## Сервисы и файлы затронутые изменениями

### `docker-compose.yml`
- Добавить сервис `redis` (image: redis:7-alpine, AOF, named volume)

### `shared_contracts/models.py`
- Удалить поле `chunk_ids` из `FileIndexState`

### `db-api-server`
- Добавить endpoint `GET /vaults/{vault_id}/documents/all`

### `rag-indexer` (основные изменения)
- Новый файл: `parser/state/redis_state_manager.py`
- Удалить: `parser/state/state_manager.py`
- Удалить: `app/websocket_manager.py`
- Изменить: `app/main.py` — lifespan, Redis init, rebuild vault cache при старте
- Изменить: `app/indexer_service.py` — async cancel через Redis, убрать broadcaster
- Изменить: `indexer_worker.py` — убрать chunk_ids, broadcast, переключить state
- Изменить: `requirements.txt` — добавить `redis[asyncio]`, удалить `websockets`

### `rag-backend`
- Удалить: WS-прокси endpoint
- Изменить: `main.py` — Redis client в lifespan
- Изменить: `db_management.py` (или аналог) — `get_index_task_state` читает из Redis
- Добавить: `GET /vaults/{vault_id}/index-state`
- Изменить: `requirements.txt` — добавить `redis[asyncio]`, удалить `websockets`

## Что НЕ меняется
- `db-api-server` — кроме одного нового endpoint
- `shared_contracts` — кроме удаления `chunk_ids`
- Логика чанкования, эмбеддинга, парсинга
- Логика удаления чанков (через `document_id`, не через `chunk_ids`)
- `scan_vault` — используется как есть
- PostgreSQL-схема
- LanceDB-логика

## Следующая итерация (не входит в этот план)
**VaultWatcher** — фоновый inotify/watchdog процесс, обновляющий `vault:{vault_id}:files`
в реальном времени при изменении файлов на диске между запусками индексации.
