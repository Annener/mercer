# Статус реализации: Full Document Mode

> Последнее обновление: 2026-07-13  
> Текущий этап: **Этап 3 — FullDocumentService**

---

## Прогресс по этапам

| Этап | Статус | Примечания |
|---|---|---|
| Этап 1 — Alembic-миграции (Chat + Document) | ✅ завершён | миграции 0003 + 0004 применены |
| Этап 2 — Indexer: запись size-метаданных | ✅ завершён | `update_document_size()` + вызов в `_process_file()` |
| Этап 3 — FullDocumentService | ▾️ не начат | — |
| Этап 4 — PipelineExecutor: новый шаг | ▾️ не начат | — |
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
- [ ] Проверено: после переиндексации поля заполнены (requires manual test)

### Этап 3 — FullDocumentService
- [ ] Создан `full_document_service.py`
- [ ] `collect_document_candidates()` реализован
- [ ] `reconstruct_full_text()` реализован
- [ ] `assemble_hybrid_context()` реализован
- [ ] `DocumentCandidate` добавлен в `shared_contracts/models.py`

### Этап 4 — PipelineExecutor
- [ ] Найдена точка вставки паузы в `pipeline_executor.py`
- [ ] Пауза `full_document_selection` реализована
- [ ] SSE-событие `full_document_selection_required` добавлено
- [ ] `resume_from_full_doc_selection()` реализован
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

---

## Следующий шаг

**Начать Этап 3 — FullDocumentService.**

Что нужно сделать:
1. Найти `rag-backend/app/services/` — проверить структуру существующих сервисов и соглашения по стилю.
2. Найти `shared_contracts/models.py` — убедиться, что `DocumentCandidate` уже добавлен (этап 1), или добавить.
3. Создать `rag-backend/app/services/full_document_service.py` с тремя функциями:
   - `collect_document_candidates(hits, sent_full_document_ids, db)`
   - `reconstruct_full_text(document_id, vault_id, storage_api_url)`
   - `assemble_hybrid_context(selected_doc_ids, full_texts, hits, candidates)`
4. Изучить `retrieval.py` — понять структуру `SearchHit` для правильной группировки по `document_id`.

---

## Инструкция по обновлению этого файла

По завершении каждого этапа модель должна:
1. Поставить ✅ напротив завершённого этапа в таблице прогресса.
2. Отметить чекбоксы выполненных задач.
3. Внести в раздел «Обнаруженные проблемы» любые нестандартные находки.
4. Обновить раздел «Следующий шаг».
5. Обновить дату в шапке файла.
