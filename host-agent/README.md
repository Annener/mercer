# host-agent

Лёгкий HTTP-агент, запускаемый **на хосте** (вне Docker). Позволяет backend-у (работающему
в контейнере) управлять процессом `pdf-sidecar` через HTTP.

## Архитектура

```
Browser → Frontend (Vue)
               ↓ HTTP
         rag-backend (Docker :8000)
               ↓ HTTP → host.docker.internal:9090
         host-agent  (хост :9090, только localhost)
               ↓ subprocess
         pdf-sidecar  (процесс на хосте)
```

## Установка

```bash
cd host-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
# Без аутентификации (только для локальной разработки)
python agent.py

# С токеном (рекомендуется)
HOST_AGENT_TOKEN=mysecrettoken python agent.py

# С явным путём к sidecar (если не рядом)
SIDECAR_DIR=/opt/mercer/pdf-sidecar HOST_AGENT_TOKEN=mysecrettoken python agent.py
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `HOST_AGENT_PORT` | `9090` | Порт агента (только localhost) |
| `HOST_AGENT_TOKEN` | не задан | Shared secret для аутентификации (заголовок `X-Agent-Token`). Если не задан — auth отключена |
| `SIDECAR_DIR` | `../pdf-sidecar` | Путь к директории pdf-sidecar |

## API

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/health` | Статус агента + статус sidecar |
| `GET` | `/sidecar/status` | Статус процесса sidecar |
| `POST` | `/sidecar/start` | Запустить sidecar |
| `POST` | `/sidecar/stop` | Остановить sidecar |
| `POST` | `/sidecar/restart` | Перезапустить sidecar |
| `GET` | `/sidecar/install/stream` | SSE-поток вывода `install.sh` |

Все эндпоинты кроме `/health` требуют заголовок `X-Agent-Token` если `HOST_AGENT_TOKEN` задан.

## Запуск через systemd (опционально)

См. файл `mercer-host-agent.service` в этой директории.

```bash
# Скопировать юнит
sudo cp mercer-host-agent.service /etc/systemd/system/
# Отредактировать пути в юните под вашу систему
sudo systemctl daemon-reload
sudo systemctl enable --now mercer-host-agent
sudo systemctl status mercer-host-agent
```

## Подключение Docker-контейнера

Добавьте в `.env`:
```
HOST_AGENT_URL=http://host.docker.internal:9090
HOST_AGENT_TOKEN=mysecrettoken
```

Для Linux также добавьте в `docker-compose.yml` к сервису `rag-backend`:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```
(На macOS/Windows Docker Desktop это работает автоматически.)
