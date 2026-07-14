# Фаза 3 — Сбор контекста и генерация правок (Executor)

**Цель фазы**: Реализовать `update_mode_executor.py` — сервис, который собирает
`.md`-файлы кампании по тегам, передаёт в LLM и парсит `ProposedChange[]`.
После фазы: при вызове executor возвращает список предложенных правок с диффом.

**Зависимости**: [Фаза 2](phase-2-data-model.md) завершена
**Следующая фаза**: [Фаза 4 — Redis-хранилище и API](phase-4-api.md)

---

## Контекст для чтения

Перед началом работы прочитай:
- `context/rag-backend-services.md` — понять структуру сервисов, как работает
  `full_document_service.py` (аналогичный паттерн чтения файлов)
- `context/shared_contracts.md` — `ProposedChange`, `UpdateModeSession`
- `rag-backend/app/services/full_document_service.py` — переиспользовать
  `reconstruct_full_text()` для чтения содержимого .md файлов
- `rag-backend/app/db/models.py` — Campaign, Tag, Document, DocumentLabel
- `context/api_routes.md` — как устроены роутеры (pattern для нового роутера)

---

## Задачи

### 3.1 — Функция сбора .md-файлов кампании

Создать `rag-backend/app/services/update_mode_executor.py`.

Функция сбора контекста:

```python
async def collect_campaign_md_context(
    db: AsyncSession,
    campaign_id: str,
    vault_id: str,
) -> list[dict]:  # [{file_path, content, document_id, char_count}]
    """
    1. Получить теги кампании (campaign_tags JOIN tags)
    2. Найти документы vault с этими тегами И source_path.endswith('.md')
       (DocumentLabel JOIN Document WHERE vault_id=vault_id AND status='indexed')
    3. Для каждого документа прочитать АКТУАЛЬНЫЙ ФАЙЛ С ДИСКА (не из чанков LanceDB),
       т.к. файл может быть изменён после индексации
    4. Посчитать суммарный объём токенов. Если > TOKEN_LIMIT (64_000) —
       залогировать предупреждение и вернуть только те файлы что укладываются,
       отсортированные по char_count ASC (сначала маленькие)
    5. Вернуть список {file_path, content, document_id, char_count}
    """
```

**Важно**: читать файл с диска через `aiofiles.open(full_path, 'r', encoding='utf-8')`,
а `full_path = vault_path / document.source_path`.

### 3.2 — Системный промпт для Update Mode

Создать `rag-backend/app/services/update_mode_prompts.py` или добавить константу
в executor:

```
UPDATE_MODE_SYSTEM_PROMPT = """
You are a context maintenance assistant for a campaign knowledge base.
You will receive:
1. A user note containing new information (session events, decisions, character updates, etc.)
2. A list of markdown files from the campaign context

Your task:
- Analyze the note and identify what information should be reflected in the markdown files
- For each file that needs updating, produce the COMPLETE updated content
- If new information doesn't fit any existing file, propose creating a new markdown file
- PDF files and large reference documents are NOT part of your scope

Respond ONLY with a JSON array of proposed changes:
[
  {
    "file_path": "relative/path.md",
    "action": "update" or "create",
    "description": "Brief description of what changed and why",
    "proposed_content": "FULL new content of the file"
  }
]

Rules:
- Propose changes only where genuinely needed
- Keep descriptions concise (1-2 sentences)
- For 'create', file_path should be a logical new filename in the vault
- Respond with JSON only, no markdown code blocks, no explanation outside JSON
"""
```

### 3.3 — Функция генерации правок

```python
async def generate_proposed_changes(
    note: str,
    md_files: list[dict],  # из collect_campaign_md_context
    generation_model,      # GenerationModel или провайдер
) -> list[ProposedChange]:
    """
    Формирует промпт:
      system: UPDATE_MODE_SYSTEM_PROMPT
      user: f"Note:\n{note}\n\n" + форматированный список md_files
    
    Вызывает LLM с JSON-mode (если доступен) или парсит JSON из ответа.
    Парсит ответ в list[ProposedChange].
    
    При ошибке парсинга: логировать raw response и raise UpdateModeParseError.
    """
```

Форматирование md_files для промпта:
```
=== FILE: notes/session_log.md ===
<current content>
=== END FILE ===

=== FILE: lore/characters.md ===
<current content>
=== END FILE ===
```

### 3.4 — Функция rephrase одной правки

```python
async def rephrase_proposed_change(
    change: ProposedChange,
    instruction: str,
    original_note: str,
    generation_model,
) -> ProposedChange:
    """
    Передаёт в LLM:
    - original_note
    - original_content файла
    - текущий proposed_content
    - instruction пользователя
    
    Получает новый proposed_content.
    Возвращает новый ProposedChange с тем же change_id и status=pending.
    """
```

### 3.5 — Функция генерации commit message

```python
async def generate_commit_message(
    accepted_changes: list[ProposedChange],
    original_note: str,
    generation_model,
) -> str:
    """
    Генерирует осмысленный git commit message по принятым правкам.
    Формат: 'campaign(scope): description'
    Fallback если LLM недоступен: 'campaign: update context from user notes'
    Длина: не более 72 символов.
    """
```

---

## Тесты — `rag-backend/app/tests/test_update_mode_executor.py`

```python
async def test_collect_campaign_md_context_filters_by_tags(mock_db):
    """Возвращает только .md файлы с тегами кампании, не PDF"""

async def test_collect_campaign_md_context_token_limit(mock_db, tmp_path):
    """При превышении 64K токенов — обрезает список, логирует предупреждение"""

async def test_generate_proposed_changes_parses_json(mock_llm):
    """Корректно парсит JSON-ответ LLM в list[ProposedChange]"""

async def test_generate_proposed_changes_invalid_json(mock_llm):
    """При невалидном JSON ответе — raise UpdateModeParseError"""

async def test_rephrase_preserves_change_id(mock_llm):
    """rephrase_proposed_change сохраняет change_id и сбрасывает status в pending"""

async def test_generate_commit_message_format(mock_llm):
    """Генерирует сообщение не длиннее 72 символов"""

async def test_generate_commit_message_fallback():
    """При недоступном LLM возвращает fallback строку"""
```

---

## Критерий готовности фазы

- [ ] `update_mode_executor.py` создан
- [ ] `collect_campaign_md_context` корректно фильтрует по тегам и расширению `.md`
- [ ] Системный промпт написан и протестирован на реальной модели вручную
- [ ] Парсинг JSON-ответа LLM надёжен (обработка ошибок)
- [ ] `rephrase_proposed_change` работает
- [ ] `generate_commit_message` работает с fallback
- [ ] Все тесты фазы 3 проходят
