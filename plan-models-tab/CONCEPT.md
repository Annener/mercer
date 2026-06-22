# Концепт: Вкладка «Модели»

## Проблема

Сейчас три отдельных вкладки — «Генеративные модели», «Embedding модели», «Reranker» — решают одну задачу: управление моделями. Это лишний клик, лишние переключения. Кроме того, карточки моделей рендерятся тремя разными способами:

- `renderModelList('gen', ...)` — генеративные (через GenModelsTabMixin)
- `renderModelList('emb', ...)` — embedding (через тот же GenModelsTabMixin)
- `_renderRerankModelList(...)` — reranker (свой рендерер с другой структурой карточки)

Если захочется изменить внешний вид карточки — нужно лезть в несколько мест. Это плохо.

## Цель

1. **Одна вкладка «Модели»** с тремя секциями: Генеративные / Embedding / Reranker
2. **Единый рендерер карточек** `renderModelCard(config)` — правишь один раз, меняется везде
3. **Единый CSS** `models.css` — весь визуал карточек и секций в одном файле
4. **Сохранить изоляцию бизнес-логики**: каждый тип модели остаётся в своём файле (tab-gen-models.js, tab-emb-models.js, tab-rerank-models.js)

## Структура после рефакторинга

```
tab-models.js           ← НОВЫЙ: оркестратор, рендерер секций, единый рендерер карточек
tab-gen-models.js       ← ПРАВКИ: логика ген.моделей, modal, loadTab('models')
tab-emb-models.js       ← ПРАВКИ: логика emb-моделей, modal, loadTab('models')
tab-rerank-models.js    ← ПРАВКИ: логика reranker, modal, loadTab('models')
models.css              ← НОВЫЙ: весь CSS для карточек и секций моделей
settings.css            ← ПРАВКИ: удалены стили, переехавшие в models.css
```

## Анатомия единой карточки

Все три типа модели будут рендериться через один `renderModelCard(config)`:

```
┌─────────────────────────────────────────────────┐
│  [badge: АКТИВНА]                          [⋮]  │
│                                                 │
│  Название модели                                │
│  provider · detail (dimensions / url)           │
│                                                 │
│  [sub-info: vaults / url]                       │
└─────────────────────────────────────────────────┘
```

`config` — объект, который каждый tab-файл собирает из своих данных и передаёт в общий рендерер:

```js
{
  id: 'model-id',           // data-id для action-обработчика
  title: 'Display Name',
  subtitle: 'ollama · 768',
  subInfo: '3 vault\'ов',   // опционально
  badge: { text: 'АКТИВНА', class: 'ok' },
  isActive: true,           // .settings-card--active
  menuItems: [              // каждый tab-файл формирует свой список
    { action: 'edit-gen', label: '✏️ Изменить', disabled: false },
    { action: 'activate-gen', label: '▶️ Активировать', disabled: false },
    { action: 'delete-gen', label: '🗑️ Удалить', danger: true, disabled: false },
  ]
}
```

## Секции (аналог вкладки Параметры)

Каждая секция выглядит так:

```
┌─ Генеративные ──────────────────── [+ Добавить модель] ─┐
│                                                          │
│  [card] [card] [card]                                    │
│                                                          │
└──────────────────────────────────────────────────────────┘

┌─ Embedding ─────────────────────── [+ Добавить модель] ─┐
│  ...                                                     │
└──────────────────────────────────────────────────────────┘

┌─ Reranker ──────────────────────── [+ Добавить модель] ─┐
│  ...                                                     │
└──────────────────────────────────────────────────────────┘
```

Кнопка **+ Добавить модель** живёт в заголовке секции и несёт `data-action="new-gen"` / `new-emb` / `new-rerank`. Toolbar внутри каждого рендерера **убирается** — он больше не нужен.

## Что НЕ меняется

- `api.js` — **не трогаем вообще**. Все URL остаются нетронутыми.
- Модальные окна (wizard) — **не меняем**. Только обновляем `loadTab(...)` внутри них.
- Мастер конфигурации — **не меняем**.
- Бизнес-логика каждого типа модели — остаётся в своём файле.

## CSS: что переезжает в models.css

Из `settings.css` выносятся только стили, специфичные для карточек моделей и секций:

| Класс | Переезжает |
|-------|----------|
| `.settings-card`, `.settings-card--active`, `.settings-card-body`, `.settings-card-meta` | ✅ в models.css |
| `.settings-grid` | ✅ в models.css |
| `.settings-toolbar` (только в контексте моделей) | ⚠️ используется и в других вкладках — создаём `.models-toolbar` |
| `.card-menu-container`, `.card-menu-toggle`, `.card-menu`, `.card-menu-item`, `.card-menu-danger` | ✅ в models.css |
| `.badge`, `.badge.ok`, `.badge.muted` | ⚠️ badge используется везде — копируем нужные варианты, в settings.css оставляем |
| Новые: `.models-section`, `.models-section-header`, `.models-section-body` | ✅ только в models.css |
| `.model-card`, `.model-card-*`, `.model-list` (старые легаси) | ✅ в models.css (там же и умрут) |
