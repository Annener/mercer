# Этап 11: Интеграционный тест

## Цель
Убедиться что полная цепочка работает: запуск индексации → прогресс доступен
через polling → отмена работает → vault cache корректен после завершения.

## Перед тестом

1. Собери все образы:
```bash
docker-compose build rag-indexer rag-backend
```

2. Подними стек:
```bash
docker-compose up -d
```

3. Проверь Redis:
```bash
docker-compose exec redis redis-cli ping
# PONG
```

4. Убедись что тестовый vault существует и содержит файлы:
```bash
docker-compose exec rag-indexer ls /data/vaults/
# Должен быть хотя бы один vault с PDF-файлами внутри
```

## Тест 1: Базовый запуск и polling прогресса

```bash
# Запустить индексацию (порты уточни из docker-compose.yml)
# rag-indexer обычно слушает на 8001, rag-backend на 8000
TASK_ID=$(curl -s -X POST http://localhost:8001/index-tasks \
  -H "Content-Type: application/json" \
  -d '{"vault_id": "<VAULT_ID>"}' | jq -r .task_id)

echo "Task ID: $TASK_ID"

# Polling прогресса через rag-backend
for i in $(seq 1 10); do
  curl -s http://localhost:8000/index-tasks/$TASK_ID/state | jq '{status, files_done, files_total}'
  sleep 2
done
```

**Ожидается:**
- `status` меняется: `running` → `done`
- `files_done` инкрементируется
- Ответ содержит `files` с прогрессом по файлам

## Тест 2: Отмена задачи

```bash
TASK_ID=$(curl -s -X POST http://localhost:8001/index-tasks \
  -H "Content-Type: application/json" \
  -d '{"vault_id": "<VAULT_ID_С_БОЛЬШИМ_ЧИСЛОМ_ФАЙЛОВ>"}' | jq -r .task_id)

sleep 3

# Отменить
curl -s -X POST http://localhost:8001/index-tasks/$TASK_ID/cancel

sleep 2

# Проверить статус через rag-backend
curl -s http://localhost:8000/index-tasks/$TASK_ID/state | jq .status
# Ожидается: "cancelled"
```

## Тест 3: Vault cache корректен

```bash
# После успешной индексации
curl -s http://localhost:8000/vaults/<VAULT_ID>/index-state | jq .by_status
# Ожидается: {"indexed": N} или {"indexed": N, "stale": M}
```

## Тест 4: Рестарт rag-indexer не теряет task state из Redis

```bash
# Запустить задачу на vault с большим числом файлов
TASK_ID=$(curl -s -X POST http://localhost:8001/index-tasks \
  -H "Content-Type: application/json" \
  -d '{"vault_id": "<VAULT_ID>"}' | jq -r .task_id)

# Через 5 секунд перезапустить indexer
sleep 5
docker-compose restart rag-indexer

sleep 5

# Проверить — task state должен быть в Redis (AOF сохранил)
curl -s http://localhost:8000/index-tasks/$TASK_ID/state | jq .status
# Если задача не завершилась: статус сохранён ("running" или "done")
# Если завершилась до рестарта: "done"
```

## Тест 5: Redis key inspection

```bash
docker-compose exec redis redis-cli

# Посмотреть ключи
KEYS *

# Проверить task state
HGETALL task:<task_id>

# Проверить vault cache
HLEN vault:<vault_id>:files

# Проверить отсутствие TTL у vault cache
TTL vault:<vault_id>:files
# Ожидается: -1 (нет TTL)

# Проверить TTL у task
TTL task:<task_id>
# Ожидается: ~86400 (24 часа)
```

## Что проверить в логах

```bash
docker-compose logs rag-indexer --follow
```

Ожидаемые строки при старте:
```
INFO - Vault cache rebuilt: vault_id=..., files=N
INFO - Redis connected
```

Отсутствие строк вида:
```
WebSocket
broadcast
ConnectionManager
```

## Критерии успешного завершения
- [ ] Polling `GET /index-tasks/{task_id}/state` возвращает корректный прогресс
- [ ] Статус меняется `running` → `done` без ошибок
- [ ] Отмена переводит задачу в `cancelled`
- [ ] `GET /vaults/{vault_id}/index-state` возвращает корректные данные
- [ ] `TTL vault:{vault_id}:files` = -1 (нет TTL)
- [ ] `TTL task:{task_id}` ≈ 86400
- [ ] Нет WS-зависимостей в логах и коде
- [ ] `grep -r websocket rag-indexer/ rag-backend/` — пусто

## После завершения
Обнови `STATUS.md` — строку этапа 11: поставь ✅, запиши коммит, добавь в историю.  
Задокументируй любые отклонения от плана в колонке "Примечания".
