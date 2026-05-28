# Spec-02b: Settings API — Part 1 (Status, Params, Domains, Generation Models)

Перед выполнением прочитай `Spec-00-Architecture-Overview.md` и `Spec-02a` (сервисы уже созданы).

**Зависит от:** `Spec-02a` (сервисы `settings_service`, `domain_service` существуют).

**Цель:** Реализовать первую группу эндпоинтов `/settings/*`: статус, параметры, домены, генеративные модели. После выполнения этого Spec эти эндпоинты полностью работоспособны.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/services/settings_service.py` — создан в Spec-02a
- `rag-backend/app/services/domain_service.py` — создан в Spec-02a
- `rag-backend/app/db/models.py` — ORM-модели
- `rag-backend/app/main.py` — уже инициализирует сервисы

## Задачи

### 1. Создать `api/settings.py`

Новый роутер FastAPI. Подключить его в `main.py` (добавить `app.include_router(settings_router)`).

Реализовать следующие эндпоинты:

#### 1.1. Статус платформы

```
GET /settings/status
```

Возвращает:
```json
{
    "has_active_generation_model": bool,
    "has_active_embedding_model": bool,
    "pdf_sidecar_available": bool,
    "has_vaults": bool
}
```

**Логика:**
- `has_active_generation_model`: `settings_service.get_active_provider()` не бросает исключение → `true`, иначе `false`.
- `has_active_embedding_model`: проверить `SELECT count(*) FROM embedding_models WHERE enabled = true AND (SELECT count(*) FROM vaults WHERE embedding_model_id = embedding_models.model_id) > 0 LIMIT 1` (хотя бы одна embedding-модель привязана к vault'у). Если нет привязанных — `false`.
- `pdf_sidecar_available`: HTTP GET к URL из `settings_service.get("pdf_sidecar.url")` (путь `/health` или `/`), таймаут 2 секунды. При `200` → `true`, иначе `false`. При `KeyError` (параметр отсутствует) → вернуть `HTTP 500` с сообщением "pdf_sidecar.url not configured".
- `has_vaults`: `SELECT count(*) FROM vaults WHERE enabled = true > 0`.

#### 1.2. Рантайм-параметры

```
GET /settings/params
```

Возвращает все параметры из `platform_settings` в виде объекта: `{"key": value}`. Типы значений приводятся согласно `value_type` из БД. Использовать `settings_service.get_all()` (добавить этот метод в `settings_service`).

```
PUT /settings/params/{key}
```

Тело: `{"value": ...}` (может быть строка, число, булево, null).

**Валидация:**
- Прочитать `value_type` из БД для данного ключа.
- Если ключ не существует → `404`.
- Привести переданное значение к нужному типу:
  - `bool`: `"true"`, `"1"`, `true` → `True`; `"false"`, `"0"`, `false` → `False`. Иначе `422`.
  - `int`: целое число. Дробные или текст → `422`. `null` → `422`.
  - `float`: число с точкой. Текст → `422`. `null` → `422`.
  - `str`: любое строковое значение. `null` → сохранить пустую строку `""`.
- Обновить БД и вызвать `settings_service.invalidate(key)`.
- Вернуть `200 OK` с обновлённым значением.

```
POST /settings/params/reset
```

Сбросить все параметры к дефолтам: `settings_service.reset_all()`. Вернуть `200 OK`.

#### 1.3. Домены

```
GET /settings/domains
```

Возвращает список всех доменов из БД (включая `default`). Для каждого: `domain_id`, `display_name`, `description`, `is_system`, `enabled`.

```
POST /settings/domains
```

Тело:
```json
{
    "domain_id": "new_domain",
    "display_name": "Новый домен",
    "description": "опционально",
    "enabled": true
}
```

- `domain_id`: 3-32 символа, `[a-z0-9_]+`. Уникальность.
- `is_system` всегда принудительно `false`.
- Вызвать `domain_service.create_domain()`.
- Вернуть `201 Created` с созданным объектом. При дубликате `domain_id` → `409 Conflict`.

```
PUT /settings/domains/{id}
```

Тело: любые из полей `display_name`, `description`, `enabled`. Обновить через `domain_service.update_domain()`. Вернуть `200 OK`.

```
DELETE /settings/domains/{id}
```

- Проверить `is_system` — если `true`, вернуть `409 Conflict` с сообщением "Cannot delete system domain".
- Проверить наличие vault'ов: `SELECT count(*) FROM vaults WHERE domain_id = :id`. Если > 0 → `409 Conflict` с сообщением "Cannot delete domain: vaults still exist".
- Удалить через `domain_service.delete_domain()`. Вернуть `204 No Content`.

```
GET /settings/domains/{id}/prompts
```

Возвращает объект: `{"system": "...", "clarification": "...", "planner": "...", "pipeline_router": "..."}`.

```
PUT /settings/domains/{id}/prompts/{type}
```

Тело: `{"content": "..."}`. Обновить промпт указанного типа. Тип один из: `system`, `clarification`, `planner`, `pipeline_router`. Вернуть `200 OK`.

```
GET /settings/domains/{id}/fields
```

Возвращает список полей уточнения: `[{"field_name": "...", "label": "...", "hint": "...", "required": true, "display_order": 0}]`.

```
PUT /settings/domains/{id}/fields
```

Тело: массив полей (полная замена). Перед заменой проверить конфликты с `clarification_states` (см. задачу 4 в Spec-02c — но здесь можно упрощённо: если есть хотя бы один чат в стадии `collecting`, у которого `missing_fields` содержит удаляемое поле, вернуть `409 Conflict`). При успехе заменить и вернуть `200 OK`.

#### 1.4. Генеративные модели

```
GET /settings/generation-models
```

Возвращает список моделей. Для каждой: все поля, кроме `encrypted_api_key` (вместо него поле `has_api_key: bool`).

```
POST /settings/generation-models
```

Тело:
```json
{
    "model_id": "string, unique",
    "provider": "openai_compatible",
    "display_name": "опционально",
    "base_url": "valid URL",
    "api_key": "plain text (опционально)",
    "timeout_seconds": 60
}
```

- Шифровать `api_key` через `settings_service.encrypt_api_key()`.
- Сохранить в БД. Вернуть `201 Created`.

```
PUT /settings/generation-models/{id}
```

Обновление. Аналогично POST, но можно обновить любые поля. При обновлении `api_key` — если передан, шифровать; если не передан — оставить старый (не перезаписывать).

```
DELETE /settings/generation-models/{id}
```

Запретить, если модель активна (`is_active = true`) → `409 Conflict`. Иначе удалить.

```
POST /settings/generation-models/{id}/activate
```

- В транзакции: сбросить `is_active = false` у всех моделей.
- Установить `is_active = true` у указанной.
- Вызвать `settings_service.swap_provider(model_id, db)` (передать текущую сессию).
- Вернуть `200 OK`.

```
POST /settings/generation-models/{id}/check
```

- Загрузить модель из БД, расшифровать ключ.
- Создать провайдер (через `provider_factory` или напрямую).
- Отправить тестовый запрос (например, `{"messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}`).
- Замерить latency.
- Вернуть `{"ok": bool, "latency_ms": int, "error": str | null}`. При ошибке соединения или таймауте — `ok: false`.

### 2. Обновить `main.py`

- Импортировать `settings_router` из `api.settings`.
- Выполнить `app.include_router(settings_router, prefix="/settings", tags=["settings"])`.

## Финальный контракт

После выполнения Spec-02b:
- Все эндпоинты из раздела 1 работают.
- `GET /settings/status` возвращает корректные значения.
- `PUT /settings/params/{key}` валидирует типы и возвращает `422` при ошибке.
- `DELETE /settings/domains/{id}` проверяет `is_system` и наличие vault'ов.
- Генеративные модели можно создавать, активировать, проверять доступность.
- Система запускается без ошибок (при условии, что БД уже инициализирована Spec-01).

## Критерии приёмки

Codex проверяет самостоятельно:

- [ ] `docker compose up rag-backend` — сервис стартует (после выполнения Spec-01 и миграций)
- [ ] `GET /settings/status` возвращает JSON с четырьмя полями, нет `500`
- [ ] `GET /settings/params` возвращает 16 параметров
- [ ] `PUT /settings/params/retrieval.top_k` со значением `"abc"` → `422`
- [ ] `PUT /settings/params/chat.stream_answers` со значением `"true"` → успешно меняет на `true`
- [ ] `GET /settings/domains` возвращает 3 домена (default, dnd, work)
- [ ] `DELETE /settings/domains/default` → `409`
- [ ] `DELETE /settings/domains/dnd` (если есть vault'ы) → `409`
- [ ] `POST /settings/generation-models` + `POST .../activate` → `GET /settings/status` показывает `has_active_generation_model: true`
- [ ] `POST /settings/generation-models/{id}/check` возвращает `{"ok": ..., "latency_ms": ...}`
- [ ] Без активной генеративной модели `POST /chat/{id}/message` (если чат создан) — `HTTP 503` (проверка будет в Spec-02c, но пока не критично)
