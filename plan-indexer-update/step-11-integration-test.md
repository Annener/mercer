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

## Тест 1: Базовый запуск и polling прогресса

```bash
# Запустить индексацию (через rag-backend или rag-indexer напрямую)
TASK_ID=$(curl -s -X POST http://localhost:8001/index-tasks \
  -H "Content-Type: application/json" \
  -d '{"vault_id": "test-vault"}' | jq -r .task_id)

echo "Task ID: $TASK_ID"

# Polling прогресса
for i in $(seq 1 10); do
  curl -s http://localhost:8000/index-tasks/$TASK_ID/state | jq .status
  sleep 2
done
```

**Ожидается:**
- `status` меняется: `running` -> `done`
- `files_done` инкрементируется
- Ответ содержит `files` с прогрессом по файлам

## Тест 2: Отмена задачи

```bash
TASK_ID=$(curl -s -X POST http://localhost:8001/index-tasks \
  -H "Content-Type: application/json" \
  -d '{"vault_id": "large-vault"}' | jq -r .task_id)

sleep 3

# Отменить
curl -s -X POST http://localhost:8001/index-tasks/$TASK_ID/cancel

sleep 2

# Проверить статус
curl -s http://localhost:8000/index-tasks/$TASK_ID/state | jq .status
# Ожидается: "cancelled"
```

## Тест 3: Vault cache корректен

```bash
# После успешной индексации
curl -s http://localhost:8000/vaults/test-vault/index-state | jq .by_status
# Ожидается: {"indexed": N} или {"indexed": N, "stale": M}
```

## Тест 4: Рестарт rag-indexer не теряет активные задачи

```bash
# Запустить долгую задачу
TASK_ID=$(...)

# Через 5 секунд перезапустить indexer
docker-compose restart rag-indexer

sleep 3

# Проверить — task state должен быть в Redis
curl -s http://localhost:8000/index-tasks/$TASK_ID/state | jq .status
# Если задача не завершилась: "running" (Redis сохранил state)
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

# Проверить cancel flag
EXISTS cancel:<task_id>
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

## Критерии успешного завершения
- [ ] Polling `GET /index-tasks/{task_id}/state` возвращает корректный прогресс
- [ ] Статус меняется running -> done без ошибок
- [ ] Отмена переводит задачу в cancelled
- [ ] `GET /vaults/{vault_id}/index-state` возвращает корректные данные
- [ ] Нет WS-зависимостей в логах и коде
- [ ] `grep -r websocket rag-indexer/ rag-backend/` — пусто

## После завершения
Обнови `STATUS.md` — этап 11 -> завершён.
Задокументируй любые отклонения от плана в колонке "Примечания".
