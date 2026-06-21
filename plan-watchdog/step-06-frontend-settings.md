# Этап 6 — Фронтенд: вкладка «Индексация» в настройках платформы

## Цель

Добавить в UI управление `watchdog_auto_index_extensions`: администратор видит чекбоксы
по расширениям, может добавить своё и сохраняет нажатием «Сохранить».

## Архитектурный контекст

Фронтенд — **чистый vanilla JS без фреймворков**. Никакого Vue/React/JSX.

Паттерн организации:
- `rag-backend/app/static/js/api.js` — единый класс `chatAPI` со всеми fetch-методами
- `rag-backend/app/static/js/settings.js` — класс `SettingsManager`; switch по `tab` в `loadTab()` и `_dispatch()`
- `rag-backend/app/static/js/settings/tab-*.js` — каждый файл экспортирует mixin-объект и вызывает `Object.assign(SettingsManager.prototype, ...)`
- `rag-backend/app/static/index.html` — nav с кнопками `data-tab="..."` и `<script>` тегами

> ⚠️ **Порядок загрузки скриптов**: `settings.js` обязательно должен быть
> загружен **раньше** `tab-indexing.js`. Если `tab-indexing.js`
> окажется выше `settings.js` — `ReferenceError: SettingsManager is not defined`.

## UX-логика

```
Вкладка «Индексация»:
  Заголовок: «Авто-индексация при изменении файлов»
  Подзаголовок: «Файлы этих типов будут переиндексированы автоматически»
  [✓] .md
  [✓] .pdf
  [ ] .docx
  [ ] .txt
  [ ] .rst
  [ ] .html
  Ввод своего расширения: [______] + [Добавить]
  [Сохранить]
```

Предопределённый список расширений: `.md`, `.pdf`, `.docx`, `.txt`, `.rst`, `.html`.
Дополнительно пользователь может ввести любое своё расширение.

## Что нужно сделать

### 1. `rag-backend/app/static/js/api.js` — добавить два метода в класс `chatAPI`

```js
// Watchdog settings
async getWatchdogSettings() {
    const res = await fetch('/api/v1/settings/watchdog');
    if (!res.ok) throw new Error('Failed to load watchdog settings');
    return res.json(); // { auto_index_extensions: string[] }
}

async saveWatchdogSettings(extensions) {
    const res = await fetch('/api/v1/settings/watchdog', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_index_extensions: extensions }),
    });
    if (!res.ok) throw new Error('Failed to save watchdog settings');
    return res.json();
}
```

### 2. `rag-backend/app/static/js/settings/tab-indexing.js` — создать новый файл

Паттерн идентичен `tab-params.js`: mixin-объект + `Object.assign`.

```js
const INDEXING_KNOWN_EXTENSIONS = ['.md', '.pdf', '.docx', '.txt', '.rst', '.html'];

const IndexingTabMixin = {
    async renderIndexingTab() {
        let currentExtensions = [];
        try {
            const data = await this.api.getWatchdogSettings();
            currentExtensions = data.auto_index_extensions || [];
        } catch (e) {
            console.error('Failed to load watchdog settings', e);
        }

        const selectedSet = new Set(currentExtensions);

        // Собираем все расширения: известные + кастомные из текущих настроек
        const allExtensions = [
            ...INDEXING_KNOWN_EXTENSIONS,
            ...currentExtensions.filter(e => !INDEXING_KNOWN_EXTENSIONS.includes(e)),
        ];

        const checkboxesHtml = allExtensions.map(ext => `
            <label class="settings-param-row indexing-ext-row">
                <input type="checkbox"
                       data-ext="${this.escapeHtml(ext)}"
                       ${selectedSet.has(ext) ? 'checked' : ''}>
                <span>${this.escapeHtml(ext)}</span>
            </label>
        `).join('');

        return `
            <div class="settings-section">
                <h3>Авто-индексация при изменении файлов</h3>
                <p class="settings-param-desc">
                    Файлы этих типов будут переиндексированы автоматически при изменении в vault-директории
                </p>

                <div id="indexing-ext-list" class="indexing-ext-list">
                    ${checkboxesHtml}
                </div>

                <div class="indexing-custom-input settings-toolbar">
                    <input type="text"
                           id="indexing-custom-ext"
                           placeholder=".epub"
                           style="width: 140px;">
                    <button class="btn btn-secondary" data-action="add-ext">Добавить</button>
                </div>

                <div id="indexing-message" style="min-height: 1.5em; margin-top: 8px;"></div>

                <div class="settings-params-footer">
                    <button class="btn btn-primary" data-action="save-indexing">Сохранить</button>
                </div>
            </div>
        `;
    },

    async handleIndexingAction(action, id, btn) {
        if (action === 'add-ext') {
            const input = this._tabContent.querySelector('#indexing-custom-ext');
            const msgEl = this._tabContent.querySelector('#indexing-message');
            const ext = (input?.value || '').trim();
            if (!ext.startsWith('.')) {
                if (msgEl) {
                    msgEl.textContent = 'Расширение должно начинаться с "."';
                    msgEl.className = 'error';
                }
                return;
            }
            // Проверяем дубликат
            const existing = this._tabContent.querySelector(`[data-ext="${CSS.escape(ext)}"]`);
            if (existing) {
                if (msgEl) {
                    msgEl.textContent = `Расширение ${ext} уже есть в списке`;
                    msgEl.className = '';
                }
                return;
            }
            // Добавляем чекбокс
            const list = this._tabContent.querySelector('#indexing-ext-list');
            if (list) {
                const label = document.createElement('label');
                label.className = 'settings-param-row indexing-ext-row';
                label.innerHTML = `
                    <input type="checkbox" data-ext="${this.escapeHtml(ext)}" checked>
                    <span>${this.escapeHtml(ext)}</span>
                `;
                list.appendChild(label);
            }
            if (input) input.value = '';
            if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; }

        } else if (action === 'save-indexing') {
            const msgEl = this._tabContent.querySelector('#indexing-message');
            const checked = [...this._tabContent.querySelectorAll('#indexing-ext-list [data-ext]')]
                .filter(cb => cb.checked)
                .map(cb => cb.dataset.ext);

            // Клиентская валидация: backend вернёт 422, но лучше сообщить заранее
            if (checked.length === 0) {
                if (msgEl) {
                    msgEl.textContent = 'Выберите хотя бы одно расширение';
                    msgEl.className = 'error';
                }
                return;
            }

            try {
                await this.api.saveWatchdogSettings(checked);
                if (msgEl) {
                    msgEl.textContent = 'Настройки сохранены';
                    msgEl.className = 'success';
                    setTimeout(() => { if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; } }, 3000);
                }
            } catch (e) {
                if (msgEl) {
                    msgEl.textContent = 'Ошибка сохранения: ' + e.message;
                    msgEl.className = 'error';
                }
            }
        }
    },
};

Object.assign(SettingsManager.prototype, IndexingTabMixin);
```

### 3. `rag-backend/app/static/js/settings.js` — добавить в два switch

> ⚠️ **Обязательно обновить оба** switch в `loadTab()` и `_dispatch()`.
> Если пропустить любой — вкладка откроется пустой или кнопки не будут реагировать.

В методе `loadTab()`:
```js
case 'indexing': html = await this.renderIndexingTab(); break;
```

В методе `_dispatch()`:
```js
case 'indexing': await this.handleIndexingAction(action, id, btn); break;
```

### 4. `rag-backend/app/static/index.html` — два изменения

**4a. Добавить кнопку вкладки** в `<nav class="settings-tabs">` (после `documents`):
```html
<button data-tab="indexing">Индексация</button>
```

**4b. Добавить `<script>` тег`** после `tab-documents.js` и **обязательно после `settings.js`**:
```html
<script src="/static/js/settings/tab-indexing.js"></script>
```

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `rag-backend/app/static/js/api.js` | Добавить методы `getWatchdogSettings`, `saveWatchdogSettings` |
| `rag-backend/app/static/js/settings/tab-indexing.js` | **Создать** |
| `rag-backend/app/static/js/settings.js` | Добавить `case 'indexing'` в `loadTab()` и `_dispatch()` |
| `rag-backend/app/static/index.html` | Добавить кнопку вкладки и `<script>` тег в правильном порядке |

## Критерий готовности

- [ ] При открытии вкладки «Индексация» читается `GET /api/v1/settings/watchdog`, чекбоксы отображают текущие значения
- [ ] При «Сохранить» отправляется `PATCH /api/v1/settings/watchdog` с выбранными расширениями в виде массива
- [ ] Валидация: нельзя добавить расширение без точки
- [ ] Нельзя добавить дубликат расширения
- [ ] Клиентская валидация: нельзя сохранить с пустым списком («Выберите хотя бы одно расширение»)
- [ ] Сообщение «Настройки сохранены» автоматически исчезает через 3 секунды
- [ ] `STATUS.md` обновлён: этап 6 → ✅
