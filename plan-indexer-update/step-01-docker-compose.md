# Этап 1: Инфраструктура — Redis в docker-compose

## Цель
Добавить Redis-контейнер в `docker-compose.yml`. После этого этапа Redis доступен
внутри docker-сети для `rag-indexer` и `rag-backend`.

## Файлы для изменения
- `docker-compose.yml` (корень репозитория)

## Перед началом — прочитай текущий файл
Прочитай `docker-compose.yml` через GitHub MCP чтобы знать актуальную структуру
сервисов, сетей и volumes перед внесением изменений.

## Что добавить

### Новый сервис `redis`
```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
  command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy noeviction
  volumes:
    - redis_data:/data
  networks:
    - internal          # та же сеть что у rag-indexer и rag-backend
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 3s
    retries: 5
```

**Важно про `noeviction`:** Redis не будет молча выкидывать ключи при нехватке памяти —
вернёт ошибку. Это защищает активные task state от случайного удаления.

### В сервис `rag-indexer` добавить
```yaml
environment:
  REDIS_URL: redis://redis:6379
depends_on:
  redis:
    condition: service_healthy
```

### В сервис `rag-backend` добавить
```yaml
environment:
  REDIS_URL: redis://redis:6379
depends_on:
  redis:
    condition: service_healthy
```

### В секцию `volumes` добавить
```yaml
volumes:
  redis_data:
```

## Критичные детали

- Имя сети (`internal` или другое) — уточни из текущего `docker-compose.yml`
- Не удаляй существующие `depends_on` у `rag-indexer` и `rag-backend` — добавляй к ним
- Named volume `redis_data` сохраняется при `docker-compose down` и удаляется только при `docker-compose down -v`
- AOF (`--appendonly yes`) нужен чтобы не потерять task state при рестарте контейнера во время индексации

## Проверка после реализации
```bash
docker-compose up redis -d
docker-compose exec redis redis-cli ping
# Ожидается: PONG
```

## ✅ Тесты для этого этапа

Unit-тесты не нужны — это инфраструктурный шаг.  
Проверка выполняется вручную командами выше.

Дополнительно — проверь connectivity из контейнеров:
```bash
docker-compose run --rm rag-indexer python -c \
  "import redis.asyncio as r; import asyncio; asyncio.run(r.from_url('redis://redis:6379').ping())"
# Ожидается: True
```

## После завершения
Обнови `STATUS.md` — строку этапа 1: поставь ✅, запиши коммит, добавь в историю.
