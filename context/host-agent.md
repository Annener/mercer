# host-agent

## Назначение

`host-agent` — лёгкий HTTP-агент, запускаемый **на хосте** (вне Docker). Позволяет `rag-backend`
(работающему в контейнере) управлять жизненным циклом процесса `pdf-sidecar` через HTTP-вызовы
на `host.docker.internal:9090`.

Является связующим звеном между контейнерной средой и хостовыми процессами — без него
управление `pdf-sidecar` из UI невозможно.

---

## Архитектурная позиция

```
Browser → Frontend (ванильный JS SPA)
               ↓ HTTP
         rag-backend  (Docker :8000)
               ↓ HTTP  →  host.docker.internal:9090
         host-agent   (хост :9090, только localhost)
               ↓ subprocess (bash start.sh / stop.sh / install.sh)
         pdf-sidecar  (процесс на хосте)
```

`rag-backend` обращается к `host-agent` через прокси-роутер `api/settings/sidecar.py`.
На macOS/Windows Docker Desktop `host.docker.internal` резолвится автоматически.
На Linux требуется `extra_hosts: host.docker.internal:host-gateway` в `docker-compose.yml`
(уже прописано для сервиса `rag-backend`).

---

## Файловая структура

```
host-agent/
├── agent.py                     — FastAPI-приложение, все эндпоинты
├── requirements.txt             — fastapi, uvicorn[standard]
├── mercer-host-agent.service    — systemd unit-файл (опционально)
└── README.md
```

---

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `HOST_AGENT_PORT` | `9090` | Порт агента (bind только на `127.0.0.1`) |
| `HOST_AGENT_TOKEN` | не задан | Shared secret. Если задан — все защищённые эндпоинты требуют заголовок `X-Agent-Token`. Если не задан — авторизация отключена |
| `SIDECAR_DIR` | `../pdf-sidecar` (от `agent.py`) | Абсолютный или относительный путь к директории `pdf-sidecar` |

Соответствующие переменные на стороне `rag-backend` (`docker-compose.yml`):

```
HOST_AGENT_URL=http://host.docker.internal:9090
HOST_AGENT_TOKEN=<тот же токен>
```

---

## HTTP API

> Эндпоинты `/sidecar/*` проверяют `X-Agent-Token`, если `HOST_AGENT_TOKEN` задан.  
> `/health` — публичный, токен не требует.

### `GET /health`

Статус агента и sidecar. Токен не требуется.

```json
{
  "status": "ok",
  "service": "host-agent",
  "sidecar": {
    "running": true,
    "pid": 12345,
    "installed": true,
    "sidecar_dir": "/opt/mercer/pdf-sidecar"
  }
}
```

---

### `GET /sidecar/status`

Текущее состояние процесса sidecar.

```json
{
  "running": false,
  "pid": null,
  "installed": true,
  "sidecar_dir": "/opt/mercer/pdf-sidecar"
}
```

`installed` = наличие `.venv/` в `SIDECAR_DIR`.  
Если PID-файл (`sidecar.pid`) существует, но процесс мёртв — файл автоматически удаляется (stale pidfile cleanup).

---

### `POST /sidecar/start`

Запускает sidecar через `start.sh`. Если процесс уже запущен — возвращает `ok: false` без запуска.

```json
{"ok": true, "message": "Started", "output": "..."}
```

Таймаут исполнения скрипта: **15 сек**.

---

### `POST /sidecar/stop`

Останавливает sidecar через `stop.sh`.

```json
{"ok": true, "output": "..."}
```

Таймаут: **20 сек**.

---

### `POST /sidecar/restart`

Последовательно вызывает `stop.sh`, затем `start.sh`. Ошибка stop не прерывает start.

```json
{
  "ok": true,
  "message": "Restarted",
  "stop_output": "...",
  "start_output": "..."
}
```

---

### `GET /sidecar/install/stream`

SSE-поток вывода `install.sh`. Используется для отображения прогресса установки в UI.

**Media-type:** `text/event-stream`  
Каждая строка вывода скрипта отправляется как SSE-событие:

```
data: [START] Running install.sh...

data: Installing Tesseract OCR...

data: [DONE] exit_code=0

```

При дисконнекте клиента (`request.is_disconnected()`) стрим прерывается.

---

## Внутренняя логика

### Определение статуса процесса

Агент читает PID из `SIDECAR_DIR/sidecar.pid` и проверяет его через `os.kill(pid, 0)`.
Это сигнал 0 — не убивает процесс, только проверяет его существование.

### Запуск скриптов

Все операции делегируются bash-скриптам в `SIDECAR_DIR` (`start.sh`, `stop.sh`, `install.sh`).
Исполнение — через `asyncio.create_subprocess_exec`. Тайм-аут реализован через `asyncio.wait_for`.

### Авторизация

```python
def check_token(x_agent_token: str | None) -> None:
    if AGENT_TOKEN and x_agent_token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Agent-Token")
```

Вызывается явно в каждом защищённом эндпоинте (не через `Depends`, намеренно — для простоты).

---

## Установка и запуск

```bash
cd host-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
# Без авторизации (только для локальной разработки)
python agent.py

# С токеном (рекомендуется)
HOST_AGENT_TOKEN=mysecrettoken python agent.py

# С явным путём к sidecar
SIDECAR_DIR=/opt/mercer/pdf-sidecar HOST_AGENT_TOKEN=mysecrettoken python agent.py
```

По умолчанию слушает на `127.0.0.1:9090` — намеренно только localhost, не доступен извне.

---

## Запуск через systemd (опционально)

```bash
sudo cp mercer-host-agent.service /etc/systemd/system/
# Отредактировать пути и пользователя в юните
sudo systemctl daemon-reload
sudo systemctl enable --now mercer-host-agent
sudo systemctl status mercer-host-agent
```

---

## Связанные компоненты

| Компонент | Файл | Описание |
|---|---|---|
| Прокси-роутер | `rag-backend/app/api/settings/sidecar.py` | Пробрасывает запросы от UI к host-agent |
| Управляемый сервис | `pdf-sidecar/` | Процесс, которым управляет host-agent |
| Env-переменные backend | `docker-compose.yml` → `rag-backend` | `HOST_AGENT_URL`, `HOST_AGENT_TOKEN` |
