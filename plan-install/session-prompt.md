# Промт для новой сессии

> Копируй весь блок ниже целиком и вставляй в начало нового чата. Ничего не правь.
> Перед новой сессией обнови только файл [session-state.md](./session-state.md).

---

```
Ты помогаешь мне реализовывать план установки/деплоя проекта Mercer.

## Что такое Mercer

RAG/LLM-платформа на Python/FastAPI. Репозиторий: https://github.com/Annener/mercer

Сервисы:
- rag-backend (FastAPI, порт 8000)
- rag-indexer (порт 9000, внутренний)
- db-api-server (LanceDB HTTP API, порт 8080, внутренний)
- pdf-sidecar (embedding + reranker, порт 8765, на хосте)
- pdf-sidecar/agent (host-agent FastAPI, порт 9090)

## Документы проекта

Полный контекст: https://github.com/Annener/mercer/blob/main/plan-install/context.md
План работ:      https://github.com/Annener/mercer/blob/main/plan-install/plan.md
Статус шагов:    https://github.com/Annener/mercer/blob/main/plan-install/status.md
Текущая сессия:  https://github.com/Annener/mercer/blob/main/plan-install/session-state.md

Прочитай файл session-state.md — там текущий статус выполнения и задача на эту сессию.

## Стек и ограничения

- Python 3.11–3.13 (3.14+ несовместим с unstructured-inference)
- Makefile — bash-синтаксис
- Docker Compose v2
- macOS (основной dev-хост): launchd для host-agent
- Linux: host-agent в Docker Compose
- Windows: не реализовано, только предупреждение
- generate_env.py — только stdlib (без pip install)

## Важные детали

- ENCRYPTION_KEY: urlsafe base64 от 32 байт, всегда 44 символа → передаётся в Fernet(key.encode())
- HOST_AGENT_TOKEN: secrets.token_urlsafe(32), передаётся через X-Agent-Token header
- COMPOSE_PROFILES в .env читается Docker Compose автоматически
- Миграции БД применяются автоматически при старте rag-backend
- seed_models.py идемпотентен (HTTP 409/422 игнорируется)
```
