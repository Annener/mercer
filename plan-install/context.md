# plan-install: Контекст задачи

## Что уже сделано

### `scripts/seed_models.py` (добавлен в main)

Скрипт на Python stdlib (без внешних зависимостей), который:
- ждёт доступности `rag-backend` (`/health`, 15 ретраев по 2 сек)
- `POST /api/settings/models/embedding/` — создаёт embedding-модель
- `POST /api/settings/models/rerank/` — создаёт reranker-модель
- `POST /api/settings/models/rerank/{id}/activate` — активирует reranker
- идемпотентен: HTTP 409/422 молча пропускается

**Параметры моделей по умолчанию:**
```python
EMBEDDING_MODEL = {
    "model_id": "sidecar_bge_m3",
    "provider": "sidecar",
    "model_name": "BAAI/bge-m3",
    "base_url": "http://host.docker.internal:8765",
    "dimensions": 1024,
    "max_retries": 3,
    "timeout_seconds": 30,
}

RERANK_MODEL = {
    "model_id": "bge-reranker-v2-m3",
    "provider": "openai_compatible",
    "model_name": "BAAI/bge-reranker-v2-m3",
    "base_url": "http://host.docker.internal:8765",
    "api_key": "",
    "timeout_seconds": 30,
}
```

### `Makefile` (обновлён)

Добавлено:
- `BACKEND_URL = http://localhost:8000` — переменная, переопределяемая из CLI
- `make seed` — запускает `scripts/seed_models.py --base-url $(BACKEND_URL)`
- `make setup` — составная цель: `agent-setup up seed`

---

## Следующий шаг: подготовка .env при `make setup`

### Задача

При первом запуске `make setup` на чистом хосте:
1. Скопировать `.env.example` → `.env` (если `.env` не существует)
2. Сгенерировать `ENCRYPTION_KEY` и подставить в `.env` (если значение пустое/placeholder)

### Ключевой факт: формат ENCRYPTION_KEY

Backend и rag-indexer передают ключ напрямую в `Fernet(encryption_key.encode("utf-8"))`.  
Это значит ключ **обязан** быть Fernet-совместимым:
- urlsafe base64
- декодируется в ровно 32 байта
- пример: `dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBtZXJjZXI=`

Файлы, подтверждающие это:
- `rag-backend/app/services/settings_service.py` → `Fernet(key.encode("utf-8"))`
- `rag-indexer/app/db_client.py` → `Fernet(encryption_key.encode("utf-8"))`

### Почему не `cryptography`

Пакет `cryptography` не входит в стандартную библиотеку Python.  
Он будет в venv внутри Docker-контейнеров, но **не** на хосте при первом `make setup`.  
Поэтому генерировать ключ нужно через stdlib:

```bash
python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Это математически эквивалентно `Fernet.generate_key()` по формату.

---

## Что нужно реализовать

### Новые Makefile-цели

```
init-env             — cp .env.example .env, если .env нет
ensure-encryption-key — заменить placeholder в ENCRYPTION_KEY на сгенерированный ключ
```

### Обновить `make setup`

```makefile
setup: init-env ensure-encryption-key agent-setup up seed
```

### Логика `ensure-encryption-key`

Три состояния в `.env`:
1. `ENCRYPTION_KEY=<generate with: ...>` — placeholder из .env.example → заменить
2. `ENCRYPTION_KEY=` — пустое → заменить
3. `ENCRYPTION_KEY=dGhpcyBp...` — уже заполнено → пропустить, не перезатирать

GREP-паттерн для «ключ не заполнен»:
```bash
grep -q '^ENCRYPTION_KEY=\(<\|$\)' .env
```

Замена через `sed -i`:
```bash
sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$KEY|" .env && rm -f .env.bak
```

> ⚠️ На macOS `sed -i` требует аргумент суффикса (`.bak`), на Linux — нет.
> Нужно учесть кроссплатформенность или добавить ветку по `uname`.

---

## Открытые вопросы для проверки перед реализацией

### 1. Формат ENCRYPTION_KEY в `.env.example`
**Вопрос:** Текущий placeholder — `<generate with: ...>`. Какой именно паттерн использовать
для grep, чтобы надёжно распознать «ключ не задан»?
- Вариант A: `grep -q '^ENCRYPTION_KEY=<'` — матчит только placeholder
- Вариант B: `grep -q '^ENCRYPTION_KEY=\S'` — матчит «любое непустое значение» (инверсия)
- Вариант C: проверять длину — валидный Fernet-ключ всегда 44 символа

**Рекомендация:** Вариант C — самый надёжный. Если значение после `=` не равно 44 символам, генерировать.

### 2. `sed -i` кроссплатформенность
**Вопрос:** Целевая ОС только macOS или тоже Linux?
- macOS: `sed -i '' "s|...|...|"` (пустой суффикс через пробел)
- Linux: `sed -i "s|...|...|"` (без суффикса)

Текущий Makefile содержит `_check-macos`, что говорит об ориентации на macOS,  
но `make up` и `make seed` не имеют такого ограничения.

**Решение:** Использовать Python-скрипт вместо sed — портабельно, читаемо, без сюрпризов.

### 3. Есть ли уже папка `scripts/` в `.gitignore`?
**Вопрос:** Нужно убедиться, что `scripts/seed_models.py` попал в git.  
Проверить `.gitignore` — нет ли там `scripts/` или `*.py` в корне.

Текущий `.gitignore` репозитория не изучался — **нужно проверить**.

### 4. Нужен ли `HOST_AGENT_TOKEN` в `.env`?
**Вопрос:** В `.env.example` есть `HOST_AGENT_TOKEN=changeme`.  
Если токен используется как секрет при связи docker ↔ host-agent, его тоже нужно  
генерировать автоматически (аналогично ENCRYPTION_KEY).

Если значение `changeme` оставляется по умолчанию — это security-риск на реальном деплое.  
**Нужно выяснить**: как `HOST_AGENT_TOKEN` используется в `host-agent/agent.py`.

### 5. API-эндпоинты embedding/rerank: точные схемы
**Вопрос:** Достоверно ли известны поля для `POST /api/settings/models/embedding/`
и `POST /api/settings/models/rerank/`?

Параметры `timeout_seconds` для reranker взяты по аналогии с embedding, но нужно
проверить Pydantic-схемы в `rag-backend/app/api/settings/emb_models.py`
и `rerank_models.py` — вдруг `timeout_seconds` у reranker не поддерживается.

### 6. Активация embedding-модели
**Вопрос:** API для embedding имеет ли `/activate` эндпоинт?  
Для reranker он есть (`POST /api/settings/models/rerank/{id}/activate`).  
Судя по `api_routes.md`, у embedding нет эндпоинта activate.  
Но нужно уточнить: как embedding-модель «привязывается» к vault — через `/bind` на vault'е?  
Если да, seed-скрипт embedding не активирует, а просто создаёт запись — и это корректно.

---

## Итоговый целевой флоу

```
git clone https://github.com/Annener/mercer
cd mercer
make setup

# Внутри make setup:
# 1. init-env            → cp .env.example .env (если нет .env)
# 2. ensure-encryption-key → генерируем ENCRYPTION_KEY через stdlib, пишем в .env
# 3. agent-setup         → venv + launchd для pdf-sidecar host-agent
# 4. up                  → docker compose up -d
# 5. seed                → создаём embedding + reranker в backend API
```

После `make setup` пользователь заходит в UI (`http://localhost:8000`),
и модели embedding/reranker уже сконфигурированы. Остаётся только:
- добавить генерационную модель (LLM) — её API-ключ уникален для пользователя
- создать vault, настроить домены
