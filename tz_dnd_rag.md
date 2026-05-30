# ТЗ: RAG-система для настольных RPG (DnD Assistant)

## Обзор системы

Локальный single-user инструмент для мастера настольных ролевых игр. Система индексирует документы (правила, лор, логи сессий) в единый Vault, позволяет вести диалог с AI на основе этих документов, и поддерживает гибкую организацию контента через теги и кампании.

---

## Схема базы данных

### Таблица `tags`

```sql
tags (
  id          UUID PRIMARY KEY,
  name        VARCHAR NOT NULL,
  vault_id    UUID NOT NULL,
  campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
  color       VARCHAR,
  created_at  TIMESTAMP DEFAULT now()
)
```

- `campaign_id = NULL` — глобальный тег, виден всегда
- `campaign_id != NULL` — тег принадлежит кампании, создаётся из интерфейса кампании

### Таблица `campaigns`

```sql
campaigns (
  id              UUID PRIMARY KEY,
  name            VARCHAR NOT NULL,
  vault_id        UUID NOT NULL,
  tag_id          UUID REFERENCES tags(id),   -- дефолтный тег кампании
  system_prompt   TEXT,                        -- контекст для AI
  description     TEXT,
  created_at      TIMESTAMP DEFAULT now(),
  last_session_at TIMESTAMP
)
```

- При создании кампании автоматически создаётся тег с тем же именем, `tag_id` указывает на него
- В переключателе чата отображаются все записи из этой таблицы + опция "Общий"

### Таблица `documents`

```sql
documents (
  id          UUID PRIMARY KEY,
  vault_id    UUID NOT NULL,
  source_path VARCHAR NOT NULL,
  title       VARCHAR,
  md5         VARCHAR NOT NULL,
  mtime       BIGINT NOT NULL,
  indexed_at  TIMESTAMP,
  status      VARCHAR DEFAULT 'pending'  -- pending | indexed | error
)
```

### Таблица `document_labels`

```sql
document_labels (
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  tag_id      UUID REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (document_id, tag_id),
  INDEX (tag_id)
)
```

Один документ может иметь произвольное количество тегов — глобальных и принадлежащих любым кампаниям одновременно.

### Таблица `pipelines`

```sql
pipelines (
  id         UUID PRIMARY KEY,
  name       VARCHAR NOT NULL,
  vault_id   UUID NOT NULL,
  created_at TIMESTAMP DEFAULT now()
)
```

### Таблица `pipeline_steps`

```sql
pipeline_steps (
  id          UUID PRIMARY KEY,
  pipeline_id UUID REFERENCES pipelines(id) ON DELETE CASCADE,
  type        VARCHAR NOT NULL,  -- 'retrieval' | 'final'
  position    INTEGER NOT NULL,
  prompt      TEXT,
  top_k       INTEGER DEFAULT 5,
  is_final    BOOLEAN DEFAULT false
)
```

- Шаг с `is_final = true` — один обязательный финальный шаг на пайплайн, не имеет тегов, оперирует результатами всех ретривал-шагов
- Все ретривал-шаги выполняются **параллельно**, результаты передаются в финальный шаг

### Таблица `pipeline_step_tags`

```sql
pipeline_step_tags (
  step_id UUID REFERENCES pipeline_steps(id) ON DELETE CASCADE,
  tag_id  UUID REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (step_id, tag_id)
)
```

Логика выборки: `WHERE tag_id IN (...)` — оператор **OR** (документ попадает если имеет хотя бы один из указанных тегов).

### Таблица `pipeline_labels`

```sql
pipeline_labels (
  pipeline_id UUID REFERENCES pipelines(id) ON DELETE CASCADE,
  tag_id      UUID REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (pipeline_id, tag_id)
)
```

Теги пайплайна определяют его видимость в UI: пайплайн отображается если выбранная кампания содержит хотя бы один совпадающий тег, либо если у пайплайна нет тегов (виден всегда).

### Таблица `threads`

```sql
threads (
  id          UUID PRIMARY KEY,
  vault_id    UUID NOT NULL,
  campaign_id UUID REFERENCES campaigns(id),  -- NULL = общий режим
  title       VARCHAR,
  created_at  TIMESTAMP DEFAULT now()
)
```

### Таблица `messages`

```sql
messages (
  id          UUID PRIMARY KEY,
  thread_id   UUID REFERENCES threads(id) ON DELETE CASCADE,
  role        VARCHAR NOT NULL,  -- 'user' | 'assistant'
  content     TEXT NOT NULL,
  pipeline_id UUID REFERENCES pipelines(id),  -- какой пайплайн использовался
  created_at  TIMESTAMP DEFAULT now()
)
```

---

## Логика индексации

### Запуск индексации

Пользователь запускает вручную через UI. Индексация инкрементальная.

### Алгоритм

```
для каждого файла в ФС Vault:
  вычислить md5 + mtime
  если документ не существует в БД → создать, индексировать
  если md5 или mtime изменились → переиндексировать
  иначе → пропустить
```

### Состояния документа (`status`)

| Статус | Описание |
|--------|----------|
| `pending` | Добавлен в БД, ещё не обработан |
| `indexed` | Чанки записаны в LanceDB |
| `error` | Ошибка при индексации, требует внимания |

---

## Логика ретривала

### Режим "Общий" (campaign_id = NULL)

```sql
-- Поиск по всему Vault без фильтрации по тегам
SELECT * FROM lancedb WHERE vault_id = :vault_id
ORDER BY vector_distance
LIMIT :top_k
```

### Режим кампании (campaign_id != NULL, пайплайн не выбран)

```sql
-- Ретривал по дефолтному тегу кампании
SELECT d.id FROM documents d
JOIN document_labels dl ON d.id = dl.document_id
WHERE dl.tag_id = :campaign_default_tag_id
```

### Пайплайн активирован

Каждый ретривал-шаг выполняется параллельно:

```sql
-- Шаг N: теги шага = [tag_id_1, tag_id_2, ...]
SELECT d.id FROM documents d
JOIN document_labels dl ON d.id = dl.document_id
WHERE dl.tag_id IN (:step_tag_ids)  -- логика OR
```

Результаты всех шагов дедуплицируются по `document_id`, передаются в финальный шаг вместе с историей диалога.

---

## Логика чата

### Переключатель кампаний

- Отображается в шапке окна чата
- Варианты: **"Общий"** + все записи из таблицы `campaigns`
- Переключение кампании доступно **только при создании нового треда**
- В уже открытом треде кампания заблокирована (отображается, но не кликабельна)

### Переключение пайплайна

- Доступно в любой момент в рамках треда
- При смене пайплайна следующее сообщение обрабатывается уже новым пайплайном
- В `messages` записывается `pipeline_id` который использовался для этого конкретного ответа

### Отображение пайплайнов в UI

```
Выбрана кампания X:
  Показать пайплайны где:
    pipeline не имеет тегов (pipeline_labels пуст)  →  виден всегда
    ИЛИ pipeline имеет тег принадлежащий кампании X →  виден

Выбран "Общий" режим:
  Показать только пайплайны без тегов
```

### Формирование промпта

| Ситуация | Промпт |
|----------|--------|
| Нет пайплайна, есть кампания | `campaign.system_prompt` + контекст из ретривала |
| Нет пайплайна, общий режим | Только контекст из ретривала |
| Пайплайн активирован | Промпты шагов + финальный промпт пайплайна |

---

## Управление тегами

### Создание тегов

| Откуда | Результат |
|--------|-----------|
| Интерфейс кампании | `tag.campaign_id = campaign.id` — тег принадлежит кампании |
| Окно разметки файлов | `tag.campaign_id = NULL` — глобальный тег |

### Окно разметки файлов

Теги отображаются сгруппированно:

```
Глобальные теги
  [rules]  [master_help]  [generator]

Кампания: planar_adventure
  [world_lore]  [session_logs]  [npcs]

Кампания: forgotten_realms
  [timeline]  [factions]
```

- Поддерживается множественный выбор файлов → массовая разметка
- Создание тега из этого окна всегда создаёт глобальный тег

---

## Управление кампаниями

### Создание кампании

1. Пользователь вводит имя
2. Система автоматически создаёт тег с тем же именем (`campaign_id = campaign.id`)
3. `campaigns.tag_id` указывает на созданный тег
4. Кампания появляется в переключателе чата

### Интерфейс кампании

- Поля: имя, описание, системный промпт, дата последней сессии
- Секция "Теги кампании": список тегов с `campaign_id = this.id` + кнопка создания нового
- Дефолтный тег отмечен отдельно, не удаляется

---

## Управление пайплайнами

### Структура пайплайна

```
Pipeline
  └── Шаг 1 (retrieval): теги=[session_logs], top_k=5, промпт="Найди упоминания..."
  └── Шаг 2 (retrieval): теги=[world_lore, npcs], top_k=10, промпт="Найди информацию о локациях..."
  └── Финальный шаг: промпт="На основе найденных данных ответь на вопрос мастера..."
```

- Ретривал-шаги выполняются параллельно
- Финальный шаг всегда один, обязателен, не имеет тегов ретривала
- Каждый шаг имеет имя для отображения в UI

### Привязка пайплайна к кампании

Пайплайн привязывается к кампании через теги в `pipeline_labels`. Если теги не указаны — пайплайн виден при любой кампании и в общем режиме.

---

## Vault и файловая система

- Один Vault на всю систему
- Документы добавляются пользователем вручную в ФС
- Индексация запускается вручную
- Дубли файлов (одинаковое содержимое, разные пути) допустимы — хранятся как отдельные документы
- Один документ может быть размечен тегами разных кампаний одновременно

