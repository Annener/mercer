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
