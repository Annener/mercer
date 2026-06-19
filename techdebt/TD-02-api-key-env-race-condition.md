# TD-02 — Гонка условий при передаче API-ключа через os.environ

**Приоритет:** 🔴 Критический  
**Файл:** `rag-backend/app/services/settings_service.py`, метод `_build_embedding_config`

## Проблема

Расшифрованный API-ключ прокидывается через глобальную переменную окружения:

```python
# Текущий код (ПРОБЛЕМА):
if model.encrypted_api_key:
    api_key_env = "_MERCER_FALLBACK_API_KEY"
    os.environ[api_key_env] = self.decrypt_api_key(model.encrypted_api_key)
```

`_MERCER_FALLBACK_API_KEY` — одна на весь процесс. При конкурентных async-запросах
с разными vault'ами (разные embedding-модели с разными ключами) **один запрос
перезапишет ключ другого** до того, как второй успеет его прочитать.

Дополнительно: ключ остаётся в `os.environ` навсегда после первого вызова — утечка
секрета в адресное пространство процесса.

## Анализ перед исправлением

- [ ] Найти все места чтения `_MERCER_FALLBACK_API_KEY` в кодовой базе
  (`grep -r "_MERCER_FALLBACK_API_KEY"`)
- [ ] Понять, как `EmbeddingModelConfig.api_key_env` используется в embedding-провайдерах
  (`rag-backend/app/providers/embedding/`)
- [ ] Проверить, есть ли у `EmbeddingModelConfig` поле для прямой передачи ключа
  (не через env) или надо добавить
- [ ] Оценить, нужна ли обратная совместимость с env-based конфигами

## Ожидаемое исправление

1. Добавить поле `api_key: str = ""` в `EmbeddingModelConfig`
2. В `_build_embedding_config` передавать расшифрованный ключ напрямую:
   ```python
   return EmbeddingModelConfig(
       ...,
       api_key=self.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else "",
       api_key_env="",
   )
   ```
3. В embedding-провайдерах читать `config.api_key` вместо `os.getenv(config.api_key_env)`
4. Убрать `os.environ[...]` из сервиса

## Риски

Средние — нужно согласованно поменять `EmbeddingModelConfig` + все провайдеры,
читающие ключ. Вероятно затронет `rag-indexer` тоже.
