# Состояние текущей сессии

> Этот файл — единственное, что нужно обновлять перед каждой новой сессией.
> Промт (`session-prompt.md`) остаётся неизменным — он читает этот файл.

---

## Выполненные шаги

- A1: удалены мёртвые volumes `./state` и `./cache/embeddings` у `rag-indexer`
- A2: `DATABASE_URL` в `rag-indexer` и `rag-backend` теперь собирается из компонентов
- A3: добавлены `profiles` (with-db-api / core / db-api-only) во все сервисы
- A4: `state_manager.py` и `embedding/cache.py` — подтверждено отсутствие в репо (grep пустой, файлы уже не существовали)
- A5: `.env.example` приведён к целевому виду
- B1–B5: `scripts/generate_env.py` реализован полностью; `init-env` добавлен в Makefile первым шагом `setup` (коммит 80f2555)
- C1: диспетчер `_agent-setup-dispatch`; `agent-setup` → `_agent-setup-launchd`; Linux → Docker Compose; Windows → предупреждение (коммит 738fca1)
- C2: `HOST_AGENT_TOKEN` подставляется в plist через `_render-plist`; шаблон обновлён (коммит 07f252a)

## В работе

Ничего.

## Ещё не начато

- D1, D2, D3

## Задача на следующую сессию

Блок D — проверка и завершение:
- D1, D2, D3

Перед началом прочитать `plan-install/block-D.md`.

## Заметки / контекст

### Изменения блока C

- `setup` теперь: `init-env _agent-setup-dispatch up seed`
- `agent-setup` — публичный алиас на `_agent-setup-dispatch`
- `_agent-setup-dispatch` читает `AGENT_MODE` из `.env`:
  - `host` → `_agent-setup-launchd` (macOS, launchd)
  - `docker` → echo (пропуск, Linux Docker Compose)
  - прочее → WARNING, exit 0 (Windows)
- `HOST_AGENT_TOKEN` читается из `.env` и подставляется в plist через sed в `_render-plist`
- Порядок: `init-env` → `_agent-setup-dispatch` — строго соблюдать
