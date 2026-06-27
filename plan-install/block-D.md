# Блок D — Открытые вопросы и верификация

> Выполнять после блоков A, B, C.

---

## D1. Pydantic-схема reranker: поле `timeout_seconds`

**Вопрос:** Есть ли поле `timeout_seconds` в модели reranker?

**Файл для проверки:** `rag-backend/app/api/settings/rerank_models.py`

**Действие:**
- Если поле есть → оставить как есть в `seed_models.py`.
- Если поля нет → убрать `timeout_seconds` из `scripts/seed_models.py`.

```bash
grep -n "timeout_seconds" rag-backend/app/api/settings/rerank_models.py
```

---

## D2. Активация embedding-модели

**Вопрос:** Нужно ли вызывать `/activate` для embedding-модели, или достаточно создания записи?

**Файл для проверки:** `rag-backend/app/api/settings/emb_models.py`

**Действие:**
- Проверить наличие роута `/activate`:
  ```bash
  grep -n "activate" rag-backend/app/api/settings/emb_models.py
  ```
- Если есть `/activate` → добавить вызов в `seed_models.py` по аналогии с reranker.
- Если `/activate` нет → embedding привязывается к vault через `/bind`, создание записи достаточно.

---

## D3. Финальная проверка после всех изменений

После выполнения всех блоков — smoke test на чистом окружении:

```bash
# 1. Удалить .env
rm -f .env

# 2. Запустить setup
make setup

# 3. Проверить статус контейнеров
docker compose ps

# 4. Проверить health rag-backend
curl http://localhost:8000/health

# 5. Проверить логи на ошибки
docker compose logs --tail=50
```

**Ожидаемый результат:** все сервисы `running`, `/health` возвращает `200 OK`, ошибок в логах нет.
