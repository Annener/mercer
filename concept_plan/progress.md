# Migration Progress

## Итерации

| # | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Миграция схемы БД (models.py + Alembic) | ⏳ В процессе | — |
| 2 | Retrieval: multi-vault + domain_id | 🔜 Ожидает | — |
| 3 | Pipeline router + executor | 🔜 Ожидает | — |
| 4 | API-контракты, CreateChatRequest, shared_contracts | 🔜 Ожидает | — |
| 5 | Интеграционная проверка | 🔜 Ожидает | — |

---

## Итерация 1 — Миграция схемы БД

**Цель:** привести `models.py` к целевой модели согласно `another_context.md`.

### Изменения в `models.py`

- [ ] `Tag.vault_id` → удалить, заменить на `Tag.domain_id FK -> domains`
- [ ] `Tag` UNIQUE-констрейнт: `(name, vault_id, campaign_id)` → `(name, domain_id, campaign_id)`
- [ ] `Tag` индексы: `idx_tags_vault` → `idx_tags_domain`
- [ ] `Campaign.vault_id` → удалить, заменить на `Campaign.domain_id FK -> domains`
- [ ] `Pipeline` → добавить `campaign_id: UUID nullable FK -> campaigns`
- [ ] `Pipeline` индекс: добавить `campaign_id` в `idx_pipelines_domain`
- [ ] `PipelineLabel` → удалить класс целиком
- [ ] `Chat.vault_id` → оставить nullable (переходный период), задокументировать план удаления

### Alembic-миграция

- [ ] Создать файл миграции `alembic/versions/XXXX_iter1_domain_schema.py`
  - DROP TABLE `pipeline_labels`
  - `tags`: DROP COLUMN `vault_id`, ADD COLUMN `domain_id`, обновить констрейнты
  - `campaigns`: DROP COLUMN `vault_id`, ADD COLUMN `domain_id`
  - `pipelines`: ADD COLUMN `campaign_id`

### Инварианты для проверки

- Тег принадлежит домену, не Vault
- Кампания принадлежит домену, не Vault
- Пайплайн может быть привязан к кампании (nullable)
- `PipelineLabel` полностью удалён из схемы

---

## Итерация 2 — Retrieval: multi-vault + domain_id

**Цель:** перевести retrieval-слой с single-vault на multi-vault, привязка к domain_id.

### Планируемые изменения

- `chat_context` в `chat.py`: `vault_id` → `vault_ids: list[str]`
- `pipeline_executor._retrieve_for_step`: `retrieve(vault_id=...)` → `retrieve_multi_vault(vault_ids=...)`
- `get_allowed_tag_ids(vault_id, ...)` → `get_allowed_tag_ids(domain_id, ...)`
- `get_document_ids_by_tags(...)` → работает через domain_id
- Инвариант пустого контекста: `allowed == []` → `document_ids = []` (не `None`)

---

## Итерация 3 — Pipeline router + executor

**Цель:** жёсткая фильтрация пайплайнов по режиму/кампании, правильная структура шагов.

### Планируемые изменения

- `pipeline_router.decide`: предфильтрация по `campaign_id` и режиму чата
- `pipeline_router.decide`: проверка совместимости `locked_pipeline_id` с режимом
- `pipeline_executor`: шаги используют `tag_id` (один), не `tag_ids`
- `pipeline_executor._run_step`: передавать `history` в LLM
- `pipeline_executor.run`: добавить SSE `step_started`, `step_skipped_no_docs`, `final_started`
- `chat.py`: удалить функцию `_run_pipelines` (заглушка)

---

## Итерация 4 — API-контракты

**Цель:** API-контракты, совместимость с фронтом после изменения схемы.

### Планируемые изменения

- `CreateChatRequest`: убрать `vault_id`, сделать `domain_id` обязательным
- `_domain_id_for_chat`: убрать vault-fallback
- `shared_contracts/models`: обновить `ChatRecord`, `PipelineStep`, `PipelineContext`
- Удалить `rag-backend/app/api/bckp_settings.py_bckp`

---

## Итерация 5 — Интеграционная проверка

**Цель:** сквозная проверка всех инвариантов концепции.

### Сценарии

- Домен → несколько Vault → документы → теги → кампания в чате → RAG ограничен тегами кампании
- Пустые теги кампании → retrieval возвращает `[]`, не весь домен
- Общий пайплайн недоступен в режиме кампании и наоборот
- SSE-события pipeline execution корректны

---

## Контекст для новой сессии

Репозиторий: `Annener/mercer`  
Ключевые файлы:
- `rag-backend/app/db/models.py` — схема БД
- `rag-backend/app/api/chat.py` — основной обработчик чата
- `rag-backend/app/services/pipeline_executor.py` — исполнитель пайплайнов
- `rag-backend/app/services/pipeline_router.py` — маршрутизатор пайплайнов
- `rag-backend/app/services/retrieval.py` — retrieval-слой
- `shared_contracts/models.py` — Pydantic-контракты
- `another_context.md` (в репо) — исходная концепция, источник истины

Для продолжения: прочитай этот файл + `another_context.md` + файл нужной итерации.
