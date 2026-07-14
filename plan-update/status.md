# Campaign Update Mode — Статус выполнения плана

Обновляй этот файл после завершения каждой задачи или фазы.
Формат: `[x]` — выполнено, `[ ]` — не выполнено, `[~]` — в процессе.

---

## Общий прогресс

| Фаза | Статус | Дата завершения | Примечания |
|---|---|---|---|
| Фаза 1 — Git-инфраструктура | `[ ]` не начата | — | — |
| Фаза 2 — Модель данных | `[ ]` не начата | — | — |
| Фаза 3 — Executor | `[ ]` не начата | — | — |
| Фаза 4 — Redis и API | `[ ]` не начата | — | — |
| Фаза 5 — SSE и фронтенд | `[ ]` не начата | — | — |

---

## Фаза 1 — Git-инфраструктура

- [ ] 1.1 — `vault_git_service.py` создан
- [ ] 1.2 — `AppConfig`: `git_author_name`, `git_author_email` добавлены
- [ ] 1.3 — Lifespan: `init_all_vaults` вызывается при старте
- [ ] 1.4 — Создание нового vault: `ensure_repo` вызывается
- [ ] Тесты `test_vault_git_service.py` — все проходят

**Итог фазы**: *(заполнить после завершения)*

---

## Фаза 2 — Модель данных

- [ ] 2.1 — ORM `Vault`: поля `versioned_extensions`, `git_author_name`, `git_author_email`
- [ ] 2.2 — ORM `Chat`: поле `update_mode_enabled`
- [ ] 2.3 — Alembic-миграция создана и применена
- [ ] 2.4 — `ProposedChange`, `UpdateModeSession`, `UpdateModeStartRequest`,
  `UpdateModeChangeAction`, `UpdateModeApplyRequest` добавлены в shared_contracts
- [ ] 2.5 — `VaultRead`, `VaultUpdate`, `ChatRecord` обновлены
- [ ] Тесты `test_update_mode_models.py` — все проходят
- [ ] `context/shared_contracts.md` обновлён
- [ ] `context/db_schema.md` обновлён

**Итог фазы**: *(заполнить после завершения)*

---

## Фаза 3 — Executor

- [ ] 3.1 — `collect_campaign_md_context` реализована
- [ ] 3.2 — Системный промпт написан
- [ ] 3.3 — `generate_proposed_changes` реализована
- [ ] 3.4 — `rephrase_proposed_change` реализована
- [ ] 3.5 — `generate_commit_message` реализована
- [ ] Системный промпт проверен вручную на реальной модели
- [ ] Тесты `test_update_mode_executor.py` — все проходят

**Итог фазы**: *(заполнить после завершения)*

---

## Фаза 4 — Redis и API

- [ ] 4.1 — `update_mode_store.py` реализован
- [ ] 4.2 — Роутер `update_mode.py` реализован (5 эндпоинтов)
- [ ] 4.3 — Роутер зарегистрирован в app
- [ ] 4.4 — Проверка campaign_id реализована
- [ ] Ручная проверка всех эндпоинтов через curl
- [ ] Тесты `test_update_mode_api.py` — все проходят
- [ ] `context/api_routes.md` обновлён

**Итог фазы**: *(заполнить после завершения)*

---

## Фаза 5 — SSE и фронтенд

- [ ] 5.1 — SSE-стриминг генерации правок
- [ ] 5.2 — UI toggle включён только для чатов с кампанией
- [ ] 5.3 — DiffBlock компонент
- [ ] 5.4 — Кнопка Apply с commit sha
- [ ] 5.5 — Предупреждение о большом контексте
- [ ] E2E проверка: заметка → review → apply → git log
- [ ] Тесты `test_update_mode_sse.py` — все проходят
- [ ] `context/frontend.md` обновлён
- [ ] `context/rag-backend-services.md` обновлён

**Итог фазы**: *(заполнить после завершения)*

---

## Известные проблемы / решения

*(добавлять сюда нестандартные решения, отступления от плана и причины)*

---

## Последнее обновление

Дата: 2026-07-14  
Автор обновления: *(ИИ-ассистент или Сергей)*  
Активная фаза: **Фаза 1**
