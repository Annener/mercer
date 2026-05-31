# Migration Progress

## Итерации

| # | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Миграция схемы БД (models.py + Alembic) | ✅ Готово | [42089da](https://github.com/Annener/mercer/commit/42089daa5c7b8fa7489d1392baa169a902145ab5) / [4224c01](https://github.com/Annener/mercer/commit/4224c0182f492ffa43f044bdb2f55306ea2c8db2) |
| 2 | Retrieval: multi-vault + domain_id | ✅ Готово | [d08a45f](https://github.com/Annener/mercer/commit/d08a45fd674b148d452d107e5de9447072695c1c) / [d5f0e22](https://github.com/Annener/mercer/commit/d5f0e220ae16874e588ea1c597a40ad93b52852c) |
| 3 | Pipeline executor: domain_id + multi-vault | ✅ Готово | [effd91a](https://github.com/Annener/mercer/commit/effd91a6eff08d1a71f2648082290af0c294357e) |
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

В `0005_iter1_domain_schema.py` есть `server_default="default"` для `domain_id` в `tags` и `campaigns` — это временный дефолт для существующих строк. Перед применением на боевой БД — нужна ручная data-миграция.

---

## ✅ Итерация 2 — Retrieval: multi-vault + domain_id

**Статус:** завершено

### Что сделано

- [x] `get_allowed_tag_ids(vault_id, ...)` → `get_allowed_tag_ids(domain_id, ...)` — фильтрует теги по `Tag.domain_id`
- [x] `get_document_ids_by_tags(tag_ids, vault_id, ...)` → `get_document_ids_by_tags(tag_ids, domain_id, ...)` — JOIN с `Vault` таблицей, ищет документы по всем enabled-Vault домена
- [x] `retrieve_multi_vault`: добавлен guard `document_ids=[]` → `return []` без запросов к LanceDB
- [x] `chat.py`: `chat_context["vault_ids"]` — список всех enabled-Vault домена
- [x] `chat.py`: инвариант «кампания без тегов → `document_ids=[]`» (не расширяется на весь домен)
- [x] `_generate_answer`: если `chat.vault_id` задан → `retrieve`, иначе → `retrieve_multi_vault` по всем vault'ам домена
- [x] `_domain_id_for_chat` вынесена как async-метод с vault-fallback + TODO(iter4)

### Изменённые файлы

- `rag-backend/app/services/retrieval.py`
- `rag-backend/app/api/chat.py`

---

## ✅ Итерация 3 — Pipeline executor: domain_id + multi-vault

**Статус:** завершено

### Что сделано

- [x] `_retrieve_for_step`: `vault_id` → `domain_id` для вызовов `get_allowed_tag_ids` и `get_document_ids_by_tags`
- [x] `_retrieve_for_step`: читает `vault_ids: list[str]` из `chat_context` (вместо `vault_id`)
- [x] Обратная совместимость: если `vault_ids` нет, fallback на `chat_context["vault_id"]` (переходный период)
- [x] Логика выбора: `len(vault_ids)==1` → `retrieve(...)`, `>1` → `retrieve_multi_vault(...)`
- [x] Guard: нет `domain_id` при наличии `step.tag_ids` → warning + `return []`
- [x] Guard: нет `vault_ids` → warning + `return []`
- [x] Подробное логирование: `domain_id`, `vault_ids` в каждом `Pipeline retrieval start`

### Изменённые файлы

- `rag-backend/app/services/pipeline_executor.py`

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
