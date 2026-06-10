# STEPS: Пошаговый план реализации

Каждый шаг — отдельный чат. Ниже — готовые системные промты для копирования.

---

## ШАГ 1–3: ORM + Service + Schemas

**Что делаем:**
- Добавляем класс `RerankModel` в `models.py`
- Пишем миграцию БД
- Добавляем CRUD-методы в `settings_service.py`
- Добавляем Pydantic-схемы в `schemas.py`

---

### 📋 СИСТЕМНЫЙ ПРОМТ — Шаг 1-3

```
Репозиторий: https://github.com/Annener/mercer
Контекст по архитектуре: папка context/ в репозитории.
План фичи: папка Plan/ в репозитории — прочитай CONCEPT.md, RULES.md, PROGRESS.md.

## Порядок работы (строго соблюдать)

1. ПРОЧИТАТЬ файлы контекста:
   - Plan/CONCEPT.md — суть фичи и детали реализации
   - Plan/PROGRESS.md — текущий статус шагов
   - Plan/RULES.md — правила работы с файлами

2. ПРОЧИТАТЬ целевые файлы в репозитории ПЕРЕД изменением:
   - rag-backend/app/db/models.py
   - rag-backend/app/services/settings_service.py
   - rag-backend/app/api/settings/schemas.py
   - Найти папку с миграциями (alembic/versions/ или аналогичную)

3. ПОНЯТЬ постановку:
   - Текущий шаг: 1-3 (ORM модель + Service методы + Pydantic схемы)
   - Конечный результат шага: в БД есть таблица rerank_models, сервис умеет с ней работать,
     схемы валидации готовы
   - Сверить с CONCEPT.md секции "1. База данных", "2. settings_service.py", "4. Pydantic схемы"

4. РЕАЛИЗОВАТЬ:
   a) В models.py — добавить класс RerankModel в конец файла (после EmbeddingModel).
      ВАЖНО: не менять существующие классы, только добавить новый.
   b) Создать файл миграции — по образцу существующих миграций в проекте.
      Миграция только СОЗДАЁТ таблицу rerank_models, ничего не меняет в существующих.
   c) В settings_service.py — добавить методы для RerankModel в конец класса SettingsService.
      ВАЖНО: не менять существующие методы, только добавить новые.
      Методы: _get_rerank_model, list_rerank_models, create_rerank_model, update_rerank_model,
               delete_rerank_model, activate_rerank_model, get_active_rerank_model
   d) В schemas.py — добавить RerankModelCreateRequest и RerankModelUpdateRequest в конец файла.

5. ПРОВЕРИТЬ корректность реализации:
   - Прочитать каждый изменённый файл целиком после изменения
   - Убедиться что существующий код не тронут
   - Убедиться что новые методы соответствуют спецификации в CONCEPT.md
   - Миграция не должна трогать существующие таблицы

6. ОБНОВИТЬ PROGRESS.md:
   - Изменить статус шагов 1, 2, 3 на [x] в таблице
   - Добавить запись в секцию Notes для каждого шага
   - Обновить только эти строки, не трогать остальные

Если что-то в коде не совпадает с описанием в CONCEPT.md — остановиться и сообщить.
```

---

## ШАГ 4–5: API роутер + check helper

**Что делаем:**
- Создаём `rerank_models.py` в `app/api/settings/`
- Добавляем `_check_reranker_provider()` в `helpers.py`
- Регистрируем роутер в `__init__.py`

---

### 📋 СИСТЕМНЫЙ ПРОМТ — Шаг 4-5

```
Репозиторий: https://github.com/Annener/mercer
Контекст по архитектуре: папка context/ в репозитории.
План фичи: папка Plan/ в репозитории — прочитай CONCEPT.md, RULES.md, PROGRESS.md.

## Порядок работы (строго соблюдать)

1. ПРОЧИТАТЬ файлы контекста:
   - Plan/CONCEPT.md — суть фичи и детали реализации
   - Plan/PROGRESS.md — убедиться что шаги 1-3 завершены ([x])
   - Plan/RULES.md — правила работы с файлами

2. ПРОЧИТАТЬ целевые файлы ПЕРЕД изменением:
   - rag-backend/app/api/settings/emb_models.py — эталонный паттерн для нового роутера
   - rag-backend/app/api/settings/helpers.py — куда добавляем check-функцию
   - rag-backend/app/api/settings/__init__.py — куда регистрировать роутер
   - rag-backend/app/api/settings/schemas.py — убедиться что схемы шага 3 уже есть

3. ПОНЯТЬ постановку:
   - Текущий шаг: 4-5 (API роутер + helper для проверки)
   - Конечный результат: рабочие эндпоинты /settings/models/rerank/*
   - Сверить с CONCEPT.md секции "3. API" и "5. helpers.py"

4. РЕАЛИЗОВАТЬ:
   a) Создать новый файл rag-backend/app/api/settings/rerank_models.py
      Структура — точная копия паттерна emb_models.py, адаптированная под RerankModel.
      Эндпоинты: GET list, POST create, PUT update, DELETE delete,
                 POST /{model_id}/activate, POST /{model_id}/deactivate, POST /{model_id}/check
   b) В helpers.py — добавить _check_reranker_provider(model: RerankModel) в конец файла.
      Импорт RerankModel добавить в начало файла (к существующим импортам).
      ВАЖНО: не менять существующие функции.
   c) В __init__.py — добавить импорт и подключение rerank_models.router.
      Посмотреть как подключены другие роутеры и сделать аналогично.

5. ПРОВЕРИТЬ корректность реализации:
   - Прочитать rerank_models.py целиком — все эндпоинты соответствуют CONCEPT.md?
   - Прочитать helpers.py — существующие функции не тронуты?
   - Прочитать __init__.py — роутер зарегистрирован?
   - Lookup по model_id (строка), не по UUID PK — как в emb_models.py

6. ОБНОВИТЬ PROGRESS.md:
   - Изменить статус шагов 4, 5 на [x]
   - Добавить записи в Notes

Если шаги 1-3 не завершены — не продолжать, сообщить пользователю.
```

---

## ШАГ 6: Логика rerankinga в retrieval.py

**Что делаем:**
- Добавляем функцию `rerank_hits()` в `retrieval.py`
- Встраиваем вызов в `retrieve_multi_vault()`

---

### 📋 СИСТЕМНЫЙ ПРОМТ — Шаг 6

```
Репозиторий: https://github.com/Annener/mercer
Контекст по архитектуре: папка context/ в репозитории.
План фичи: папка Plan/ в репозитории — прочитай CONCEPT.md, RULES.md, PROGRESS.md.

## Порядок работы (строго соблюдать)

1. ПРОЧИТАТЬ файлы контекста:
   - Plan/CONCEPT.md — особенно секцию "6. retrieval.py — реализация rerankinga"
   - Plan/PROGRESS.md — убедиться что шаги 1-5 завершены ([x])
   - Plan/RULES.md — правила работы с файлами

2. ПРОЧИТАТЬ целевые файлы ПЕРЕД изменением:
   - rag-backend/app/services/retrieval.py — ЦЕЛИКОМ, внимательно
   - rag-backend/app/services/settings_service.py — убедиться что get_active_rerank_model есть

3. ПОНЯТЬ постановку:
   - Текущий шаг: 6 (реализация rerankinga)
   - ВАЖНЫЙ ФАКТ: reranker в retrieval.py сейчас не вызывается вообще.
     Нет функции rerank_hits, нет вызова в retrieve_multi_vault.
     Это не баг — просто не реализовано.
   - Конечный результат: после поиска результаты переранжируются активной reranker-моделью.
     Если активной модели нет — поиск работает как раньше, без изменений.

4. РЕАЛИЗОВАТЬ:
   a) Добавить функцию rerank_hits() в конец retrieval.py (после всех существующих функций).
      Спецификация — в CONCEPT.md секция "6. retrieval.py".
      Функция должна: получить активную модель, если нет — вернуть hits без изменений,
      сделать POST /rerank к провайдеру, пересортировать hits по scores.
      ВАЖНО: если в retrieval.py отсутствует `import httpx`, добавить его в блок импортов.
   b) В функции retrieve_multi_vault() — добавить вызов rerank_hits() перед return.
      Место вставки: после строки `result = all_hits[:effective_top_k]`
      Добавить:
        if db is not None:
            result = await rerank_hits(query, result, db)
      ВАЖНО: менять ТОЛЬКО эти два места. Не трогать retrieve(), _embed_query(),
             _embed_ollama(), _embed_openai_compatible() и другие функции.

5. ПРОВЕРИТЬ корректность реализации:
   - Прочитать retrieval.py целиком после изменений
   - Убедиться что retrieve() не тронута (только retrieve_multi_vault)
   - Убедиться что rerank_hits() корректно обрабатывает случай "нет активной модели"
   - Убедиться что rerank_hits() корректно обрабатывает пустой список hits
   - Убедиться что парсинг response поддерживает оба формата:
     results[i]["relevance_score"] и results[i]["score"]
   - Логирование: добавить logger.info в начало и конец rerank_hits для отладки

6. ОБНОВИТЬ PROGRESS.md:
   - Изменить статус шага 6 на [x]
   - Добавить запись в Notes

СТОП-условие: если retrieval.py уже содержит вызов reranker — остановиться и сообщить.
```

---

## ШАГ 7: Фронтенд — вкладка Reranker

**Что делаем:**
- Создаём `tab-rerank-models.js` в `rag-backend/app/static/js/settings/`
- Добавляем вкладку в HTML настроек

---

### 📋 СИСТЕМНЫЙ ПРОМТ — Шаг 7

```
Репозиторий: https://github.com/Annener/mercer
Контекст по архитектуре: папка context/ в репозитории.
План фичи: папка Plan/ в репозитории — прочитай CONCEPT.md, RULES.md, PROGRESS.md.

## Порядок работы (строго соблюдать)

1. ПРОЧИТАТЬ файлы контекста:
   - Plan/CONCEPT.md — секцию "UI: новая вкладка Reranker"
   - Plan/PROGRESS.md — убедиться что шаги 1-6 завершены
   - Plan/RULES.md — правила работы

2. НАЙТИ и ПРОЧИТАТЬ фронтенд-файлы:
   - Найти папку `rag-backend/app/static/js/settings/` в репозитории
   - Найти существующий JS файл для embedding или generation моделей — использовать как эталон
   - Найти HTML файл настроек — где добавлять вкладку

3. ПОНЯТЬ постановку:
   - Создать вкладку «Reranker» по аналогии с существующими вкладками моделей
   - Кнопка «Добавить модель» → модальное окно с полями из CONCEPT.md
   - Карточки моделей с кнопками: Активировать/Деактивировать, Проверить, Удалить
   - Активная модель визуально выделена (badge "АКТИВНА", зелёный индикатор)

4. РЕАЛИЗОВАТЬ:
   a) Создать `rag-backend/app/static/js/settings/tab-rerank-models.js` по образцу существующего embedding JS.
      API-эндпоинты: /settings/models/rerank (list, create, update, delete, activate, deactivate, check)
   b) Добавить вкладку в HTML страницу настроек.
      ВАЖНО: добавить только новую вкладку, не менять существующие.

5. ПРОВЕРИТЬ:
   - JS файл покрывает все операции: list, create, activate, deactivate, check, delete
   - Модальное окно содержит все поля: model_id, display_name, provider, base_url, api_key, timeout_seconds
   - Обработка ошибок: если API вернул ошибку — показать пользователю
   - Кнопка "Проверить" показывает latency и статус ответа

6. ОБНОВИТЬ PROGRESS.md: статус шага 7 на [x]
```

---

## ШАГ 8–9: Cleanup + QA

**Что делаем:**
- Удаляем старые ключи `reranker.*` из platform_settings
- Сквозное ручное тестирование

---

### 📋 СИСТЕМНЫЙ ПРОМТ — Шаг 8-9

```
Репозиторий: https://github.com/Annener/mercer
Контекст по архитектуре: папка context/ в репозитории.
План фичи: папка Plan/ в репозитории — прочитай CONCEPT.md, RULES.md, PROGRESS.md.

## Порядок работы (строго соблюдать)

1. ПРОЧИТАТЬ Plan/PROGRESS.md — убедиться что шаги 1-7 завершены ([x]).
   Если нет — не продолжать.

2. Шаг 8 — Cleanup:
   a) Найти все упоминания ключей reranker.enabled, reranker.provider,
      reranker.base_url, reranker.model_name в коде:
      - settings_service.py DEFAULTS dict
      - Любые миграции где эти ключи инициализируются
      - Фронтенд-код (общие параметры)
   b) Убрать их из DEFAULTS в settings_service.py
   c) Создать миграцию: DELETE FROM platform_settings WHERE key LIKE 'reranker.%'
   d) Убрать поля reranker из UI общих параметров (если они там есть)
   ВАЖНО: убирать ТОЛЬКО reranker.* ключи, не трогать retrieval.reranker_enabled

3. Шаг 9 — QA чеклист:
   □ Можно добавить reranker-модель через UI
   □ Можно активировать модель — она помечается как активная
   □ Только одна модель может быть активной одновременно
   □ Кнопка "Проверить" возвращает latency или понятную ошибку
   □ При активной модели: RAG-поиск возвращает переранжированные результаты
     (проверить через логи rag-backend — должен быть RERANK лог)
   □ При деактивированной модели: поиск работает как раньше
   □ Удаление модели работает корректно
   □ После удаления активной модели поиск не падает (graceful fallback)

4. ОБНОВИТЬ PROGRESS.md:
   - Изменить статус шагов 8, 9 на [x]
   - Добавить записи в Notes
   - Кратко зафиксировать результаты QA по чеклисту
```
