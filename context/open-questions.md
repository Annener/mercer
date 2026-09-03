# Открытые вопросы и идеи

Документ-аккумулятор открытых мыслей по контекстной подсистеме Mercer. Сюда складываются идеи, баги и направления развития, которые **зафиксированы в коде или в чате, но пока не оформлены как задача или PR**.

Каждый пункт содержит:
- **Контекст** — где идея возникла.
- **Гипотеза / почему это важно** — что именно не так или что хочется улучшить.
- **Что нужно исследовать** — конкретные точки входа в код, чтобы начать работу.

---

## 1. Визуализация фонового поведения модели для пользователя + глобальная настройка drift/draft loop ✅ реализовано

**Контекст:** обсуждение платформы в чате. Текущий drift/draft loop работает всегда после каждого turn-а, если у чата есть `campaign_id`. Пользователь не знает, что происходит в фоне.

**Проблемы:**
- Нет глобальной настройки `platform_settings` для включения/выключения drift loop (сейчас только cooldown через `drift.cooldown_seconds` и пороги `drift.confidence_threshold` / `drift.max_messages`, но **вкл/выкл всего цикла — нет**).
- Пользователь видит карточку `ContextDraftCard` только если polling `GET /api/chats/{id}/context-draft` в `ChatContextBar` сработал. Между «drift заметил расхождение» и «пользователь увидел» может пройти произвольное время.
- Нет визуального индикатора «сейчас в фоне: drift detection / drafting / idle».

**Что нужно исследовать:**
- `rag-backend/app/services/context_engine/loop.py:32-36` — cooldown/dirty ключи в Redis.
- `rag-backend/app/main.py:72-89` — lifespan wiring; добавить ли `drift_loop_enabled: bool` в `app.state`.
- `rag-backend/app/api/chat.py:1130-1135` — точка вызова `drift_loop.trigger_for_chat`. Возможно, пропускать если флаг выключен.
- `rag-backend/app/services/settings_service.py:25-27` — список `platform_settings`; добавить `drift.enabled: bool`, `drift.draft_enabled: bool`.
- `rag-backend/app/static/frontend/src/components/chat/ChatContextBar.tsx` — место для badge «Drift: idle / running / draft ready».
- `rag-backend/app/static/frontend/src/components/chat/ContextDraftCard.tsx` — текущая карточка draft.

**Связанные точки:** SSE-событие `drift_status` (пока не существует) может эмититься из `DriftLoop._run_detect` чтобы UI получил real-time сигнал.

**Реализовано (см. PR):**

| Что | Где |
|---|---|
| Миграция: 3 ключа `drift.enabled` / `drift.detect_enabled` / `drift.draft_enabled` | `rag-backend/migrations/versions/0017_drift_loop_enabled.py` |
| `DriftStatus` + `DriftPhase` модели | `shared_contracts/models.py` |
| In-memory pub/sub + Redis TTL=60с fallback | `rag-backend/app/services/context_engine/status_bus.py` |
| Чтение флагов с TTL-кешем 5 сек и авто-инвалидация при изменении `platform_settings` | `rag-backend/app/services/context_engine/loop.py`, `rag-backend/app/api/settings/params.py` |
| SSE endpoint `GET /api/chats/{id}/events` + poll fallback `GET /api/chats/{id}/drift-status` | `rag-backend/app/api/chat_events.py` |
| Глобальная группа «Drift loop» во вкладке «Параметры» с пояснением | `rag-backend/app/static/frontend/src/components/settings/tabs/ParamsTab.tsx` |
| Стеклянный popup сверху-справа чата (real-time фазы) | `rag-backend/app/static/frontend/src/components/chat/DriftStatusPopup.tsx` |
| Тесты backend (16 шт) + frontend (6 шт) | `tests/unit/rag_backend/test_drift_status_bus.py`, `tests/unit/rag_backend/test_drift_loop_flags.py`, `__tests__/DriftStatusPopup.test.tsx` |

---

## 2. Ускорение обновления контекста

**Контекст:** обсуждение платформы в чате. Текущий drift → draft → review → apply pipeline включает несколько последовательных LLM-вызовов с большими задержками.

**Проблемы (из обсуждения):**
- Cooldown 30 сек + инференс QVikhr (5-15 сек) + инференс большой модели (5-20 сек) + polling на фронте = пользователь видит уведомление о draft через десятки секунд после turn-а.
- Initial State: при >8k токенов большая модель отваливается по таймауту (см. пункт 5).
- Нет background-pipeline, который бы заранее готовил следующий likely state.

**Что нужно исследовать:**
- Можно ли запускать drift detection **во время генерации ответа** основной моделью (параллельно), а не после SSE `final`?
- Стоит ли генерировать draft **инкрементально** (по мере появления новых drift hints), а не пересоздавать целиком?
- Можно ли использовать `temperature=0.1` для QVikhr для ускорения (сейчас 0.3)?
- Кэшировать compiled state block в Redis чтобы не компилировать на каждом turn-е.

**Связанные файлы:**
- `rag-backend/app/services/context_engine/drift.py:51` — `DriftDetector.detect`
- `rag-backend/app/services/context_engine/draft.py:99` — `CampaignStateDrafter.plan_draft`
- `rag-backend/app/services/context_engine/loop.py:42` — `DriftLoop` cooldown/dirty
- `rag-backend/app/services/context_engine/scene_memory.py` — `compose_scene_block` (вызывается на каждом turn-е)

---

## 3. Саммаризация контекста чата, идущая фоном по событиям

**Контекст:** обсуждение платформы в чате. Сейчас нет компрессии/саммаризации истории — все сообщения отправляются в LLM провайдеру как есть, в пределах `max_tokens` провайдера.

**Проблемы:**
- При длинных сессиях контекстное окно заполняется history → state block + scene_state могут не влезть в первые сообщения, и провайдер их обрежет с конца или выкинет из середины.
- Нет сжатия «old tail» истории.
- Нет сохранения важных фактов из истории в state/scene_state (просто `update_scene_state` tool, который модель может забыть вызвать).

**Чиго нужно исследовать:**
- Где сейчас собирается messages list для провайдера? (вероятно, `rag-backend/app/providers/generation/base.py` или `rag-backend/app/api/chat.py:1120+`)
- Что считается «событием» для триггера саммаризации: каждые N сообщений, при превышении threshold по tokens, при archival в `scene_state`?
- Нужна ли отдельная малая модель для саммаризации (та же QVikhr, или отдельная)?
- Куда сохранять результат: новый JSONB `chats.metadata.history_summary`, или старые summary messages в `messages` таблице?

**Связанные файлы:**
- `rag-backend/app/api/chat.py:602-626` — `_maybe_set_title` (похожий fire-and-forget паттерн)
- `rag-backend/app/services/agent_loop.py:559-620` — `_execute_update_scene_state` (host-side merge)
- Возможно: расширение `context_engine/` для `summarizer.py`

---

## 4. Чистка docstring'ов с упоминанием Qwen2.5 (Qwen2.5 → QVikhr)

**Контекст:** обсуждение платформы в чате. Миграция `0016_drift_model_qvikhr` переключила seed drift-модели с Qwen2.5-3B-Instruct на QVikhr-3-1.7B-Instruct-noreasoning. В 4 местах остались устаревшие упоминания Qwen2.5 в комментариях/docstring'ах.

**Что нужно сделать:**
- `pdf-sidecar/app.py:40-45` — переписать блок `v6.0` в changelog-комментарии. Там написано «Qwen2.5-3B-Instruct (Q4_K_M, GGUF)», реальная модель — QVikhr. Либо удалить v6.0 (он не описывает текущее поведение), либо переписать как «Qwen2.5 изначально, потом заменён на QVikhr».
- `pdf-sidecar/drift.py:70` — комментарий в `class DriftHint` «QVikhr-3-1.7B отдаёт msg_ref как int, Qwen2.5 — как str». Убрать упоминание Qwen2.5, оставить про QVikhr.
- `pdf-sidecar/drift.py:214-216` — комментарий «Нормализация: msg_ref может быть int (QVikhr) или str (Qwen2.5)». Убрать упоминание Qwen2.5, оставить суть нормализации int → str. Логика нормализации `if not isinstance(hint.msg_ref, str): hint.msg_ref = str(hint.msg_ref)` (строки 217-218) — **НЕ трогать**, она нужна.
- `tests/unit/pdf_sidecar/test_drift_endpoint.py:209` — test docstring «QVikhr-3-1.7B отдаёт msg_ref как int (Qwen2.5 — str)». Убрать упоминание Qwen2.5.

**НЕ трогать (false positives):**
- `migrations/versions/0016_drift_model_qvikhr.py:35, 44, 45` — упоминание `qwen2.5-3b-instruct-q4_k_m` это часть WHERE-clause для идемпотентности миграции и правильного rollback'а. Это **НЕ мусор, это функциональный код**.
- `rag-indexer/storage/storage_client.py:15` — «Qwen3-4B embedding» относится к embedding-модели в **индексаторе**, не к drift. False positive.
- `rag-backend/app/services/retrieval.py:28, 693, 737` — «Qwen3-Reranker» — это другая модель (реранкер), не drift. False positive.
- `pdf-sidecar/drift.py:160-165` — упоминание QVikhr как текущей модели — корректно.

**Критерий готовности:** `rg -i qwen` в `pdf-sidecar/drift.py`, `pdf-sidecar/app.py`, `tests/unit/pdf_sidecar/test_drift_endpoint.py` возвращает только false positives (Qwen3-Reranker, embedding) либо упоминания QVikhr (текущая модель).

---

## 5. Research: таймауты Initial State (>8k токенов → таймаут)

**Контекст:** обсуждение платформы в чате. При первой генерации контекста кампании (Initial State, `POST /api/settings/campaigns/{id}/state/initial/preview`) при >8k UI-токенов в выбранных файлах генеративная модель отваливается по таймауту.

**Что нужно исследовать (без детального фикса):**
- Соответствие `Document.estimated_tokens` vs реально реконструированного текста через `reconstruct_full_text`. См. `rag-backend/app/services/campaign_state_initial_service.py:946-955` (`_filter_by_per_doc_limit`, `_apply_total_budget`). Фильтры работают по `Document.estimated_tokens`, а user_message строится из `docs_text` после reconstruction. Если оценки в БД устарели, фильтр может пропустить документ, который на самом деле весит 2-3x больше.
- Конкретный таймаут httpx-клиента для активного провайдера. Где он задаётся? См. `rag-backend/app/providers/generation/*` — какой timeout у `OpenAICompatibleProvider`?
- Тип ошибки, которая прилетает пользователю:
  - `asyncio.TimeoutError`?
  - `httpx.TimeoutException`?
  - HTTP `413 Request Entity Too Large` (overflow context_window)?
  - HTTP `504 Gateway Timeout` от прокси?
  - HTTP `429 Too Many Requests`?
- Сколько попыток делает `_call_provider_with_repair_raw` (см. `initial_service.py:1510+`)? Ловит ли он таймауты или только JSON parse errors? Предварительно: `except (ValidationError, ValueError, TypeError)` — **НЕ ловит таймауты**.

**Связанные файлы:**
- `rag-backend/app/services/campaign_state_initial_service.py:1055, 1510-1611` — точка вызова LLM + retry
- `rag-backend/app/services/retrieval.py:42, 206, 226` — `httpx.AsyncClient(timeout=15)` для `reconstruct_full_text`
- `rag-backend/app/providers/generation/openai_compatible.py` — реальный timeout
- `rag-backend/app/services/settings_service.py:25+` — дефолты `pdf_sidecar.timeout_seconds: 180`
- `rag-backend/migrations/versions/0002_watchdog_interval.py` — заполнение `Document.estimated_tokens`

**Критерий готовности (research):**
1. Точный текст ошибки в логах при воспроизведении проблемы.
2. Соответствие `Document.estimated_tokens` vs `len(docs_text[doc_id])` для 5 случайных документов.
3. Реальный timeout httpx-клиента для активного провайдера.
4. Подтверждение/опровержение гипотезы «фильтр пропускает большие документы».

---

## Связь с PR / задачами

Каждый пункт может быть поднят как отдельный PR или как часть Epic «Context Engine Phase 6+».

**Приоритет (на момент создания документа):**
1. Пункт 4 — trivial clean-up, 5 минут.
2. Пункт 5 — research без правок, 1-2 часа на диагностику.
3. ~~Пункт 1 — UX-улучшение, требует дизайна badge/индикатора.~~ ✅ реализовано
4. Пункт 3 — feature, требует дизайна архитектуры саммаризации.
5. Пункт 2 — research + multiple optimizations, может разбиваться на под-PR.
