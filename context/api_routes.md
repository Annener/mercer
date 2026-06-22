# API Routes — rag-backend

Базовый URL: `http://localhost:8000`  
Основной файл: `rag-backend/app/main.py`

## Роутеры

| Роутер | Prefix | Файл | Назначение |
|---|---|---|---|
| `chat_router` | `/api/chat` | `api/chat.py` | Чаты, сообщения, стриминг |
| `pipeline_resume_router` | `/api/pipeline` | `api/pipeline_resume.py` | Подтверждение/resume пайплайнов |
| `config_router` | `/api/config` | `api/config_api.py` | Системные настройки |
| `settings_router` | `/api/settings` | `api/settings/__init__.py` | Настройки платформы |
| `db_management_router` | `/api/db` | `api/db_management.py` | Управление БД, миграции |
| `indexer_state_router` | `/api/indexer` | `api/indexer_state.py` | Статус индексатора |
| `watchdog_router` | `/api/watchdog` | `api/watchdog_settings.py` | Настройки watchdog |

## Chat API (`api/chat.py`, ~34KB)

Ключевые эндпоинты:

```
POST   /api/chat/                           — создать чат
GET    /api/chat/                           — список чатов
GET    /api/chat/{chat_id}                  — получить чат
DELETE /api/chat/{chat_id}                  — удалить чат
PATCH  /api/chat/{chat_id}                  — обновить чат

GET    /api/chat/{chat_id}/messages         — история сообщений
POST   /api/chat/{chat_id}/message          — отправить сообщение (stream)
DELETE /api/chat/{chat_id}/messages         — очистить историю

GET    /api/chat/{chat_id}/clarification    — состояние ClarificationFSM
POST   /api/chat/{chat_id}/clarification/reset — сбросить уточнение
```

## Settings API (`api/settings/`)

### Домены (`settings/domains.py`)
```
GET    /api/settings/domains/               — список доменов
POST   /api/settings/domains/               — создать домен
GET    /api/settings/domains/{domain_id}    — получить домен
PATCH  /api/settings/domains/{domain_id}    — обновить домен
DELETE /api/settings/domains/{domain_id}    — удалить (не системный)

GET    /api/settings/domains/{domain_id}/prompts             — промпты домена
PUT    /api/settings/domains/{domain_id}/prompts/{type}      — обновить промпт
GET    /api/settings/domains/{domain_id}/clarification-fields
POST   /api/settings/domains/{domain_id}/clarification-fields
DELETE /api/settings/domains/{domain_id}/clarification-fields/{id}
```

### Вольты (`settings/vaults.py`)
```
GET    /api/settings/vaults/
POST   /api/settings/vaults/
GET    /api/settings/vaults/{vault_id}
PATCH  /api/settings/vaults/{vault_id}
DELETE /api/settings/vaults/{vault_id}
POST   /api/settings/vaults/{vault_id}/bind     — привязать embedding model
POST   /api/settings/vaults/{vault_id}/unbind   — отвязать
```

### Документы (`settings/documents.py`)
```
GET    /api/settings/documents/
GET    /api/settings/documents/{doc_id}
DELETE /api/settings/documents/{doc_id}
POST   /api/settings/documents/reindex          — переиндексировать
```

### Модели (`settings/gen_models.py`, `emb_models.py`, `rerank_models.py`)
```
# Generation Models
GET    /api/settings/models/generation/
POST   /api/settings/models/generation/
PATCH  /api/settings/models/generation/{model_id}
DELETE /api/settings/models/generation/{model_id}
POST   /api/settings/models/generation/{model_id}/activate

# Embedding Models  
GET    /api/settings/models/embedding/
POST   /api/settings/models/embedding/
PATCH  /api/settings/models/embedding/{model_id}
DELETE /api/settings/models/embedding/{model_id}

# Rerank Models
GET    /api/settings/models/rerank/
POST   /api/settings/models/rerank/
PATCH  /api/settings/models/rerank/{model_id}
DELETE /api/settings/models/rerank/{model_id}
POST   /api/settings/models/rerank/{model_id}/activate
```

### Кампании (`settings/campaigns.py`)
```
GET    /api/settings/campaigns/
POST   /api/settings/campaigns/
GET    /api/settings/campaigns/{campaign_id}
PATCH  /api/settings/campaigns/{campaign_id}
DELETE /api/settings/campaigns/{campaign_id}
```

### Теги (`settings/tags.py`)
```
GET    /api/settings/tags/
POST   /api/settings/tags/
DELETE /api/settings/tags/{tag_id}
```

### Пайплайны (`settings/pipelines.py`)
```
GET    /api/settings/pipelines/
POST   /api/settings/pipelines/
GET    /api/settings/pipelines/{pipeline_id}
PATCH  /api/settings/pipelines/{pipeline_id}
DELETE /api/settings/pipelines/{pipeline_id}
```

### Платформенные параметры (`settings/params.py`)
```
GET    /api/settings/params/           — все параметры (сгруппированы)
PATCH  /api/settings/params/{key}      — обновить параметр
```

## Pipeline Resume API (`api/pipeline_resume.py`)

```
POST   /api/pipeline/{chat_id}/confirm         — подтвердить запуск пайплайна
POST   /api/pipeline/{chat_id}/resume          — продолжить после паузы
POST   /api/pipeline/{chat_id}/cancel          — отменить
GET    /api/pipeline/{chat_id}/status          — статус пайплайна чата
```

## Статика и SPA

```
GET    /                  — возвращает index.html (SPA Vue)
GET    /static/*          — статические файлы фронтенда
GET    /health            — {"status": "ok", "service": "rag-backend"}
```

## Indexer State API (`api/indexer_state.py`)

```
GET    /api/indexer/state/{vault_id}    — IndexState из Redis
GET    /api/indexer/health             — проксирует к rag-indexer /health
```

## Watchdog API (`api/watchdog_settings.py`)

```
GET    /api/watchdog/settings          — настройки watchdog
PATCH  /api/watchdog/settings          — изменить интервал и т.д.
POST   /api/watchdog/trigger           — ручной запуск проверки
```
