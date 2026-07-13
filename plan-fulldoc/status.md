# Статус реализации: Full Document Mode

> Последнее обновление: 2026-07-13  
> Текущий этап: **Этап 6 — завершён. Все этапы выполнены ✅**

---

## Прогресс по этапам

| Этап | Статус | Примечания |
|---|---|---|
| Этап 1 — Alembic-миграции (Chat + Document) | ✅ завершён | миграции 0003 + 0004 применены |
| Этап 2 — Indexer: запись size-метаданных | ✅ завершён | `update_document_size()` + вызов в `_process_file()`; поля заполнены в psql |
| Этап 3 — FullDocumentService | ✅ завершён | `full_document_service.py` создан, все три функции реализованы |
| Этап 4 — PipelineExecutor: новый шаг | ✅ завершён | пауза + resume реализованы |
| Этап 5 — API: новые эндпоинты | ✅ завершён | `full_document_confirm` добавлен, PATCH расширен, роутер зарегистрирован |
| Этап 6 — Frontend: тоглер + панель | ✅ завершён | тоглер в context-bar, SSE-обработчик, панель выбора, стили |

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
- [x] Найден роутер чата (`rag-backend/app/api/chat.py`)
- [x] `POST /chat/{chat_id}/full_document_confirm` добавлен (`rag-backend/app/api/fulldoc_confirm.py`)
- [x] PATCH чата расширен флагом `full_document_mode_enabled`
- [ ] curl-тесты пройдены

### Этап 6 — Frontend
- [x] Найдены нужные JS-файлы в `app/static/`
- [x] Тоглер добавлен в UI (`index.html` — `#fulldoc-toggle` + `#fulldoc-checkbox` в `#chat-context-bar`)
- [x] Тоглер сохраняется через PATCH (`chatAPI.setFullDocMode()` в обработчике `change`)
- [x] Обработчик `full_document_selection_required` добавлен в `handleStreamResponse()`
- [x] Панель выбора документов реализована (`createFullDocPanel()` в `chat.js`)
- [x] Суммарный счётчик токенов работает (событие `change` на списке чекбоксов)
- [x] Кнопка «Продолжить без полных документов» работает (вызов `fullDocConfirm` с пустым массивом)
- [x] `css/fulldoc.css` создан, подключён в `index.html`
- [x] `api/chat.js` — добавлены методы `setFullDocMode()` и `fullDocConfirm()`
- [x] `clearMessages()` расширен — удаляет `.fulldoc-panel` при переходе между чатами
- [x] `reset()` сбрасывает `fulldocCheckbox.checked = false`
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
| 6 | `PATCH /chat/{chat_id}` уже использует `UpdateChatRequest`, где `campaign_id` объявлен как обязательное поле (`= ...`) | Для минимально-инвазивной реализации Stage 5 новый флаг `full_document_mode_enabled` добавлен как опциональный, без изменения обязательности `campaign_id`. Это значит, что клиенту пока безопаснее продолжать отправлять `campaign_id` вместе с PATCH-запросом | 5 |
| 7 | В `full_document_confirm` нужен устойчивый SSE lifecycle с живой DB-сессией до конца генератора | Использован отдельный `SessionLocal()` внутри генератора по тому же паттерну, что и в `pipeline_resume.py`, чтобы сессия не закрылась раньше завершения стрима | 5 |
| 8 | SHA файла `api/chat.js` устарел при первой попытке обновления | Файл был уже обновлён в ходе предыдущей сессии. Получена актуальная SHA перед записью. Методы `setFullDocMode` и `fullDocConfirm` присутствовали в репозитории | 6 |
| 9 | Весь Frontend-код уже находился в репозитории на момент работы | Этапы `chat.js`, `fulldoc.css`, `index.html`, `api/chat.js` были реализованы в предыдущей сессии. Текущая сессия верифицировала код и обновил status.md | 6 |
| 10 | 500 Internal Server Error при переключении тогла Full Document Mode в новом чате | `UpdateChatRequest.campaign_id` был объявлен как обязательное поле (`= ...`). Фронтенд `setFullDocMode()` отправляет только `{"full_document_mode_enabled": true/false}` без `campaign_id`. При его отсутствии Pydantic возвращал 422, а при пустой строке `uuid.UUID("")` бросал неперехваченный `ValueError` → 500. Исправлено: `campaign_id` сделан опциональным (`= None`), в обработчике `update_chat()` применяется partial PATCH semantics через `req.model_fields_set` — `campaign_id` обновляется только если явно передан в запросе. Добавлен `try/except ValueError` с возвратом 422. | 5 |

---

## Следующий шаг

**Все 6 этапов реализации завершены.**

Оставшиеся задачи — ручное тестирование:

1. **curl-тесты (Этап 5)**:
   - `PATCH /chat/{id}` с `full_document_mode_enabled: true/false`
   - `POST /chat/{id}/full_document_confirm` с `selected_document_ids: []` и `["id1", "id2"]`

2. **Браузерный end-to-end (Этап 6)**:
   - Открыть чат с кампанией
   - Включить тоглер «📄 Полные документы» → обновить страницу → тоглер должен остаться включённым
   - Отправить сообщение → при достаточном числе релевантных документов должна появиться панель выбора
   - Выбрать документы → нажать «Продолжить» → ответ должен содержать полный текст документов
   - Нажать «Продолжить без полных документов» → обычный RAG-ответ

3. **Pipeline-тесты (Этап 4)**:
   - Режим выключен → pipeline без паузы
   - Режим включён → пауза с SSE-событием
   - Resume с пустым массивом → только чанки
   - Resume с документами → гибридный контекст
