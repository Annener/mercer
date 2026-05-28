# Spec-02a: Settings Services

Перед выполнением прочитай `Spec-00-Architecture-Overview.md` целиком.

Этот Spec — **первая часть** бэкенда управления платформой. Реализует сервисы настроек и доменов, шифрование, кэширование и hot-swap генеративной модели.

**Зависит от:** `Spec-01` (схема БД и ORM-модели должны существовать).

**Цель:** Создать `settings_service.py` и `domain_service.py`. После выполнения этого Spec эти сервисы готовы к использованию, но API эндпоинты ещё не реализованы.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/app/db/models.py` — ORM-модели (должны существовать после Spec-01)
- `rag-backend/app/providers/generation/base.py` — `GenerationProvider`
- `rag-backend/app/providers/generation/openai_compatible.py` — реализация провайдера

## Задачи

### 1. Создать `services/settings_service.py`

Singleton-сервис. Отвечает за рантайм-параметры, активную генеративную модель и шифрование.

**Рантайм-параметры:**
- При старте загружает все записи из `platform_settings` в in-memory кэш (`dict[str, Any]`)
- `get(key: str) -> Any` — возвращает значение с приведением к `value_type` из БД. Если ключ не существует — `KeyError`.
- `set(key: str, value: Any) -> None` — обновляет БД и кэш. Если ключ не существует — `KeyError`.
- `reset_all() -> None` — сбрасывает все значения к дефолтам. Дефолты берутся из **словаря `DEFAULTS`**, захардкоженного внутри сервиса на основе раздела 3.2 `Spec-00` (16 параметров). Пример структуры:

```python
DEFAULTS = {
    "retrieval.enabled": True,
    "retrieval.top_k": 10,
    "retrieval.reranker_enabled": False,
    "chunking.chunk_size": 2000,
    "chunking.overlap": 64,
    "chunking.entity_aware_mode": True,
    "chat.max_clarification_turns": 3,
    "chat.stream_answers": True,
    "chat.auto_title": True,
    "reranker.enabled": False,
    "reranker.provider": None,
    "reranker.base_url": None,
    "reranker.model_name": None,
    "pdf_sidecar.url": "http://host.docker.internal:8765",
    "pdf_sidecar.timeout_seconds": 180,
    "pdf_sidecar.fallback_to_pdfminer": True,
}
```

- `invalidate(key: str) -> None` — сбрасывает конкретный ключ из кэша (при следующем `get()` перечитает из БД).

**Активная генеративная модель (hot-swap):**
- `_active_provider: GenerationProvider | None`
- `_provider_lock: asyncio.Lock`
- `get_active_provider() -> GenerationProvider` — если `None`, поднимает `RuntimeError("No active generation model configured")`
- `swap_provider(model_id: str, db: AsyncSession) -> None` — загружает модель из БД, расшифровывает ключ через Fernet, пересоздаёт провайдер под локом
- `load_active_provider(db: AsyncSession) -> None` — вызывается при старте; находит запись с `is_active=True`

**Шифрование:**
- Ключ из переменной окружения `ENCRYPTION_KEY`
- `encrypt_api_key(plain: str) -> str` — Fernet-шифрование, возвращает base64-строку
- `decrypt_api_key(encrypted: str) -> str` — расшифровка

**Методы для работы с моделями (будут использоваться в API):**
- `get_generation_model(model_id: str, db: AsyncSession) -> dict | None`
- `list_generation_models(db: AsyncSession) -> list[dict]` (без расшифрованных ключей, заменять на `has_api_key: bool`)
- `create_generation_model(data: dict, db: AsyncSession) -> dict`
- `update_generation_model(model_id: str, data: dict, db: AsyncSession) -> dict`
- `delete_generation_model(model_id: str, db: AsyncSession) -> None` (с проверкой `is_active`)
- `activate_generation_model(model_id: str, db: AsyncSession) -> None`

Аналогичные методы для `embedding_models` (без `activate`, т.к. embedding-модель привязывается к vault).

**Транзакции:** все операции, изменяющие БД, должны выполняться в рамках одной транзакции (`async with db.begin():`). Для `swap_provider` — отдельная транзакция на обновление `is_active`, затем вызов пересоздания провайдера вне транзакции.

### 2. Создать `services/domain_service.py`

Singleton-сервис. Отвечает за домены, промпты и поля уточнения. Данные хранятся в БД, in-memory кэш для быстрого доступа.

**Структура:**
- `_cache: dict[str, DomainConfig]` — in-memory кэш
- `DomainConfig` — dataclass: `domain_id`, `display_name`, `enabled`, `prompts: dict[str, str]`, `clarification_fields: list[dict]`

**Методы:**
- `get_domain(domain_id: str, db: AsyncSession) -> DomainConfig` — кэш → БД → fallback на `default`. Если домен не найден и не `default` — поднимать `ValueError`.
- `list_enabled(db: AsyncSession) -> list[DomainConfig]` — только `enabled=True` и `domain_id != 'default'` (если нужно скрыть системный домен из UI).
- `invalidate(domain_id: str) -> None`
- `get_prompt(domain_id: str, prompt_type: str, db: AsyncSession) -> str` — возвращает промпт или пустую строку, если не найден.
- `get_clarification_fields(domain_id: str, db: AsyncSession) -> list[dict]`

**Методы для CRUD (будут использоваться в API):**
- `create_domain(data: dict, db: AsyncSession) -> dict` (проверка `domain_id` уникальности, `is_system=False`)
- `update_domain(domain_id: str, data: dict, db: AsyncSession) -> dict`
- `delete_domain(domain_id: str, db: AsyncSession) -> None` (проверка `is_system` и наличие vault'ов в таблице `vaults`; если vault'ы есть — `ValueError`)
- `update_prompts(domain_id: str, prompts: dict[str, str], db: AsyncSession) -> None`
- `update_clarification_fields(domain_id: str, fields: list[dict], db: AsyncSession) -> None` (полная замена; перед удалением старых полей проверить `clarification_states` на использование)

**Важно:** При обновлении полей уточнения, если какие-то поля удаляются, а в `clarification_states` есть чаты в стадии `collecting` с этими полями в `missing_fields`, необходимо вернуть ошибку (конфликт). Это требование будет реализовано в API, но сервис должен предоставлять метод проверки `can_delete_fields(domain_id, field_names, db) -> bool`.

### 3. Обновить `providers/generation/factory.py`

`get_generation_provider()` → тонкая обёртка над `settings_service.get_active_provider()`. Убрать прямую работу с `config.yaml`.

### 4. Обновить `main.py` (частично)

**Прочитать текущий файл `rag-backend/app/main.py` перед изменениями.**

- Создать экземпляры `SettingsService` и `DomainService` в lifespan.
- Вызвать `await settings_service.load_active_provider(db)`.
- Если при выполнении ошибка (БД недоступна, нет активной модели) — залогировать `CRITICAL` и вызвать `sys.exit(1)`. Без ретраев.

**Пока не подключать роутер `api/settings.py`** — это будет в Spec-02b.

## Финальный контракт

После выполнения Spec-02a:
- `settings_service.py` существует, содержит все методы для работы с параметрами, моделями и шифрованием.
- `domain_service.py` существует, содержит кэширование и CRUD доменов.
- `providers/generation/factory.py` обновлён, использует `settings_service`.
- `main.py` инициализирует сервисы и загружает активную модель.
- Система **не обязана** запускаться (API ещё нет), но сервисы должны компилироваться без ошибок.

## Критерии приёмки

Codex проверяет самостоятельно:

- [ ] `python -m py_compile rag-backend/app/services/settings_service.py` — без ошибок
- [ ] `python -m py_compile rag-backend/app/services/domain_service.py` — без ошибок
- [ ] В `settings_service.DEFAULTS` ровно 16 ключей, значения соответствуют Spec-00
- [ ] `settings_service.get()` для существующего ключа возвращает значение правильного типа
- [ ] `settings_service.get()` для несуществующего ключа поднимает `KeyError`
- [ ] `settings_service.reset_all()` сбрасывает все параметры в значения из `DEFAULTS`
- [ ] `settings_service.encrypt_api_key()` и `decrypt_api_key()` работают с Fernet
- [ ] `domain_service.get_domain('dnd', db)` возвращает `DomainConfig` с промптами из БД
- [ ] `domain_service.get_domain('nonexistent', db)` падает на `default` (если `default` есть) или поднимает `ValueError`
- [ ] `domain_service.list_enabled(db)` не включает домен `default`
- [ ] `main.py` вызывает `load_active_provider`, при ошибке — `sys.exit(1)`
