# Этап 8 — Интеграционный тест

## Цель

Ручная проверка всей цепочки на живом `docker compose up`.
Покрывает четыре сценария: новый файл / изменённый / удалённый / смена настройки.

## Предусловия

- Этапы 1–7 завершены
- `docker compose up -d` выполнен, все сервисы `healthy`
- Наличие хотя бы одного ваулта с vault_id и файлами на диске
- Известен `WATCHDOG_INTERVAL_SEC` (до проверки удобно выставить 15)

## Сценарий 1 — Новый файл (авто-индексация)

```bash
# 1. Убедиться, что .md в auto_extensions
curl -s http://localhost:8000/api/v1/settings/watchdog | jq
# Ожидаем: {"auto_index_extensions": [".md", ".pdf"]}

# 2. Создать новый .md-файл
VAULT_PATH=/data/vaults/<vault_id>  # заменить
docker compose exec rag-indexer bash -c \
  "echo '# Test' > $VAULT_PATH/watchdog_test.md"

# 3. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд

# 4. Проверить логи watchdog
docker compose logs rag-indexer | grep watchdog
# Ожидаем: "Watchdog: started task task_id=... vault_id=..."

# 5. Проверить, что файл индексирован
curl -s http://localhost:8000/api/v1/vaults/<vault_id>/pending-files | jq
# Ожидаем: {"total": 0} (авто-индексация завершилась)
```

## Сценарий 2 — Изменённый файл

```bash
# 1. Отключить авто-индексацию для .md
curl -s -X PATCH http://localhost:8000/api/v1/settings/watchdog \
  -H 'Content-Type: application/json' \
  -d '{"auto_index_extensions": [".pdf"]}' | jq

# 2. Изменить watchdog_test.md
docker compose exec rag-indexer bash -c \
  "echo '# Changed' >> $VAULT_PATH/watchdog_test.md"

# 3. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд

# 4. Проверить pending
curl -s http://localhost:8000/api/v1/vaults/<vault_id>/pending-files | jq
# Ожидаем: {"total": 1, "pending_files": ["watchdog_test.md"]}

# 5. Вернуть .md в авто-список, запустить вручную
curl -s -X PATCH http://localhost:8000/api/v1/settings/watchdog \
  -H 'Content-Type: application/json' \
  -d '{"auto_index_extensions": [".md", ".pdf"]}' | jq
```

## Сценарий 3 — Удалённый файл

```bash
# 1. Удалить watchdog_test.md
docker compose exec rag-indexer bash -c \
  "rm $VAULT_PATH/watchdog_test.md"

# 2. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд

# 3. Проверить логи
docker compose logs rag-indexer | grep 'file deleted'
# Ожидаем: "Watchdog: file deleted vault_id=... path=watchdog_test.md"

# 4. Проверить Redis: ключ удалён
docker compose exec redis redis-cli \
  HGET vault:<vault_id>:files watchdog_test.md
# Ожидаем: (nil)

# 5. Проверить PG: документ удалён
docker compose exec postgres psql -U mercer -d mercer -c \
  "SELECT id FROM documents WHERE relative_path = 'watchdog_test.md';"
# Ожидаем: 0 rows
```

## Сценарий 4 — Смена настройки через UI

```
1. Открыть Settings → вкладка Индексация
2. Снять чекбокс .pdf, оставить только .md
3. Нажать «Сохранить» — должно появиться «Настройки сохранены»
4. curl GET /api/v1/settings/watchdog — вернуть [".md"]
5. Создать новый .pdf -> после watchdog-цикла:
   баннер должен появиться в чате (1 pending-файл)
```

## Критерий готовности

- [ ] Сценарий 1: watchdog запустил индексацию автоматически
- [ ] Сценарий 2: изменённый файл попал в `pending` (не в auto)
- [ ] Сценарий 3: удалённый файл очищен из LanceDB + PG + Redis
- [ ] Сценарий 4: смена настройки через UI отражается в баннере
- [ ] `STATUS.md` обновлён: этап 8 → ✅
