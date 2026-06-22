# План выполнения: Вкладка «Модели»

Каждый шаг атомарный. Можно выполнять по одному в отдельном чате, используя промт из PROMPT.md.

---

## Шаг 1 — Создать `models.css`

**Файл:** `rag-backend/app/static/css/models.css` (создать новый)

**Задача:** Вынести из `settings.css` все стили, специфичные для карточек и меню моделей, и добавить новые классы для секций.

**Что создаём в `models.css`:**

1. Перенести (СКОПИРОВАТЬ, не удалять пока) из `settings.css`:
   - `.settings-card` и все вложенные (`.settings-card h3`, `.settings-card p`)
   - `.settings-card--active` (если есть — или добавить)
   - `.settings-card-body`, `.settings-card-meta`
   - `.settings-grid`
   - `.card-menu-container`, `.card-menu-toggle`, `.card-menu-btn`
   - `.card-menu`, `.card-menu-dropdown` и их состояния (`.open`)
   - `.card-menu-item`, `.card-menu-danger` и hover/disabled
   - `.model-card`, `.model-card-*`, `.model-list`, `.model-add-*` (легаси, для совместимости)

2. Добавить новые классы:
```css
/* Секция моделей */
.models-section {
    margin-bottom: 28px;
    background: #fff;
    border: 1px solid #b8cfe0;
    border-radius: 10px;
    padding: 18px 20px 16px;
    box-shadow: 0 1px 4px rgba(52, 120, 180, 0.06);
}

.models-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
}

.models-section-title {
    font-size: 14px;
    font-weight: 650;
    color: #1f4e6e;
    display: flex;
    align-items: center;
    gap: 6px;
}

.models-section-title::before {
    content: '';
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3498db;
    flex-shrink: 0;
}

.models-section-body {
    /* пусто — содержит .settings-grid */
}

/* Модификатор активной карточки */
.settings-card--active {
    border-color: #27ae60;
    box-shadow: 0 0 0 2px #e6f5ee;
}
```

3. Добавить подключение в HTML-шаблон (рядом с settings.css):
```html
<link rel="stylesheet" href="/static/css/models.css">
```

**Проверка:** Открыть страницу настроек, убедиться что карточки выглядят как раньше (стили дублируются пока — это нормально на этом шаге).

**Риск:** Низкий. Только добавляем файл, ничего не удаляем.

---

## Шаг 2 — Создать `tab-models.js` (оркестратор)

**Файл:** `rag-backend/app/static/js/settings/tab-models.js` (создать новый)

**Задача:** Единый рендерер карточек + оркестратор трёх секций.

**Структура файла:**

```js
const ModelsTabMixin = {

    // ─── Единый рендерер карточки ─────────────────────────────────────────────
    // config: { id, title, subtitle, subInfo?, badge: {text, class}, isActive, menuItems[] }
    // menuItem: { action, label, disabled?, danger? }
    renderModelCard(config) {
        const menuItemsHtml = config.menuItems.map(item => `
            <button class="card-menu-item${item.danger ? ' card-menu-danger' : ''}"
                    data-action="${this.escapeHtml(item.action)}"
                    data-id="${this.escapeHtml(config.id)}"
                    ${item.disabled ? 'disabled' : ''}>
                ${item.label}
            </button>`).join('');

        return `<article class="settings-card${config.isActive ? ' settings-card--active' : ''}">
            <div class="settings-card-body">
                <h3>${this.escapeHtml(config.title)}</h3>
                <p class="settings-card-meta">${this.escapeHtml(config.subtitle)}</p>
                ${config.subInfo ? `<p class="settings-card-meta">${this.escapeHtml(config.subInfo)}</p>` : ''}
            </div>
            <div class="card-menu-container">
                <button class="card-menu-toggle"
                        data-id="${this.escapeHtml(config.id)}"
                        aria-label="Меню модели">⋮</button>
                <div class="card-menu">${menuItemsHtml}</div>
            </div>
            <div><span class="badge ${config.badge.class}">${config.badge.text}</span></div>
        </article>`;
    },

    // ─── Обёртка секции ───────────────────────────────────────────────────────
    _renderModelsSection(title, addAction, bodyHtml) {
        return `
        <div class="models-section">
            <div class="models-section-header">
                <h3 class="models-section-title">${title}</h3>
                <button class="btn btn-primary btn-sm"
                        data-action="${addAction}">+ Добавить модель</button>
            </div>
            <div class="models-section-body">
                ${bodyHtml}
            </div>
        </div>`;
    },

    // ─── Главный рендерер вкладки ─────────────────────────────────────────────
    async renderModelsTab() {
        const [genHtml, embHtml, rerankHtml] = await Promise.all([
            this._renderGenSection(),
            this._renderEmbSection(),
            this._renderRerankSection(),
        ]);
        return genHtml + embHtml + rerankHtml;
    },

    // ─── Секция: Генеративные ─────────────────────────────────────────────────
    async _renderGenSection() {
        const models = await this.api.getGenerationModels();
        const modelsArr = Array.isArray(models) ? models : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="empty-state">Нет моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => this.renderModelCard(this._genModelConfig(m))).join('')}
               </div>`;

        return this._renderModelsSection('Генеративные', 'new-gen', bodyHtml);
    },

    _genModelConfig(model) {
        const isActive = !!model.is_active;
        const isEnabled = model.enabled !== false;
        return {
            id: model.model_id,
            title: model.display_name || model.model_id,
            subtitle: model.provider || '',
            badge: isActive
                ? { text: 'active', class: 'ok' }
                : (!isEnabled ? { text: 'disabled', class: 'muted' } : { text: 'ready', class: 'muted' }),
            isActive,
            menuItems: [
                { action: 'edit-gen',     label: '✏️ Изменить' },
                { action: 'check-gen',    label: '🔍 Проверить' },
                { action: 'activate-gen', label: '▶️ Активировать', disabled: isActive },
                { action: 'toggle-gen',   label: isEnabled ? '⏸️ Выключить' : '▶️ Включить' },
                { action: 'delete-gen',   label: '🗑️ Удалить', danger: true, disabled: isActive },
            ],
        };
    },

    // ─── Секция: Embedding ────────────────────────────────────────────────────
    async _renderEmbSection() {
        const [models, vaults] = await Promise.all([
            this.api.getEmbeddingModels(),
            this.api.getSettingsVaults(),
        ]);
        const modelsArr = Array.isArray(models) ? models : [];
        const vaultsArr = Array.isArray(vaults) ? vaults : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="empty-state">Нет моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => {
                    const connectedVaults = vaultsArr.filter(v => v.embedding_model_id === m.model_id);
                    return this.renderModelCard(this._embModelConfig(m, connectedVaults));
                }).join('')}
               </div>`;

        return this._renderModelsSection('Embedding', 'new-emb', bodyHtml);
    },

    _embModelConfig(model, connectedVaults = []) {
        const hasVaults = connectedVaults.length > 0;
        return {
            id: model.model_id,
            title: model.display_name || model.model_id,
            subtitle: `${model.provider || ''}${model.dimensions ? ` · ${model.dimensions}` : ''}`,
            subInfo: hasVaults ? `${connectedVaults.length} vault'ов` : undefined,
            badge: { text: 'ready', class: 'ok' },
            isActive: false,
            menuItems: [
                { action: 'edit-emb',   label: '✏️ Изменить' },
                { action: 'check-emb',  label: '🔍 Проверить' },
                { action: 'delete-emb', label: '🗑️ Удалить', danger: true, disabled: hasVaults },
            ],
        };
    },

    // ─── Секция: Reranker ─────────────────────────────────────────────────────
    async _renderRerankSection() {
        const models = await this.api.getRerankModels();
        const modelsArr = Array.isArray(models) ? models : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="empty-state">Нет reranker-моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => this.renderModelCard(this._rerankModelConfig(m))).join('')}
               </div>`;

        return this._renderModelsSection('Reranker', 'new-rerank', bodyHtml);
    },

    _rerankModelConfig(model) {
        const isActive = !!model.is_active;
        const isEnabled = model.enabled !== false;
        return {
            id: model.model_id,
            title: model.display_name || model.model_id,
            subtitle: `${model.base_url || ''} · ${model.provider || ''}`,
            badge: isActive && isEnabled
                ? { text: 'АКТИВНА', class: 'ok' }
                : (!isEnabled ? { text: 'отключена', class: 'muted' } : { text: 'неактивна', class: 'muted' }),
            isActive,
            menuItems: [
                ...(isActive
                    ? [{ action: 'deactivate-rerank', label: '⏸️ Деактивировать' }]
                    : [{ action: 'activate-rerank',   label: '▶️ Активировать' }]
                ),
                { action: 'edit-rerank',   label: '✏️ Редактировать' },
                { action: 'check-rerank',  label: '🔍 Проверить' },
                { action: 'delete-rerank', label: '🗑️ Удалить', danger: true, disabled: isActive },
            ],
        };
    },
};

Object.assign(SettingsManager.prototype, ModelsTabMixin);
```

**Подключить в HTML** после трёх существующих tab-файлов:
```html
<script src="/static/js/settings/tab-models.js"></script>
```

**Порядок подключения важен:**
```
tab-gen-models.js     ← должен быть ДО
tab-emb-models.js     ← должен быть ДО
tab-rerank-models.js  ← должен быть ДО
tab-models.js         ← последний из четырёх
```

**Проверка:** Файл создан, ошибок синтаксиса нет. Вкладка пока не работает (не зарегистрирована).

---

## Шаг 3 — Обновить `loadTab` вызовы в tab-gen-models.js

**Файл:** `rag-backend/app/static/js/settings/tab-gen-models.js`

**Задача:**
1. Найти и заменить все `await this.loadTab('gen-models')` → `await this.loadTab('models')`
2. Удалить метод `renderModelList` (целиком) — заменён на `renderModelCard` в tab-models.js
3. Удалить метод `renderGenerationModelsTab` — логика переехала в `_genModelConfig` / `_renderGenSection`

**Что оставить:**
- `showGenerationModelModal` (modal остаётся без изменений, кроме loadTab)

**Grep-подсказка:** Ищем все `loadTab` в файле и меняем на `'models'`.

**Проверка:** Файл не должен содержать `'gen-models'` ни в одном месте.

---

## Шаг 4 — Обновить `loadTab` вызовы в tab-emb-models.js

**Файл:** `rag-backend/app/static/js/settings/tab-emb-models.js`

**Задача:**
1. Заменить все `await this.loadTab('emb-models')` → `await this.loadTab('models')`
2. Удалить метод `renderEmbeddingModelsTab` — логика переехала в `_embModelConfig` / `_renderEmbSection`

**Что оставить:**
- `showEmbeddingModelModal` (modal без изменений, кроме loadTab)

**Проверка:** Файл не должен содержать `'emb-models'`.

---

## Шаг 5 — Обновить `loadTab` вызовы в tab-rerank-models.js

**Файл:** `rag-backend/app/static/js/settings/tab-rerank-models.js`

**Задача:**
1. Найти и заменить ВСЕ вхождения `loadTab('rerank-models')` → `loadTab('models')` (их около 5 в `handleRerankModelsAction`)
2. Удалить методы `renderRerankModelsTab` и `_renderRerankModelList`

**Что оставить:**
- `handleRerankModelsAction` (с исправленными loadTab)
- `showRerankModelModal`
- `showRerankModelEditModal`

**Grep-подсказка:**
```
loadTab('rerank-models')  →  loadTab('models')
```

**Проверка:** Файл не должен содержать `'rerank-models'`.

---

## Шаг 6 — Зарегистрировать вкладку в `SettingsManager`

**Файл:** Основной JS файл настроек (скорее всего `settings.js` или главный скрипт в HTML)

**Задача:** Добавить обработку `case 'models':` в метод `loadTab` / `renderTab`.

**Найти код типа:**
```js
case 'gen-models':
    html = await this.renderGenerationModelsTab();
    break;
case 'emb-models':
    html = await this.renderEmbeddingModelsTab();
    break;
case 'rerank-models':
    html = await this.renderRerankModelsTab();
    break;
```

**Заменить на:**
```js
case 'models':
    html = await this.renderModelsTab();
    break;
```

Убедиться, что action-ы `new-gen`, `edit-gen`, `check-gen`, `activate-gen`, `toggle-gen`, `delete-gen`, `new-emb`, `edit-emb`, `check-emb`, `delete-emb`, `new-rerank`, `edit-rerank`, `check-rerank`, `activate-rerank`, `deactivate-rerank`, `delete-rerank` — маршрутизируются правильно в обработчике кликов.

**Проверка:** `loadTab('models')` отрабатывает без ошибок, три секции рендерятся.

---

## Шаг 7 — Обновить HTML: заменить три вкладки на одну

**Файл:** HTML-шаблон настроек (скорее всего `settings.html` или шаблон Jinja2)

**Найти:**
```html
<button data-tab="gen-models">Генеративные модели</button>
<button data-tab="emb-models">Embedding модели</button>
<button data-tab="rerank-models">Reranker</button>
```

**Заменить на:**
```html
<button data-tab="models">Модели</button>
```

**Проверка:** В навигации одна вкладка «Модели». При клике — отображаются три секции с карточками.

---

## Шаг 8 — Удалить перенесённые стили из `settings.css`

**Файл:** `rag-backend/app/static/css/settings.css`

**Удалить из `settings.css`:**
- `.settings-card` и вложенные
- `.settings-card--active`
- `.settings-card-body`, `.settings-card-meta`
- `.settings-grid`
- `.card-menu-container`, `.card-menu-toggle`, `.card-menu-btn`
- `.card-menu`, `.card-menu-dropdown` и их состояния
- `.card-menu-item`, `.card-menu-danger` и их состояния
- `.model-card`, `.model-card-*`, `.model-list`, `.model-add-*` (легаси-блоки)

**Оставить в `settings.css`:**
- `.badge` и все варианты (используются везде)
- `.settings-toolbar` (используется во вкладке Параметры)
- Всё остальное (layout, tabs, modals, params, docs, campaigns...)

**Проверка:** Страница выглядит идентично. DevTools → нет ошибок, все карточки отображаются.

---

## Шаг 9 — Финальная проверка и чистка

**Задача:**

1. Убедиться что нигде не осталось `'gen-models'`, `'emb-models'`, `'rerank-models'` в JS-файлах
2. Проверить все 6 сценариев:
   - Клик «+ Добавить модель» в каждой секции открывает правильный modal
   - После сохранения новой модели — секция обновляется
   - Edit/Delete/Check работают для каждого типа
   - Активация генеративной модели работает
   - Активация/деактивация reranker работает
3. Проверить пустые состояния (empty-state) в каждой секции
4. Убедиться что `api.js` не изменялся
