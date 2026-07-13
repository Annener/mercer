# Статус реализации: Full Document Mode

> Последнее обновление: 2026-07-13  
> Текущий этап: **Этап 5 — API**

---

## Прогресс по этапам

| Этап | Статус | Примечания |
|---|---|---|
| Этап 1 — Alembic-миграции (Chat + Document) | ✅ завершён | миграции 0003 + 0004 применены |
| Этап 2 — Indexer: запись size-метаданных | ✅ завершён | `update_document_size()` + вызов в `_process_file()`; поля заполнены в psql |
| Этап 3 — FullDocumentService | ✅ завершён | `full_document_service.py` создан, все три функции реализованы |
| Этап 4 — PipelineExecutor: новый шаг | ✅ завершён | пауза + resume реализованы |
| Этап 5 — API: новые эндпоинты | ▾️ не начат | — |
| Этап 6 — Frontend: тоглер + панель | ▾️ не начат | — |

---

## Детальный статус

### Этап 1 — Alembic-миграции
- [x] Найдены ORM-модели Chat и Document (`rag-backend/app/db/models.py`)
- [x] Создана Alembic-ревизия `0003_fulldoc_fields`
- [x] Добавлены поля в Chat: `full_document_mode_enabled`, `sent_full_document_ids`
- [x] Добавлены поля в Document: `char_count`, `chunk_count`, `estimated_tokens`
- [x] Обновлены контракты в `shared_contracts/models.py`: `ChatRecord`, `DocumentRead`, добавлен `DocumentCandidate`
- [x] Миграция применена без ошибок (проверено через psql)

### Этап 2 — Indexer size-метаданные
- [x] Найдено место в `indexer_worker.py` для записи: финализация в `_process_file()` перед `update_document_status('indexed')`
- [x] Добавлен метод `update_document_size()` в `db_client.py` (прямой asyncpg UPDATE)
- [x] Проверено через psql: `char_count`, `chunk_count`, `estimated_tokens` заполнены у реальных документов

### Этап 3 — FullDocumentService
- [x] Создан `rag-backend/app/services/full_document_service.py`
- [x] `collect_document_candidates(hits, sent_full_document_ids, db)` реализован
- [x] `reconstruct_full_text(document_id, vault_id, db_api_url)` реализован
- [x] `assemble_hybrid_context(selected_doc_ids, full_texts, hits, candidates)` реализован
- [x] `DocumentCandidate` уже присутствовал в `shared_contracts/models.py` (добавлен в Этапе 1) — повторно не добавлялся

### Этап 4 — PipelineExecutor
- [x] Найдена точка вставки паузы в `pipeline_executor.py`
- [x] Пауза `full_document_selection` реализована (метод `_maybe_pause_for_full_doc`)
- [x] SSE-событие `full_document_selection_required` добавлено
- [x] `resume_from_full_doc_selection()` реализован
- [ ] Тест: режим выключен → pipeline идёт как обычно
- [ ] Тест: режим включён → пауза работает
- [ ] Тест: resume с пустым списком → только чанки
- [ ] Тест: resume с документами → гибридный контекст

### Этап 5 — API
- [ ] Найден роутер чата (`api/chat/`)
- [ ] `POST /api/chat/{chat_id}/full_document_confirm` добавлен
- [ ] PATCH чата расширен флагом `full_document_mode_enabled`
- [ ] curl-тесты пройдены

### Этап 6 — Frontend
- [ ] Найдены нужные JS-файлы в `app/static/`
- [ ] Тоглер добавлен в UI
- [ ] Тоглер сохраняется через PATCH
- [ ] Обработчик `full_document_selection_required` добавлен
- [ ] Панель выбора документов работает
- [ ] Суммарный счётчик токенов работает
- [ ] Кнопка «Продолжить без полных документов» работает
- [ ] End-to-end тест пройден в браузере

---

## Обнаруженные проблемы и решения

| # | Проблема | Решение | Этап |
|---|---|---|---|
| 1 | `sent_full_document_ids` создан как `json`, а не `jsonb` | `sa.JSON()` в SQLAlchemy не форсирует `jsonb` на PostgreSQL. Добавлена миграция `0004_fix_sent_full_document_ids_jsonb` | 1 |
| 2 | `db_client.py` в indexer работает напрямую через asyncpg, а не HTTP | План предполагал возможным HTTP-путь. Использован asyncpg — прямой UPDATE быстрее и проще. Никаких проблем, адаптер не нужен | 2 |
| 3 | Endpoint `/vaults/{vault_id}/documents/{document_id}/text` не существует в db-api-server | В `db-api-server/api/index.py` такого маршрута нет. Используется реальный endpoint: `GET /index/document/{document_id}/chunks?vault_id={vault_id}` → конкатенация текстов чанков по `chunk_index` | 3 |
| 4 | `SearchHit` в shared_contracts не имеет поля `vault_id` | vault_id ищется в `hit.metadata["vault_id"]`, при отсутствии — берётся первый ваулт из context_snapshot.vault_ids | 4 |
| 5 | `ctx.step_results` после `model_dump` содержит `_hits_*` ключи с объектами dict (не SearchHit) | `_collect_all_hits` поддерживает оба варианта: и `SearchHit`, и `dict` с валидацией через `model_validate` | 4 |

---

## Следующий шаг

**Начать Этап 5 — API.**

Что нужно сделать:
1. Найти роутер чата в `rag-backend/app/api/` — скорее всего `app/api/chat.py` или `app/api/chat/`.
2. Прочитать существующий `PATCH /chat/{chat_id}` — узнать текущую схему запроса и добавить поле `full_document_mode_enabled`.
3. Добавить `POST /chat/{chat_id}/full_document_confirm`:
   - Читает `pipeline_pause_state` из Chat.
   - Проверяет `pause_state["step"] == "full_document_selection"`.
   - Вызывает `executor.resume_from_full_doc_selection(chat_id, selected_document_ids, db)`.
   - Возвращает SSE-стрим (как в `/stream`).
   - Сохраняет ответ ллм в `Message`.
4. Паттерн смотреть в `pipeline_resume.py` — аналогичная логика SSE-стрима с сохранением сообщения.

**Важно перед реализацией**: прочитать реальный код роутера чата — найти `PATCH` и существующий `ChatUpdateRequest`.

---

## Инструкция по обновлению этого файла

По завершении каждого этапа модель должна:
1. Поставить ✅ напротив завершённого этапа в таблице прогресса.
2. Отметить чекбоксы выполненных задач.
3. Внести в раздел «Обнаруженные проблемы» любые нестандартные находки.
4. Обновить раздел «Следующий шаг».
5. Обновить дату в шапке файла.
