# Фаза 4 — Redis-хранилище и API роутер

**Цель фазы**: Реализовать Redis-хранилище для pending changes и HTTP-роутер
`/chats/{chat_id}/update-mode/`. После фазы: полная backend-часть работает
через API без фронтенда (проверяется curl).

**Зависимости**: [Фаза 3](phase-3-executor.md) завершена
**Следующая фаза**: [Фаза 5 — SSE и стриминг](phase-5-sse.md)

---

## Контекст для чтения

Перед началом работы прочитай:
- `context/api_routes.md` — существующие роутеры, pattern регистрации
- `context/rag-backend-services.md` — как используется Redis в других сервисах
- `context/shared_contracts.md` — `UpdateModeSession`, `ProposedChange`,
  `UpdateModeStartRequest`, `UpdateModeChangeAction`, `UpdateModeApplyRequest`
- `rag-backend/app/main.py` — как подключается Redis
- Фазы 1–3 (все уже реализованы)

---

## Задачи

### 4.1 — Redis-хранилище сессий update-mode

Создать `rag-backend/app/services/update_mode_store.py`:

```python
UPDATE_MODE_TTL = 3600  # секунд
UPDATE_MODE_KEY = "update_mode:{chat_id}"

class UpdateModeStore:
    def __init__(self, redis_client):
        self._redis = redis_client

    async def save(self, session: UpdateModeSession) -> None:
        key = UPDATE_MODE_KEY.format(chat_id=session.chat_id)
        await self._redis.setex(key, UPDATE_MODE_TTL, session.model_dump_json())

    async def load(self, chat_id: str) -> UpdateModeSession | None:
        key = UPDATE_MODE_KEY.format(chat_id=chat_id)
        data = await self._redis.get(key)
        if data is None:
            return None
        return UpdateModeSession.model_validate_json(data)

    async def delete(self, chat_id: str) -> None:
        key = UPDATE_MODE_KEY.format(chat_id=chat_id)
        await self._redis.delete(key)

    async def update_change_status(
        self, chat_id: str, change_id: str,
        status: Literal["accepted", "rejected"]
    ) -> UpdateModeSession | None:
        """Загружает сессию, обновляет статус одного change, сохраняет обратно."""
```

### 4.2 — Роутер `update_mode.py`

Создать `rag-backend/app/api/update_mode.py` (или в соответствующей структуре api-роутеров).

**Эндпоинты**:

```
POST   /chats/{chat_id}/update-mode/start
  Body: UpdateModeStartRequest {note: str}
  → Включает update_mode_enabled в БД
  → collect_campaign_md_context
  → generate_proposed_changes
  → Сохраняет UpdateModeSession в Redis
  → Возвращает UpdateModeSession (без original_content для экономии payload)

GET    /chats/{chat_id}/update-mode/session
  → Возвращает текущую UpdateModeSession из Redis
  → 404 если сессии нет

POST   /chats/{chat_id}/update-mode/changes/{change_id}/action
  Body: UpdateModeChangeAction {action, instruction?}
  action=accept  → status=accepted
  action=reject  → status=rejected
  action=rephrase → rephrase_proposed_change → обновить в Redis
  → Возвращает обновлённый ProposedChange

POST   /chats/{chat_id}/update-mode/apply
  Body: UpdateModeApplyRequest {commit_message?}
  → Берёт accepted changes из Redis
  → snapshot_commit если dirty
  → Записывает файлы на диск
  → generate_commit_message если commit_message не передан
  → apply_commit
  → Сбрасывает update_mode_enabled в БД
  → Удаляет сессию из Redis
  → Возвращает {applied_count, commit_sha, commit_message}

DELETE /chats/{chat_id}/update-mode/session
  → Отменить сессию (reject all + delete Redis)
  → Сбросить update_mode_enabled в БД
```

### 4.3 — Регистрация роутера

Добавить роутер в `rag-backend/app/main.py` или в агрегирующий файл роутеров.

### 4.4 — Проверка прав доступа к chat

Во всех эндпоинтах update-mode проверять:
- chat существует в БД
- chat.campaign_id не None (update-mode требует кампании)
- Если кампании нет — 422 с понятным сообщением

---

## Тесты — `rag-backend/app/tests/test_update_mode_api.py`

```python
async def test_start_update_mode_no_campaign(client, mock_db):
    """POST /start для чата без кампании → 422"""

async def test_start_update_mode_creates_session(client, mock_db, mock_redis, mock_llm):
    """POST /start создаёт сессию в Redis и возвращает изменения"""

async def test_accept_change(client, mock_redis):
    """POST /changes/{id}/action {action=accept} → status=accepted"""

async def test_reject_change(client, mock_redis):
    """POST /changes/{id}/action {action=reject} → status=rejected"""

async def test_rephrase_change(client, mock_redis, mock_llm):
    """POST /changes/{id}/action {action=rephrase, instruction=...} → новый proposed_content"""

async def test_apply_writes_files(client, mock_redis, mock_db, tmp_path, mock_git):
    """POST /apply записывает файлы и вызывает apply_commit"""

async def test_apply_only_accepted(client, mock_redis, tmp_path, mock_git):
    """POST /apply применяет только accepted, игнорирует pending/rejected"""

async def test_apply_clears_session(client, mock_redis, mock_db, mock_git):
    """После apply: сессия в Redis удалена, update_mode_enabled = False"""

async def test_get_session_not_found(client):
    """GET /session без активной сессии → 404"""
```

---

## Критерий готовности фазы

- [ ] `update_mode_store.py` реализован
- [ ] Роутер `update_mode.py` реализован со всеми 5 эндпоинтами
- [ ] Роутер зарегистрирован в app
- [ ] Все эндпоинты проверены через curl вручную
- [ ] Все тесты фазы 4 проходят
- [ ] `context/api_routes.md` обновлён — добавлены новые эндпоинты
