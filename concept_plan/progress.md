# Migration Progress

## Итерации

| # | Название | Статус | Коммит |
|---|---|---|---|
| 1 | Миграция схемы БД (models.py + Alembic) | ✅ Готово | [42089da](https://github.com/Annener/mercer/commit/42089daa5c7b8fa7489d1392baa169a902145ab5) |
| 2 | Retrieval: multi-vault + domain_id | ✅ Готово | [d08a45f](https://github.com/Annener/mercer/commit/d08a45fd674b148d452d107e5de9447072695c1c) |
| 3 | Pipeline executor: domain_id + multi-vault | ✅ Готово | [effd91a](https://github.com/Annener/mercer/commit/effd91a6eff08d1a71f2648082290af0c294357e) |
| 4 | API-контракты, shared_contracts | ✅ Готово | [5e151c5](https://github.com/Annener/mercer/commit/5e151c5734e77371f59fcc616fdbb48c56d8aea4) |
| 5 | Интеграционная проверка | 🔜 Ожидает | — |

---

## ✅ Итерация 1 — Миграция схемы БД

**Статус:** завершено

- [x] `Tag.vault_id` удалён, добавлен `Tag.domain_id FK -> domains`
- [x] `Campaign.vault_id` удалён, добавлен `Campaign.domain_id FK -> domains`
- [x] `Pipeline.campaign_id` nullable FK -> campaigns
- [x] `PipelineLabel` удалён целиком
- [x] `Chat.vault_id` nullable (переходный период, TODO iter4-cleanup)
- [x] Alembic `0005_iter1_domain_schema.py`

⚠️ `server_default="default"` в миграции — перед боевым применением нужна ручная data-миграция.

---

## ✅ Итерация 2 — Retrieval: multi-vault + domain_id

**Статус:** завершено

- [x] `get_allowed_tag_ids(domain_id, ...)` — фильтр по `Tag.domain_id`
- [x] `get_document_ids_by_tags(tag_ids, domain_id, ...)` — JOIN с `Vault`, все enabled-Vault домена
- [x] `retrieve_multi_vault`: guard `document_ids=[]` → `return []`
- [x] `chat.py`: `chat_context["vault_ids"]` — список enabled-Vault домена
- [x] Инвариант пустой кампании: `document_ids=[]` (не None)
- [x] `_domain_id_for_chat` с vault-fallback + TODO(iter4-cleanup)

---

## ✅ Итерация 3 — Pipeline executor: domain_id + multi-vault

**Статус:** завершено

- [x] `_retrieve_for_step`: `domain_id` вместо `vault_id` в вызовах get_allowed / get_document_ids
- [x] `vault_ids: list[str]` из `chat_context`, fallback на `vault_id` (бак-компат)
- [x] `len(vault_ids)==1` → `retrieve`, `>1` → `retrieve_multi_vault`
- [x] Guard: нет `domain_id` при `step.tag_ids` → warning + `return []`
- [x] Guard: нет `vault_ids` → warning + `return []`

---

## ✅ Итерация 4 — API-контракты, shared_contracts

**Статус:** завершено

- [x] `TagRead.domain_id` — заменяет `vault_id`
- [x] `TagCreate.domain_id` — `vault_id` удалён
- [x] `CampaignRead.domain_id` — заменяет `vault_id`
- [x] `CampaignCreate.domain_id` — `vault_id` удалён
- [x] `PipelineRead.campaign_id: str | None` — None = общий пайплайн домена
- [x] `PipelineCreate.campaign_id: str | None`
- [x] `PipelineContext.domain_id` — основной; `vault_ids: list[str]`; `vault_id` оставлен deprecated
- [x] `CreateChatRequest.vault_id` — nullable back-compat; `domain_id` primary
- [x] `ChatRecord.vault_id` — nullable, TODO(iter4-cleanup)
- [x] `bckp_settings.py_bckp` удалён

### Оставшиеся TODO (iter4-cleanup, после фронт-миграции)

- [ ] `CreateChatRequest`: сделать `domain_id` обязательным, убрать `vault_id`
- [ ] `ChatRecord`: убрать `vault_id`
- [ ] `PipelineContext`: убрать `vault_id`
- [ ] `_domain_id_for_chat`: убрать vault-fallback
- [ ] `Chat.vault_id`: удалить из схемы (новая Alembic миграция)

---

## 🔜 Итерация 5 — Интеграционная проверка

**Цель:** сквозная проверка всех инвариантов концепции.

### Сценарии

1. Домен → несколько Vault → документы → теги → кампания в чате → RAG ограничен тегами кампании
2. Пустые теги кампании → retrieval возвращает `[]`, не весь домен
3. Общий пайплайн недоступен в режиме кампании и наоборот
4. SSE-события pipeline execution корректны

---

## Контекст для новой сессии

Репозиторий: `Annener/mercer`

Ключевые файлы:
- `rag-backend/app/db/models.py`
- `rag-backend/app/api/chat.py`
- `rag-backend/app/services/pipeline_executor.py`
- `rag-backend/app/services/pipeline_router.py`
- `rag-backend/app/services/retrieval.py`
- `shared_contracts/models.py`
- `concept_plan/another_context.md` — исходная концепция
