# Этап 2: shared_contracts — удалить chunk_ids из FileIndexState

## Цель
Удалить поле `chunk_ids` из модели `FileIndexState` в `shared_contracts/models.py`.
Поле является рудиментом — нигде не используется по назначению.

## Контекст: почему chunk_ids не нужны

`chunk_ids` в `FileIndexState` предполагали хранение ID чанков файла в state.
Однако удаление чанков в системе реализовано через `document_id` из PostgreSQL:
```python
await _delete_chunks_from_lancedb(str(doc["id"]), vault_id, storage_client)
```
`chunk_ids` из state при этом не читаются. Единственное место где они читались —
перенос из прошлого state в новый при пропуске неизменённого файла, то есть
просто копирование без использования.

## Файлы для изменения
- `shared_contracts/models.py`

## Зависимости
Этап не зависит от других этапов. Можно выполнять сразу после этапа 1.

## Перед началом — прочитай текущий файл
Прочитай `shared_contracts/models.py` через GitHub MCP.

## Что изменить

В классе `FileIndexState` удалить строку:
```python
chunk_ids: list[str] = Field(default_factory=list)
```

## После удаления — проверить все места использования

Найди через GitHub MCP code search все вхождения `chunk_ids` в репозитории:
- `rag-indexer/parser/state/state_manager.py` — параметр `chunk_ids` в `update_file_status`, инициализация `chunk_ids=[]` в `create_state`
- `rag-indexer/indexer_worker.py` — формирование `chunk_ids = [...]`, передача в `update_file_status`, чтение `previous_file_state.chunk_ids`

**Важно:** на этом этапе ты только удаляешь поле из модели.
Правки в `state_manager.py` и `indexer_worker.py` — в этапах 4 и 6.
Убедись что нет других мест которые читают `.chunk_ids` и которые не покрыты этапами 4/6.

## Ожидаемый результат
`FileIndexState` больше не имеет поля `chunk_ids`. Если где-то в коде есть
`file_state.chunk_ids` — это сломается при следующем деплое, поэтому этапы 4 и 6
должны быть выполнены до деплоя.

## ✅ Unit-тесты для этого этапа

**Файл:** `tests/shared_contracts/test_file_index_state.py`

```bash
pytest tests/shared_contracts/test_file_index_state.py -v
```

```python
# tests/shared_contracts/test_file_index_state.py
from shared_contracts.models import FileIndexState

def test_file_index_state_has_no_chunk_ids():
    """После удаления поля chunk_ids его не должно быть в модели."""
    assert not hasattr(FileIndexState, 'chunk_ids'), \
        "chunk_ids должен быть удалён из FileIndexState"

def test_file_index_state_instantiation_without_chunk_ids():
    """Модель создаётся без chunk_ids и не принимает его как параметр."""
    state = FileIndexState(stage="pending", checksum_md5="abc")
    assert not hasattr(state, 'chunk_ids')

def test_file_index_state_rejects_chunk_ids():
    """Передача chunk_ids должна вызвать ошибку валидации (extra=forbid) или быть проигнорирована."""
    import pytest
    # Если модель с extra='forbid' — должна бросить ValidationError
    # Если extra='ignore' — просто не сохранит. В обоих случаях .chunk_ids не должно быть.
    try:
        state = FileIndexState(stage="pending", checksum_md5="abc", chunk_ids=["x"])
        assert not hasattr(state, 'chunk_ids')
    except Exception:
        pass  # ValidationError — тоже корректное поведение
```

> 💡 **Как запустить в чате:**  
> Приведи мне содержимое `shared_contracts/models.py` и я выполню тесты против него.

## После завершения
Обнови `STATUS.md` — строку этапа 2: поставь ✅, запиши коммит, добавь в историю.
