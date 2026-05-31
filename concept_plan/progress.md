# Migration Progress

## Итерации

| # | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Миграция схемы БД (models.py + Alembic) | ✅ Готово | [42089da](https://github.com/Annener/mercer/commit/42089daa5c7b8fa7489d1392baa169a902145ab5) / [4224c01](https://github.com/Annener/mercer/commit/4224c0182f492ffa43f044bdb2f55306ea2c8db2) |
| 2 | Retrieval: multi-vault + domain_id | 🔜 Ожидает | — |
| 3 | Pipeline router + executor | 🔜 Ожидает | — |
| 4 | API-контракты, CreateChatRequest, shared_contracts | 🔜 Ожидает | — |
| 5 | Интеграционная проверка | 🔜 Ожидает | — |

---

## ✅ Итерация 1 — Миграция схемы БД

**Статус:** завершено

### Что сделано

- [x] `Tag.vault_id` удалён, добавлен `Tag.domain_id FK -> domains`
- [x] `Tag` UNIQUE: `(name, domain_id, campaign_id)` (`uq_tags_name_domain_campaign`)
- [x] `Tag` индекс: `idx_tags_vault` заменён на `idx_tags_domain`
- [x] `Campaign.vault_id` удалён, добавлен `Campaign.domain_id FK -> domains`
- [x] `Pipeline.campaign_id` nullable FK -> campaigns (добавлен)
- [x] `Pipeline` индекс: `idx_pipelines_domain` → `idx_pipelines_domain_campaign`
- [x] `PipelineLabel` удалён из `models.py` целиком
- [x] `Chat.vault_id` оставлен nullable (переходный период, TODO iter4)
- [x] Alembic `0005_iter1_domain_schema.py` создан

### Изменённые файлы

- `rag-backend/app/db/models.py`
- `rag-backend/migrations/versions/0005_iter1_domain_schema.py`

### Важно

В `0005_iter1_domain_schema.py` есть `server_default="default"` для `domain_id` в `tags` и `campaigns` — это временный дефолт для существующих строк. С чистой БД его не будет. Перед применением на боевой БД — нужно ручно сделать data-миграцию для существующих данных.

---

## 🔜 Итерация 2 — Retrieval: multi-vault + domain_id

**Цель:** перевести retrieval-слой с single-vault на multi-vault, привязка к domain_id.

### Планируемые изменения

- [ ] `chat_context` в `chat.py`: `vault_id` → `vault_ids: list[str]`
- [ ] `pipeline_executor._retrieve_for_step`: `retrieve(vault_id=...)` → `retrieve_multi_vault(vault_ids=...)`
- [ ] `get_allowed_tag_ids(vault_id, ...)` → `get_allowed_tag_ids(domain_id, ...)`
- [ ] `get_document_ids_by_tags(...)` → работает через domain_id
- [ ] Инвариант пустого контекста: `allowed == []` → `document_ids = []` (не `None`)

---

## 🔜 Итерация 3 — Pipeline router + executor

**Цель:** жёсткая фильтрация пайплайнов по режиму/кампании, правильная структура шагов.

### Планируемые изменения

- [ ] `pipeline_router.decide`: предфильтрация по `campaign_id` и режиму чата
- [ ] `pipeline_router.decide`: проверка совместимости `locked_pipeline_id` с режимом
- [ ] `pipeline_executor`: шаги используют `tag_id` (один), не `tag_ids`
- [ ] `pipeline_executor._run_step`: передавать `history` в LLM
- [ ] `pipeline_executor.run`: добавить SSE `step_started`, `step_skipped_no_docs`, `final_started`
- [ ] `chat.py`: удалить функцию `_run_pipelines` (заглушка)

---

## 🔜 Итерация 4 — API-контракты

**Цель:** API-контракты, совместимость с фронтом после изменения схемы.

### Планируемые изменения

- [ ] `CreateChatRequest`: убрать `vault_id`, сделать `domain_id` обязательным
- [ ] `_domain_id_for_chat`: убрать vault-fallback
- [ ] `shared_contracts/models`: обновить `ChatRecord`, `PipelineStep`, `PipelineContext`
- [ ] Удалить `rag-backend/app/api/bckp_settings.py_bckp`

---

## 🔜 Итерация 5 — Интеграционная проверка

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
