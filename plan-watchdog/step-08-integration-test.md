# Этап 8 — Интеграционный тест

## Цель

Ручная проверка всей цепочки на живом `docker compose up`.
Покрывает четыре сценария: новый файл / изменённый / удалённый / смена настройки.

## Предусловия

- Этапы 1–7 завершены
- `docker compose up -d` выполнен, все сервисы `healthy`
- Наличие хотя бы одного ваулта с `vault_id` и файлами на диске
- Известен `WATCHDOG_INTERVAL_SEC` (до проверки удобно выставить 15)
- Известны `VAULT_ID` и `DOMAIN_ID` — подставить в команды ниже

```bash
VAULT_ID="<vault_id>"    # заменить
DOMAIN_ID="<domain_id>"  # заменить
INTERVAL=15              # значение WATCHDOG_INTERVAL_SEC
```

## Сценарий 1 — Новый файл (авто-индексация)

```bash
# 1. Убедиться, что .md в auto_extensions
curl -s http://localhost:8000/api/v1/settings/watchdog | jq
# Ожидаем: {"auto_index_extensions": [".md", ".pdf"]}

# 2. Создать новый .md-файл
docker compose exec rag-indexer bash -c \
  "echo '# Test' > /data/vaults/${VAULT_ID}/watchdog_test.md"

# 3. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд
sleep $((INTERVAL + 5))

# 4. Проверить логи watchdog
docker compose logs rag-indexer | grep watchdog
# Ожидаем: "Watchdog: started task task_id=... vault_id=..."

# 5a. Проверить per-vault Redis (точечная проверка кэша)
curl -s "http://localhost:8000/api/v1/vaults/${VAULT_ID}/pending-files" | jq
# Ожидаем: {"total": 0} — авто-индексация завершилась

# 5b. Проверить доменный endpoint (то, что видит баннер в чате)
curl -s "http://localhost:8000/api/v1/domains/${DOMAIN_ID}/pending-files" | jq
# Ожидаем: {"total_pending": 0, ...}
```

## Сценарий 2 — Изменённый файл + ручной запуск индексации

```bash
# 1. Отключить авто-индексацию для .md
curl -s -X PATCH http://localhost:8000/api/v1/settings/watchdog \
  -H 'Content-Type: application/json' \
  -d '{"auto_index_extensions": [".pdf"]}' | jq

# 2. Изменить watchdog_test.md
docker compose exec rag-indexer bash -c \
  "echo '# Changed' >> /data/vaults/${VAULT_ID}/watchdog_test.md"

# 3. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд
sleep $((INTERVAL + 5))

# 4. Проверить pending — файл должен быть в статусе pending
curl -s "http://localhost:8000/api/v1/vaults/${VAULT_ID}/pending-files" | jq
# Ожидаем: {"total": 1, "pending_files": ["watchdog_test.md"]}

curl -s "http://localhost:8000/api/v1/domains/${DOMAIN_ID}/pending-files" | jq
# Ожидаем: {"total_pending": 1, ...}

# 5. Симулировать нажатие кнопки «Запустить индексацию» из баннера
curl -s -X POST "http://localhost:8000/api/v1/domains/${DOMAIN_ID}/index" | jq
# Ожидаем: {"queued": 1}

# 6. Подождать завершения задачи (indexer обрабатывает асинхронно)
sleep $((INTERVAL + 5))

# 7. Проверить, что pending очищен
curl -s "http://localhost:8000/api/v1/domains/${DOMAIN_ID}/pending-files" | jq
# Ожидаем: {"total_pending": 0}

# 8. Вернуть .md в авто-список
curl -s -X PATCH http://localhost:8000/api/v1/settings/watchdog \
  -H 'Content-Type: application/json' \
  -d '{"auto_index_extensions": [".md", ".pdf"]}' | jq
```

## Сценарий 3 — Удалённый файл

```bash
# 1. Удалить watchdog_test.md
docker compose exec rag-indexer bash -c \
  "rm /data/vaults/${VAULT_ID}/watchdog_test.md"

# 2. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд
sleep $((INTERVAL + 5))

# 3. Проверить логи
docker compose logs rag-indexer | grep 'file deleted'
# Ожидаем: "Watchdog: file deleted vault_id=... path=watchdog_test.md"

# 4. Проверить Redis: ключ удалён
docker compose exec redis redis-cli \
  HGET "vault:${VAULT_ID}:files" watchdog_test.md
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
4. Проверить через curl:
```

```bash
curl -s http://localhost:8000/api/v1/settings/watchdog | jq
# Ожидаем: {"auto_index_extensions": [".md"]}
```

```
5. Создать новый .pdf-файл:
```

```bash
docker compose exec rag-indexer bash -c \
  "cp /dev/null /data/vaults/${VAULT_ID}/test_doc.pdf"
```

```
6. Подождать WATCHDOG_INTERVAL_SEC + 5 секунд:
```

```bash
sleep $((INTERVAL + 5))
```

```
7. Проверить доменный pending — баннер должен появиться:
```

```bash
curl -s "http://localhost:8000/api/v1/domains/${DOMAIN_ID}/pending-files" | jq
# Ожидаем: {"total_pending": 1, ...}
```

```
8. Открыть чат с этим доменом — убедиться, что баннер виден в UI.
9. Нажать «Запустить индексацию» в баннере, убедиться что баннер исчезает.
```

## Критерий готовности

- [ ] Сценарий 1: watchdog запустил индексацию автоматически, `total_pending = 0`
- [ ] Сценарий 2: изменённый файл попал в `pending`; `POST /index` очистил его после ожидания
- [ ] Сценарий 3: удалённый файл очищен из LanceDB + PG + Redis
- [ ] Сценарий 4: смена настройки через UI отражается в баннере чата
- [ ] `STATUS.md` обновлён: этап 8 → ✅
