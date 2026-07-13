# Статус реализации: Full Document Mode

> Последнее обновление: 2026-07-13  
> Текущий этап: **Этап 2 — Indexer size-метаданные**

---

## Прогресс по этапам

| Этап | Статус | Примечания |
|---|---|---|
| Этап 1 — Alembic-миграции (Chat + Document) | ✅ завершён | миграции 0003 + 0004 применены |
| Этап 2 — Indexer: запись size-метаданных | ◾️ не начат | — |
| Этап 3 — FullDocumentService | ◾️ не начат | — |
| Этап 4 — PipelineExecutor: новый шаг | ◾️ не начат | — |
| Этап 5 — API: новые эндпоинты | ◾️ не начат | — |
| Этап 6 — Frontend: тоглер + панель | ◾️ не начат | — |

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
- [ ] Найдено место в `indexer_worker.py` для записи
- [ ] Добавлен метод обновления в `db_client.py`
- [ ] Проверено: после переиндексации поля заполнены

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

---

## Следующий шаг

**Начать Этап 2.**

Что нужно сделать:
1. Найти `rag-indexer/indexer_worker.py` — место финализации документа (где статус переключается в `done`).
2. Найти `rag-indexer/app/db_client.py` — понять, есть ли прямой HTTP-доступ к `rag-backend` или через отдельный эндпоинт.
3. Добавить метод `update_document_size()` в `db_client.py`.
4. Вызвать его в `indexer_worker.py` при финализации.

---

## Инструкция по обновлению этого файла

По завершении каждого этапа модель должна:
1. Поставить ✅ напротив завершённого этапа в таблице прогресса.
2. Отметить чекбоксы выполненных задач.
3. Внести в раздел «Обнаруженные проблемы» любые нестандартные находки.
4. Обновить раздел «Следующий шаг».
5. Обновить дату в шапке файла.
