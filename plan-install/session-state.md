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

## В работе

Ничего.

## Ещё не начато

- C1, C2
- D1, D2, D3

## Задача на следующую сессию

Блок C — мультиплатформенный `agent-setup` в Makefile:
- C1: диспетчер `_agent-setup-dispatch`; текущий `agent-setup` → `_agent-setup-launchd`; Linux → Docker Compose; Windows → предупреждение
- C2: `HOST_AGENT_TOKEN` из `.env` подставляется в plist-шаблон через `_render-plist`

Перед началом прочитать `plan-install/block-C.md`.

## Заметки / контекст

### block-C.md — что ожидается

См. `plan-install/block-C.md`. Ключевые детали:
- macOS: launchd (текущая логика, переименовать цель)
- Linux: host-agent запускается в Docker Compose (отдельный сервис или отдельный compose-файл)
- Windows: только `echo` с предупреждением, exit 0
- `HOST_AGENT_TOKEN` должен читаться из `.env` и подставляться в plist через sed в `_render-plist`
