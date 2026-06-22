# Промт для работы по плану

Скопируй этот блок целиком в чат перед каждым шагом. Замени `[НОМЕР]` на актуальный шаг.

---

```
Репозиторий: https://github.com/Annener/mercer

Мы рефакторим вкладку настроек моделей.
Объединяем три вкладки (Генеративные / Embedding / Reranker) в одну вкладку «Модели» с тремя секциями.
Ключевое требование: единый рендерер карточек `renderModelCard(config)` в tab-models.js — все три типа используют его.
api.js не трогаем — URL там не меняются.

Полный план и концепт: https://github.com/Annener/mercer/tree/main/plan-models-tab

Выполни Шаг [НОМЕР] из файла STEPS.md.

Текущий статус шагов — в файле STATUS.md.

Прежде чем писать код:
1. Прочитай CONCEPT.md
2. Прочитай STEPS.md — раздел «Шаг [НОМЕР]»
3. Прочитай актуальные версии файлов, которые нужно изменить на этом шаге
4. Напиши итоговый код изменений
5. Укажи, какие строки в STATUS.md надо обновить
```

---

## Шпаргалка: какие файлы читать на каждом шаге

| Шаг | Файлы для чтения перед правкой |
|-----|-------------------------------|
| 1 | `rag-backend/app/static/css/settings.css`, HTML-шаблон настроек |
| 2 | `rag-backend/app/static/js/settings/tab-gen-models.js`, `tab-emb-models.js`, `tab-rerank-models.js` |
| 3 | `rag-backend/app/static/js/settings/tab-gen-models.js` |
| 4 | `rag-backend/app/static/js/settings/tab-emb-models.js` |
| 5 | `rag-backend/app/static/js/settings/tab-rerank-models.js` |
| 6 | Основной settings.js или скрипт в HTML-шаблоне |
| 7 | HTML-шаблон настроек (settings.html / Jinja2) |
| 8 | `rag-backend/app/static/css/settings.css` |
| 9 | Все файлы из шагов 1-8 |

## Подсказка по поиску HTML-шаблона

Шаблон скорее всего находится в одном из:
- `rag-backend/app/templates/settings.html`
- `rag-backend/app/static/settings.html`
- `rag-backend/templates/`

Для поиска основного JS: ищи файл где есть `class SettingsManager` или `loadTab`.
