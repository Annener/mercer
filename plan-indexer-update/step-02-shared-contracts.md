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

## После завершения
Обнови `STATUS.md` — этап 2 → ✅.
