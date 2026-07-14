# Фаза 5 — SSE-стриминг и фронтенд

**Цель фазы**: Подключить SSE для стриминга генерации правок в реальном времени
и реализовать UI компоненты в чате: toggle, diff-view, кнопки review.
После фазы: полная пользовательская цепочка работает end-to-end.

**Зависимости**: [Фаза 4](phase-4-api.md) завершена
**Следующая фаза**: нет (финальная фаза MVP)

---

## Контекст для чтения

Перед началом работы прочитай:
- `context/frontend.md` — структура фронтенда, существующие компоненты
- `context/rag-backend-services.md` — как устроен SSE-стриминг
  (pipeline_executor.py, SSE events pattern)
- `context/api_routes.md` — SSE-роутеры, как они устроены
- `context/shared_contracts.md` — все Update Mode контракты
- Фазы 1–4 (все уже реализованы)

---

## Задачи

### 5.1 — SSE-стриминг генерации правок

Изменить эндпоинт `POST /chats/{chat_id}/update-mode/start` на SSE-стрим
(или добавить альтернативный `GET /chats/{chat_id}/update-mode/stream`).

SSE events:
```
event: update_mode_started
data: {"chat_id": "...", "md_files_count": 5, "context_tokens": 12400}

event: update_mode_generating
data: {"status": "Анализирую заметку..."}   # промежуточный статус

event: update_mode_change
data: {ProposedChange JSON}  # по одному, по мере генерации если LLM поддерживает streaming JSON

event: update_mode_done
data: {"total_changes": 3, "session_id": "..."}

event: update_mode_error
data: {"error": "...", "code": "parse_error" | "llm_error" | "context_too_large"}
```

Паттерн аналогичен `pipeline_executor.py` → `step_status`, `full_document_selection_required`.

### 5.2 — UI: Toggle Campaign Update Mode

В компонент чата добавить кнопку/переключатель:
- Активируется только если у чата есть `campaign_id`
- Визуально отличает режим (иконка, цвет)
- Показывает tooltip с описанием режима
- При включении — отправляет `POST /update-mode/start` с содержимым поля ввода

### 5.3 — UI: DiffBlock компонент

Компонент для отображения одного `ProposedChange`:

```
┌─ notes/session_log.md ─────────────── [update] ─────┐
│ Краткое описание изменения                           │
├──────────────────────────────────────────────────────┤
│ - Удалённый текст (красный фон)                      │
│ + Добавленный текст (зелёный фон)                    │
├──────────────────────────────────────────────────────┤
│ [✓ Принять]  [✗ Отклонить]  [↺ Переформулировать]   │
└──────────────────────────────────────────────────────┘
```

Для diff-рендеринга использовать библиотеку `diff-match-patch` (JS) или
реализовать простой line-diff через `splitLines` + подсветку изменений.

**Rephrase flow**:
1. Кнопка «Переформулировать» открывает inline input
2. Пользователь вводит инструкцию
3. POST `/changes/{id}/action {action: rephrase, instruction: "..."}`
4. DiffBlock обновляется с новым `proposed_content`

### 5.4 — UI: кнопка Apply

Кнопка «Применить подтверждённые изменения»:
- Активна только если есть хотя бы один `accepted` change
- Показывает счётчик: "Принято: N из M"
- При нажатии: POST `/update-mode/apply`
- После успеха: показывает commit sha + message, закрывает review-panel

### 5.5 — UI: предупреждение о большом контексте

Если `context_tokens > 48_000` (75% от лимита) — показывать предупреждение:
"Контекст кампании большой (N токенов). Часть файлов может быть исключена."

---

## Тесты — `rag-backend/app/tests/test_update_mode_sse.py`

```python
async def test_sse_start_emits_events(client, mock_db, mock_redis, mock_llm):
    """SSE /start эмитирует update_mode_started и update_mode_done"""

async def test_sse_error_on_parse_failure(client, mock_llm_bad_json):
    """SSE /start эмитирует update_mode_error если LLM вернул невалидный JSON"""

async def test_sse_context_too_large_warning(client, mock_large_context):
    """SSE /start эмитирует предупреждение если контекст > TOKEN_LIMIT"""
```

---

## Критерий готовности фазы

- [ ] SSE-стриминг генерации правок работает
- [ ] Фронтенд: toggle включается только для чатов с кампанией
- [ ] Фронтенд: DiffBlock рендерит diff корректно
- [ ] Фронтенд: accept/reject/rephrase работают
- [ ] Фронтенд: apply отправляется, показывает commit sha
- [ ] Предупреждение о большом контексте
- [ ] E2E тест: заметка → review → apply → git log показывает коммит
- [ ] `context/frontend.md` обновлён
- [ ] `context/rag-backend-services.md` обновлён
