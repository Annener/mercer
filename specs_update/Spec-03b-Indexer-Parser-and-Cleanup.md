# Spec-03b: Indexer Parser and Cleanup

Перед выполнением прочитай `Spec-00-Architecture-Overview.md` и `Spec-03a`. Этот Spec завершает миграцию индексера.

**Зависит от:** `Spec-03a` (создан `db_client.py`, `indexer_worker.py` обновлён).

**Цель:** Обновить `pdf_parser.py` для чтения URL и таймаутов из `platform_settings`, добавить fallback на pdfminer, удалить `binding_manager.py` и все его импорты, добавить механизм отката при частичной индексации.

## Контекст

**Прочитать перед реализацией:**
- `rag-indexer/parser/parsing/pdf_parser.py`
- `rag-indexer/parser/parsing/md_parser.py` (не требует изменений, но проверить)
- `rag-indexer/storage/binding_manager.py` — будет полностью удалён
- `rag-indexer/indexer_worker.py` — уже обновлён в Spec-03a, но нужно добавить откат
- `rag-indexer/app/db_client.py` — создан в Spec-03a

## Задачи

### 1. Обновить `parser/parsing/pdf_parser.py`

**Убрать чтение переменных окружения:** `PDF_SIDECAR_URL`, `PDF_SIDECAR_TIMEOUT` и т.д.

**Новая сигнатура функции `parse_pdf`:**

```python
def parse_pdf(
    file_path: str,
    sidecar_url: str,
    timeout_seconds: float = 180.0,
    fallback_to_pdfminer: bool = True,
) -> dict[str, Any]:
    """
    Парсит PDF через sidecar, при недоступности или ошибке
    и fallback_to_pdfminer=True использует встроенный pdfminer.
    """
```

**Логика:**
1. Попытаться выполнить POST-запрос к `{sidecar_url}/parse/stream` (NDJSON) с таймаутом `timeout_seconds`.
2. Если запрос успешен — обработать NDJSON, вернуть результат.
3. Если запрос не удался (ConnectionError, Timeout, HTTP 5xx) и `fallback_to_pdfminer == True`:
   - Залогировать `WARNING: "PDF sidecar unavailable, falling back to pdfminer for {file_path}"`.
   - Вызвать `_parse_with_pdfminer(file_path)` (реализовать простой парсер на `pdfminer.six` — возвращает словарь с ключами `pages` и `metadata`).
4. Если fallback выключен или pdfminer тоже упал — поднять исключение.

**Функция `_parse_with_pdfminer` (упрощённая):**
- Использовать `PDFPage.get_pages()`, извлекать текст через `PDFResourceManager` и `TextConverter`.
- Возвращать `{"pages": [{"page_number": i+1, "text": text}], "metadata": {"source": file_path, "parser": "pdfminer"}}`.

### 2. Обновить `indexer_worker.py` (добавить откат при частичной индексации)

В Spec-03a уже был добавлен вызов `update_vault_chunk_count(vault_id, len(chunk_ids))` при успехе. Теперь нужно добавить обработку фатальной ошибки после того, как часть чанков уже загружена в LanceDB.

**В функции `_process_file` (или в `run_indexing`, где обрабатываются файлы):**

```python
uploaded_document_ids = []  # список document_id, успешно загруженных в текущей сессии

try:
    # ... индексация файла, в конце storage_client.upsert()
    uploaded_document_ids.append(document_id)
    await db_client.update_vault_chunk_count(vault_id, len(chunk_ids))
except Exception as e:
    # Откат: удалить все документы, добавленные в этой сессии
    if uploaded_document_ids:
        logger.warning(f"Partial indexing detected. Rolling back documents: {uploaded_document_ids}")
        for doc_id in uploaded_document_ids:
            try:
                await storage_client.delete_document(doc_id, vault_id)
            except Exception as delete_err:
                logger.critical(f"Failed to rollback document {doc_id}: {delete_err}")
    raise  # перебросить исключение дальше
```

**Важно:** откат должен происходить только для документов, добавленных в **текущем запуске** индексации. Для этого в `run_indexing` нужно поддерживать список `uploaded_document_ids` на уровне задачи (например, передавать его в `_process_file` по ссылке).

### 3. Полностью удалить `storage/binding_manager.py`

- Удалить файл `rag-indexer/storage/binding_manager.py`.
- Найти все импорты этого модуля в `rag-indexer` (должны быть только в `indexer_worker.py`, но после Spec-03a их уже нет). Использовать поиск по репозиторию: `grep -r "binding_manager" rag-indexer/`.
- Убедиться, что нигде не осталось вызовов `create_or_get_binding`, `increment_chunk_count`, `lock_binding`. Заменить на вызовы `db_client`.

### 4. Обновить `docker-compose.yml` (уже частично в Spec-01)

Проверить, что для `rag-indexer` добавлены переменные окружения:
- `STORAGE_API_URL=http://db-api-server:8080` (используется в `storage_client.py`, который читает из `os.getenv("STORAGE_API_URL")` — нужно убедиться, что `storage_client.py` обновлён для чтения этой переменной, а не старой `STORAGE_API_URL` или `DB_API_URL`).
- `PDF_SIDECAR_URL` больше не нужна, но её можно оставить для обратной совместимости, однако основной источник — `platform_settings`.

### 5. Удалить `rag-backend/app/config_loader.py`

- Удалить файл `rag-backend/app/config_loader.py`.
- Убедиться, что в `rag-backend` нет импортов этого модуля (они были удалены в Spec-02a/b/c).

## Финальный контракт

- `pdf_parser.py` использует параметры из `platform_settings` (sidecar URL, таймаут, fallback).
- При недоступности sidecar и `fallback_to_pdfminer=True` используется встроенный pdfminer.
- `binding_manager.py` удалён, все его функции заменены на `db_client`.
- Реализован откат при частичной индексации (удаление документов, добавленных в текущей сессии, при ошибке).
- `config_loader.py` удалён из `rag-backend`.

## Критерии приёмки

- [ ] `pdf_parser.parse_pdf()` принимает `sidecar_url`, `timeout_seconds`, `fallback_to_pdfminer`.
- [ ] При недоступном sidecar и `fallback_to_pdfminer=True` используется pdfminer, лог `WARNING`.
- [ ] При недоступном sidecar и `fallback_to_pdfminer=False` бросается исключение.
- [ ] Файл `rag-indexer/storage/binding_manager.py` удалён.
- [ ] В `rag-indexer` нет импортов `binding_manager` (проверка через `grep`).
- [ ] При фатальной ошибке после успешной загрузки части чанков вызывается `storage_client.delete_document` для каждого загруженного документа.
- [ ] `rag-backend/app/config_loader.py` удалён.
- [ ] `rag-indexer` запускается и индексирует PDF без переменной окружения `PDF_SIDECAR_URL` (использует значение из `platform_settings`).
