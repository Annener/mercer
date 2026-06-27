# Промт для продолжения работы

> Скопируй всё ниже в новый чат и отправь первым сообщением.

---

Я работаю над проектом **Mercer** — платформой для RAG/LLM на Python/FastAPI.  
Репозиторий: **https://github.com/Annener/mercer**

---

## Структура проекта

```
mercer/
├── rag-backend/       FastAPI-бэкенд (Python, asyncpg, SQLAlchemy)
├── rag-indexer/       сервис индексации документов
├── pdf-sidecar/       хостовой сервис: embedding (порт 8765) + reranker
├── pdf-sidecar/agent/ host-agent (слушает в 9090) — запускается через launchd
├── scripts/           вспомогательные скрипты (seed_models.py уже есть)
├── plan-install/      план и контекст (этот файл)
├── Makefile
└── .env.example
```

**Основной сценарий установки на хост:**
```
git clone https://github.com/Annener/mercer
cd mercer
make setup
```

**Цель:** `make setup` должен полностью подготовить систему без ручной настройки.

---

## Что уже сделано

### 1. `scripts/seed_models.py` — готов ✓
Avтоматически создаёт embedding и reranker модели через HTTP API rag-backend при первом `make seed`.

Параметры моделей:
```python
# Embedding
{
    "model_id": "sidecar_bge_m3",
    "provider": "sidecar",
    "model_name": "BAAI/bge-m3",
    "base_url": "http://host.docker.internal:8765",
    "dimensions": 1024,
    "max_retries": 3,
    "timeout_seconds": 30,
}

# Reranker
{
    "model_id": "bge-reranker-v2-m3",
    "provider": "openai_compatible",
    "model_name": "BAAI/bge-reranker-v2-m3",
    "base_url": "http://host.docker.internal:8765",
    "api_key": "",
    "timeout_seconds": 30,
}
```

### 2. `Makefile` — обновлён ✓
Добавлены `make seed` и `make setup` (agent-setup + up + seed).  
`BACKEND_URL` переопределяемая (по умолчанию `http://localhost:8000`).

---

## Текущая задача: автоматическая подготовка `.env` при `make setup`

### Что должно произойти:

1. **`make init-env`** — если `.env` нет, скопировать `.env.example` → `.env`
2. **`make ensure-encryption-key`** — проверить `ENCRYPTION_KEY` в `.env`;
   если пустой или placeholder — сгенерировать и записать
3. Уточнить `make setup`: `init-env ensure-encryption-key agent-setup up seed`

### Ключевой факт про ENCRYPTION_KEY:

Backend (файл `rag-backend/app/services/settings_service.py`) и indexer  
(`rag-indexer/app/db_client.py`) передают ключ в `Fernet(key.encode("utf-8"))`.  
Значит, ключ должен быть **Fernet-совместимым**: urlsafe base64, 32 байта, всегда 44 символа.

Генерировать без пакета `cryptography`:
```bash
python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```
Это полный эквивалент `Fernet.generate_key()` по формату.

### Почему не `cryptography.fernet`:
Пакет `cryptography` есть внутри Docker-контейнеров, но НЕ на хосте при первом `make setup`.  
Стандартный `secrets` из stdlib работает всегда.

### `sed` кроссплатформенность (macOS vs Linux):
`sed -i` ведёт себя по-разному на macOS и Linux.  
Рекомендуемый подход: вынести логику замены в `scripts/init_env.py` (Python stdlib, портабельно):
```python
# scripts/init_env.py
import base64, secrets, re, sys, pathlib

env = pathlib.Path(".env")
if not env.exists():
    import shutil; shutil.copy(".env.example", ".env")
    print("✓ .env создан")

text = env.read_text()
# Fernet-ключ всегда ровно 44 base64-символа
need_key = not re.search(r'^ENCRYPTION_KEY=[A-Za-z0-9_=-]{44,}', text, re.M)
if need_key:
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    text = re.sub(r'^ENCRYPTION_KEY=.*', f'ENCRYPTION_KEY={key}', text, flags=re.M)
    env.write_text(text)
    print(f"✓ ENCRYPTION_KEY сгенерирован")
else:
    print("✓ ENCRYPTION_KEY уже задан, пропускаю")
```

Цели в Makefile:
```makefile
init-env:
	@python3 scripts/init_env.py
```

Обновлённый `setup`:
```makefile
setup: init-env agent-setup up seed
```

---

## Открытые вопросы, которые надо выяснить перед реализацией

1. **Формат плейсхолдера** в `.env.example`:
   Текущий: `ENCRYPTION_KEY=<generate with: ...>`.  
   Regex `[A-Za-z0-9_=-]{44,}` надёжно отсеивает плейсхолдер — проверить.

2. **`HOST_AGENT_TOKEN`** — генерировать ли автоматически?  
   Если `changeme` в продакшн — надо развернуть аналогичную логику для него.

3. **Pydantic-схемы** `/api/settings/models/rerank/`:  
   Есть ли поле `timeout_seconds` в reranker?  
   Нужно посмотреть `rag-backend/app/api/settings/`.

4. **Embedding activate**: есть ли `/activate` для embedding, или embedding-модель  
   связывается с vault отдельно.

5. **`.gitignore`**: проверить, что `scripts/*.py` не заигнорированы.

---

## Что нужно сделать сейчас

1. **Изучить** `rag-backend/app/api/settings/` — проверить Pydantic-схемы моделей
2. **Изучить** `pdf-sidecar/agent/agent.py` — как верифицируется `HOST_AGENT_TOKEN`
3. **Написать** `scripts/init_env.py` (Python stdlib, без зависимостей)
4. **Обновить** `Makefile`: добавить `init-env`, обновить `setup`
5. **Проверить** `.gitignore`
