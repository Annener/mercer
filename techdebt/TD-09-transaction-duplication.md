# TD-09 — Дублирование _transaction() в сервисах

**Приоритет:** 🟠 Структурный  
**Файлы:**
- `rag-backend/app/services/settings_service.py`
- `rag-backend/app/services/domain_service.py`

## Проблема

Один и тот же `@asynccontextmanager async def _transaction(self, db)` скопирован
дословно в оба сервиса. Вероятно, он также есть в других сервисах.

При изменении логики транзакций (например, добавление savepoint или логирования)
нужно менять во всех местах.

## Анализ перед исправлением

- [ ] Поиск по проекту: `def _transaction` — сколько копий существует?
- [ ] Проверить, отличаются ли копии между собой (могут быть небольшие вариации)
- [ ] Определить подходящее место для shared-утилиты:
  `rag-backend/app/db/utils.py` или `rag-backend/app/utils/db.py`
- [ ] Убедиться, что нет круговых импортов при выносе

## Ожидаемое исправление

Вынести в `app/db/utils.py`:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession

@asynccontextmanager
async def transactional(db: AsyncSession) -> AsyncIterator[None]:
    if db.in_transaction():
        try:
            yield
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    else:
        async with db.begin():
            yield
```

В сервисах заменить `self._transaction(db)` на `transactional(db)`,
удалить приватные методы.

## Риски

Низкие. Поведение идентично, меняется только место хранения.
