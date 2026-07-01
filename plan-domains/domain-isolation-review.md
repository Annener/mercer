# Ревью изоляции доменов — план доработки

> Создан: 2026-07-01  
> Статус: **В работе** — ревью завершено, фиксы не начаты

## Цель

Мерсер — мульти-доменная RAG-платформа. Каждый домен (`domain_id`) должен быть полностью изолирован:
- свои **источники** (vault'ы + документы)
- свои **кампании**
- свои **пайплайны**
- свои **теги**

Текущее состояние: изоляция задумана, но **не соблюдается на уровне API и фронтенда**.

---

## Что проверено

### Источники файлов
- `context/db_schema.md` — схема PostgreSQL, ORM-модели
- `context/api_routes.md` — все HTTP-роуты rag-backend
- `context/frontend.md` — структура фронтенда, `api.js`, модули
- `context/rag-backend-services.md` — сервисный слой, pipeline_router, retrieval
- Прямой поиск по коду: `rag-backend/app/api/settings/{tags,campaigns,pipelines,vaults,campaigns}.py`

---

## Результаты ревью

### ✅ Что работает корректно

| Слой | Сущность | Почему ок |
|---|---|---|
| DB | `Tag` | `domain_id FK + UNIQUE(name, domain_id)` — теги изолированы на уровне схемы |
| DB | `Campaign` | `domain_id NOT NULL + CASCADE` — кампания всегда принадлежит домену |
| DB | `Pipeline` | `UNIQUE(pipeline_id, domain_id, version)` + индекс по `(domain_id, is_active)` |
| DB | `Chat` | `domain_id NOT NULL + CASCADE` — инвариант соблюдён |
| Service | `PipelineRouter` | Фильтрует кандидатов по `domain_id` чата перед LLM-роутингом |
| Service | `retrieval.get_allowed_tag_ids()` | Принимает `domain_id` явно, изоляция в retrieval-слое есть |
| Service | `retrieval.get_document_ids_by_tags()` | Аналогично, `domain_id` передаётся явно |

### ❌ Что нарушено

#### DB-уровень

| Проблема | Где | Детали |
|---|---|---|
| `Vault.domain_id` nullable | `db/models.py` | `ON DELETE SET NULL` — vault может оказаться без домена |
| `campaign_tags` M2M без domain-check | Схема / ORM | Нет констрейнта что тег и кампания принадлежат одному домену. Технически можно привязать тег домена A к кампании домена B |
| `Chat.vault_id` без FK и без domain-check | `db/models.py` | `vault_id` хранится строкой без FK-констрейнта. Нет проверки что vault принадлежит тому же домену что и чат |
| `Pipeline.campaign_id` без domain-check | `db/models.py` | Nullable FK на campaign — нет проверки что `campaign.domain_id == pipeline.domain_id` |

#### API-уровень (rag-backend)

| Эндпоинт | Проблема |
|---|---|
| `GET /api/settings/tags/` | `domain_id: str \| None = None` — без параметра возвращает теги ВСЕХ доменов |
| `GET /api/settings/campaigns/` | То же |
| `GET /api/settings/pipelines/` | То же |
| `GET /api/settings/vaults/` | То же |
| `GET /api/settings/documents/` | То же |
| `GET /api/chat/` | Нет `domain_id` параметра вообще — возвращает все чаты |

Во всех случаях фильтрация **опциональна**: параметр есть, но если не передан — отдаётся всё. Нет принудительного требования передавать `domain_id`.

#### Frontend-уровень

| Метод `api.js` | Проблема |
|---|---|
| `getCampaigns()` | Нет параметра `domainId` вообще — всегда грузит все домены |
| `getPipelines()` | То же |
| `getVaults()` | То же |
| `getChats()` | То же — sidebar фильтрует на клиенте после загрузки |
| `getTags(domainId?)` | Параметр есть, но опциональный |

**Системная проблема**: `window.currentDomainId` (устанавливается в `sidebar.js`) — существует только в контексте чата. Страница настроек (`settings.js` + `tab-*.js`) при загрузке данных **не передаёт** `currentDomainId` в API-вызовы. Вкладки Campaigns, Pipelines, Vaults, Documents показывают данные всех доменов.

---

## Приоритизация фиксов

### 🔴 Высокий приоритет

1. **`api.js` — добавить `domainId` параметр** в:
   - `getCampaigns(domainId)`
   - `getPipelines(domainId)`
   - `getVaults(domainId)`
   - `getChats(domainId)`

2. **`tab-campaigns.js`, `tab-pipelines.js`, `tab-vaults.js`, `tab-documents.js`** — при загрузке данных передавать `window.currentDomainId`. Нужно выяснить: как эти табы сейчас получают домен (если вообще получают).

3. **Settings page — domain context**: нужен механизм передачи "текущего домена" на страницу настроек. Варианты:
   - Использовать `window.currentDomainId` (уже есть)
   - Добавить domain-selector на страницу настроек
   - Открывать настройки "в контексте домена" через параметр

### 🟡 Средний приоритет

4. **`campaign_tags` M2M** — добавить валидацию на уровне сервиса (при добавлении тега в кампанию проверять `tag.domain_id == campaign.domain_id`). Констрейнт на уровне БД сложно сделать без триггера.

5. **`Chat.vault_id` domain-check** — при создании/обновлении чата валидировать что vault принадлежит тому же домену.

6. **`GET /api/chat/`** — добавить `domain_id: str | None` query-параметр на бэкенде.

### 🟢 Низкий приоритет

7. **`Vault.domain_id` nullable** — рассмотреть нужен ли vault без домена вообще. Если нет — сделать NOT NULL (требует миграции).

---

## Что нужно доизучить перед фиксами

### 1. Как `tab-*.js` сейчас вызывают API
Файлы не читались напрямую. Нужно посмотреть:
- `rag-backend/app/static/js/settings/tab-campaigns.js`
- `rag-backend/app/static/js/settings/tab-pipelines.js`
- `rag-backend/app/static/js/settings/tab-vaults.js`
- `rag-backend/app/static/js/settings/tab-documents.js`

Конкретно: есть ли там хоть какая-то передача домена, или вообще нет.

### 2. Как `sidebar.js` фильтрует чаты
Посмотреть `rag-backend/app/static/js/sidebar.js` — как происходит смена домена, передаётся ли `domain_id` в `getChats()` или фильтрация на клиенте.

### 3. Как `settings.js` открывает вкладки
Посмотреть `rag-backend/app/static/js/settings.js` — есть ли там понятие "текущего домена" для страницы настроек, или нет вообще.

### 4. Нужен ли domain-selector на странице настроек
Архитектурное решение: настройки сейчас глобальные (все домены), нужно ли добавить выбор домена прямо на странице настроек? Или всегда использовать `currentDomainId` из сайдбара?

### 5. Миграция для `Vault.domain_id NOT NULL`
Есть ли в продакшн-данных vaults без `domain_id`? Если да — нужен план миграции данных перед изменением схемы.

### 6. Валидация cross-domain в сервисах
Посмотреть `rag-backend/app/api/settings/campaigns.py` и `pipelines.py` — есть ли там валидация при создании/обновлении, или только чтение без проверок.

---

## Файлы для изменения (предварительный список)

```
# Frontend
rag-backend/app/static/js/api.js
rag-backend/app/static/js/settings/tab-campaigns.js
rag-backend/app/static/js/settings/tab-pipelines.js
rag-backend/app/static/js/settings/tab-vaults.js
rag-backend/app/static/js/settings/tab-documents.js
rag-backend/app/static/js/sidebar.js          # проверить getChats()
rag-backend/app/static/js/settings.js         # проверить domain context

# Backend API (опционально — если делать принудительный domain_id)
rag-backend/app/api/settings/campaigns.py
rag-backend/app/api/settings/pipelines.py
rag-backend/app/api/settings/vaults.py
rag-backend/app/api/chat.py

# Backend Services (валидация cross-domain)
rag-backend/app/services/settings_service.py  # или отдельный service

# DB (если делать NOT NULL на Vault.domain_id)
rag-backend/migrations/versions/  # новая миграция
rag-backend/app/db/models.py
```

---

## Связанные контекстные файлы

- `context/db_schema.md` — полная схема БД
- `context/api_routes.md` — все роуты
- `context/frontend.md` — структура фронтенда
- `context/rag-backend-services.md` — сервисный слой
