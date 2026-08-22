# Mercer — Campaign State и управляемый RAG: спецификация реализации

## 1. Назначение

Эта спецификация определяет целевую доработку Mercer: **Campaign State** — компактное, версионируемое и подтверждаемое пользователем состояние конкретной кампании.

Цель — убрать обязательный retrieval из обычного чата. Модель должна получать актуальный state кампании и недавний контекст диалога сразу, а RAG использовать как инструмент только для точных деталей, исходников и фактов, которых нет в доступном контексте.

Это не задача построения общего «AI memory». Campaign State — управляемая пользовательская проекция актуальной ситуации внутри одной кампании.

## 2. Базовая модель контекста

На обычном turn host собирает контекст в следующем порядке:

```text
1. Существующий system prompt домена
2. Active Campaign State выбранной кампании
3. Recent chat history
4. Retrieved evidence — только если модель вызвала retrieval tool
5. Текущее сообщение пользователя
```

### Инварианты

- Существующий domain system prompt не меняется.
- Отдельный mutable Domain State не вводится.
- Campaign State не заменяет RAG.
- Campaign State не индексируется как обычный RAG-документ.
- Chat working memory / chat compaction пока не реализуются.
- В обычном чате RAG не запускается автоматически на каждый turn.

## 3. Границы ответственности

| Слой | Назначение |
|---|---|
| Domain system prompt | Роль, поведение модели и общие правила домена. Существующая система без изменений |
| Campaign State | Подтверждённая актуальная картина конкретной кампании |
| Recent chat history | Недавняя рабочая часть текущего диалога |
| RAG / Vault | Подробные документы, история, доказательства и сведения для конкретного вопроса |
| PDF | Долговременная база знаний для RAG; не источник Campaign State |

## 4. Конфигурация полей Campaign State

Campaign State не имеет глобального фиксированного набора полей вроде `objective`, `decisions` или `risks`.

Пользователь настраивает упорядоченный список полей в настройках конкретной кампании.

### 4.1. Контракт поля

```json
{
  "key": "agreements",
  "label": "Договорённости",
  "description": "Актуальные договорённости по проекту. При наличии фиксируется дата договорённости.",
  "mode": "list",
  "enabled": true
}
```

Обязательные свойства:

- `key` — уникальный стабильный технический идентификатор; immutable после создания;
- `label` — отображаемое пользователю название;
- `description` — семантика поля и критерии включения информации; передаётся LLM во время формирования/обновления state;
- `mode` — `single` или `list`;
- `enabled` — отключённое поле сохраняет историю, но не участвует в prompt и новых patch proposal;
- порядок полей — порядок отображения в UI и compiled Campaign State.

Не добавлять в MVP:

- фиксированные доменные поля;
- `priority`;
- `max_items_in_prompt`;
- `prompt_instruction`;
- сложные типы, entity graph, timeline, relation fields или специализированные редакторы.

### 4.2. Режимы

- `single`: одно актуальное текстовое значение. Примеры: «Текущая локация», «Текущий фокус», «Следующая сцена».
- `list`: независимые текстовые пункты со стабильными идентификаторами. Примеры: «Договорённости», «Активные зацепки», «Открытые вопросы».

## 5. Хранение и версионирование

Источник истины — PostgreSQL. State не хранится как вручную поддерживаемый Markdown-файл.

Нужны как минимум:

- конфигурация полей Campaign State, связанная с кампанией;
- версия конфигурации полей;
- версии state;
- отдельный proposal/patch audit trail;
- status/version для optimistic locking.

Пример логической формы active state:

```json
{
  "state_version": 12,
  "config_version": 3,
  "values": {
    "current_focus": {
      "text": "Спроектировать Campaign State MVP",
      "updated_at": "2026-08-15T01:00:00+05:00",
      "source_refs": ["chat:msg:..." ]
    },
    "agreements": [
      {
        "id": "agreement-01",
        "text": "Campaign State изменяется только после явного review пользователя.",
        "updated_at": "2026-08-15T01:00:00+05:00",
        "source_refs": ["chat:msg:..." ]
      }
    ]
  }
}
```

Конкретные имена таблиц и интеграция с текущей схемой должны следовать существующим conventions репозитория.

## 6. Защита от полной перезаписи

LLM никогда не возвращает Campaign State целиком. Она возвращает только точечные patch-операции относительно `base_state_version`.

### 6.1. Допустимые операции

Для `single`:

```text
replace_single
clear_single
```

Для `list`:

```text
add_list_item
update_list_item
resolve_list_item
remove_list_item
```

### 6.2. Обязательные правила

- Отсутствие операции означает `no-op`, а не удаление.
- Замена целого `list`-поля одной операцией запрещена.
- `update_list_item`, `resolve_list_item`, `remove_list_item` обязаны указывать существующий `item_id`.
- Patch обязан содержать `base_state_version`.
- Patch обязан ссылаться на актуальную версию конфигурации полей.
- Каждая операция содержит `reason` и `source_refs`.
- При несовпадении `base_state_version` применяется rebase/review, но не silent overwrite.
- Сервер валидирует существование/доступность поля, соответствие операции `mode`, принадлежность item кампании и версии state.

## 7. Review и apply

Campaign State меняется **только после явного review и approval пользователя**.

### 7.1. Единый review

Campaign Update Mode формирует один proposal:

```text
FileChangeIntent[]
+ CampaignStatePatchOperation[]
+ questions[]
```

Файловые изменения и state patch показываются вместе, но принимаются независимо.

Поддерживаемый результат:

- принять всё;
- принять только выбранные файловые изменения;
- принять только выбранные state-операции;
- отредактировать конкретную state-операцию;
- отклонить часть или всё.

Частичный apply должен сохраняться как факт. Отклонённые операции не должны предлагаться для повторного применения тем же proposal.

### 7.2. UI review state-операции

Пользователь видит не JSON, а смысловой diff:

```text
Изменить: Текущая локация
Было: Порт Соляных Врат
Станет: Руины маяка на острове Керн
Основание: session-14.md

Добавить: Активная зацепка
Выяснить, кто отправил письмо с печатью Ворона.
Основание: session-14.md
```

Операции удаления/закрытия визуально выделяются и не должны быть выбраны по умолчанию.

## 8. Initial Campaign State

### 8.1. Запуск

После создания кампании пользователь:

1. Создаёт и упорядочивает поля state.
2. Настраивает tags / область источников кампании.
3. Размечает источники.
4. Явно запускает действие «Сформировать начальный контекст».

Для выбора источников нужно переиспользовать существующий режим **«Полные документы»**:

- пользователь вручную выбирает конкретные Markdown-файлы;
- текущий механизм сам показывает/проверяет token count;
- если набор не помещается, пользователь сокращает его;
- не реализовывать batch processing, автоматическое разбиение или многошаговую обработку большого объёма файлов.

### 8.2. Источники

| Source type | RAG | Initial State | Campaign State update |
|---|---:|---:|---:|
| Markdown (`.md`) | Да | Да, при явном выборе пользователя | Да, в Campaign Update Mode |
| PDF | Да | Нет | Нет |

PDF может быть tagged и доступен RAG, но не участвует в формировании или обновлении Campaign State. Добавление/тегирование PDF не создаёт сигнал `potentially_stale`.

### 8.3. Результат

LLM получает:

- конфигурацию полей (`key`, `label`, `description`, `mode`, порядок);
- полные тексты выбранных Markdown-файлов;
- инструкции не выдумывать значения;
- schema initial proposal.

Она возвращает proposal по полям, `source_refs` и вопросы при неоднозначности.

Для каждого поля возможны:

- есть предложенное значение / элементы;
- поле остаётся пустым: нет надёжных данных;
- требуется уточнение: источники противоречат друг другу или данных недостаточно.

До approval существует только initialization proposal. Первая active state version создаётся после review.

Proposal должен ссылаться на конкретные версии выбранных файлов, например `file_id + content_sha`. Если источник поменялся до approval, UI предупреждает, что proposal сформирован на устаревшем source snapshot.

## 9. Campaign Update Mode

Campaign Update Mode — основной и авторитетный путь обновления state.

```text
Пользовательская update-note
  → retrieval по разрешённым Markdown-источникам кампании
  → LLM-анализ
  → file changes + Campaign State patch proposal + questions
  → единый review
  → apply выбранных операций
```

Каждый запуск Update Mode обязан анализировать Campaign State, но patch может быть пустым.

RAG/retrieval в этом режиме обязателен: persistent state patch должен иметь доказательную основу. PDF исключаются из candidate sources данного flow.

## 10. Внешние изменения файлов

При изменении источника вне Mercer, например в Obsidian:

```text
Изменение Markdown
  → detection
  → reindex
  → определить затронутые кампании по tags/source scope
  → пометить Campaign State как potentially_stale
  → показать информационное сообщение
  → пользователь при необходимости запускает Campaign Update Mode
```

Внешняя правка никогда не изменяет Campaign State автоматически.

Ожидаемый UI-смысл:

> В источниках кампании появились обновления. Актуальное состояние кампании может их не учитывать. [Обновить контекст]

PDF не является триггером для этого сценария.

## 11. Компиляция Campaign State в prompt

Host/backend детерминированно компилирует active state в текст по порядку полей.

- Ориентировочный общий budget: до ~800 токенов.
- Не выполнять дополнительный LLM-вызов для summarization/перефразирования state при каждом chat turn.
- Не обрезать текст значения/элемента посередине.
- При превышении бюджета отображать в debug/effective-context view, что вошло, а что исключено.
- Поля `single` включаются как одно значение; элементы `list` — как отдельные записи в порядке их текущего хранения/последнего подтверждённого изменения, согласно финальному решению в коде.

## 12. Conditional и cyclic RAG в чате

Обычный chat turn не должен автоматически выполнять retrieval.

Основная LLM получает tool, например:

```text
search_knowledge(queries[], reason)
```

Host сам фиксирует scope: активная кампания, разрешённые tags и source types. Модель не должна управлять чужими campaign scopes или снимать фильтры.

### 12.1. Правила для модели

Модель использует доступные system prompt, Campaign State и recent chat history.

Она обязана вызвать `search_knowledge`, если ответ зависит от конкретных кампанийских фактов, правил, лора, именованных сущностей, истории, точного содержания документа или деталей, отсутствующих в текущем prompt.

Она не должна:

- заменять отсутствующие кампанийские факты общими знаниями;
- выдумывать лор или правила;
- утверждать, что сведения найдены, если retrieval не дал evidence.

### 12.2. Cyclic retrieval

Нужен bounded agent loop:

```text
LLM
  → search_knowledge(queries[])
  → hybrid retrieval + rerank
  → tool result/evidence
  → LLM отвечает
  ИЛИ формирует дополнительные focused queries
  → повторный retrieval
  → финальный grounded answer / clarification
```

Дефолтные лимиты для реализации:

- обычный чат: до 1 retrieval round;
- grounded campaign knowledge: до 2 rounds;
- не повторять нормализованный одинаковый query;
- ограничивать общий token budget evidence и latency;
- остановить loop, если нет новых релевантных результатов;
- после лимита дать grounded answer с явными пробелами либо задать уточняющий вопрос.

Модель должна иметь возможность сформировать несколько независимых queries одним tool call. Пример для DnD:

```json
{
  "queries": [
    "Изур правила бога для боя запреты благословения ритуалы",
    "водные существа монстры обитают в воде",
    "текущая локация боевой сцены вода окружение угрозы"
  ],
  "reason": "Для боевой сцены нужны правила божества, подходящие существа и ограничения локации."
}
```

После evidence модель либо отвечает, либо формирует новый поиск только по недостающим аспектам.

### 12.3. Retrieval policy

Архитектура должна позволять на уровне домена/кампании задавать policy, но MVP может начать с двух режимов:

- `assistive`: модель сама решает, нужен ли retrieval;
- `grounded`: ответ на кампанийские факты, правила и именованные сущности требует evidence.

Для DnD knowledge-сценариев рекомендуемый default — `grounded`.

## 13. Не входит в текущий scope

- Автоматическое применение persistent Campaign State без review.
- Локальная LLM для patch extraction/analysis.
- Chat compaction, chat summary и отдельная persistent chat working memory.
- Mutable Domain State.
- Изменение domain system prompt.
- Полностью свободная JSON Schema/DB-конструктор.
- Entity graph, timeline и сложные field types.
- Initial state из большого числа документов через batches.
- PDF как источник initial/update Campaign State.

## 14. Рекомендуемый порядок реализации

1. Discovery: подтвердить существующие точки расширения в БД, API, frontend, Update Mode, Full Documents, prompt assembly, RAG/reindex.
2. Campaign State field configuration: schema, migration, API/UI CRUD, ordering, `single/list`.
3. State persistence: versioned state, list item IDs, source refs, optimistic locking, tests.
4. Initial State: reuse Full Documents selection, Markdown-only source snapshot, initialization proposal/review/first active version.
5. Campaign Update Mode: `state_patch` в proposal, unified review, partial apply, audit trail.
6. Prompt assembly: deterministic compiler, token accounting/debug effective context, inject active state.
7. External Markdown changes: `potentially_stale` signal and action; PDF exclusion.
8. Conditional/cyclic RAG: tool schema, agent loop, limits, tracing and integration tests.

Каждый этап должен быть отдельным небольшим набором коммитов с узкими acceptance criteria. Не начинать следующий этап, пока предыдущий не покрыт релевантными тестами и не проверен вручную.

## 15. Acceptance criteria верхнего уровня

- Кампания имеет настраиваемые text fields `single/list` без доменного хардкода.
- Initial state формируется только из явно выбранных Markdown через существующий Full Documents flow и всегда проходит review.
- Поле может остаться пустым.
- State не может быть полностью заменён одним ответом LLM.
- Пользователь может частично принять proposal.
- Внешний Markdown update только делает state potentially stale; PDF не влияет на state flow.
- Обычный чат работает без unconditional retrieval.
- В grounded knowledge-сценарии модель может выполнить до двух итераций поиска и не выдумывает отсутствующий кампанийский лор.
