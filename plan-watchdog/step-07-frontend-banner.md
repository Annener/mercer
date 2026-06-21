# Этап 7 — Фронтенд: баннер pending-files в чате

## Цель

Если в активном домене есть файлы со статусом `pending` — показать баннер
с кнопкой «Запустить индексацию». Polling каждые 30 секунд.

> ⚠️ **Архитектурное уточнение:** баннер работает на уровне **домена**, а не отдельного vault.
> Один домен может содержать несколько vault-ов — баннер показывает суммарное
> количество `pending`-файлов по всем vault-ам домена.
> `domain_id` берётся из `chat.domain_id` текущего чата.

## Контекст из кодовой базы

### Фронтенд — vanilla JS, без Vue

Проект использует чистый vanilla JS (`rag-backend/app/static/js/`).
Компоненты Vue (`.vue`-файлы, `<script setup>`, `ref`, `watch`) **не применимы**.
Новые компоненты реализуются как классы по паттерну `ChatManager`.

### Откуда берётся `domain_id`

Текущий чат загружается через `chatAPI.getChat(chatId)` и хранится в
`chatManager.currentChat`. Поле `chat.domain_id` содержит идентификатор домена.

### Архитектура `ChatManager`

- Конструктор собирает все DOM-элементы через `getElementById`.
- `loadChat(chatId)` → устанавливает `this.currentChat` → вызывает `setupContextBar(chat)`.
- `reset()` → вызывается при деселекте чата, скрывает UI.
- Все DOM-элементы уже существуют к моменту `DOMContentLoaded`.

## Что нужно создать / изменить

### 1. `rag-backend/app/static/js/pending-banner.js`

Новый файл — класс `PendingFilesBanner`.

```javascript
/**
 * PendingFilesBanner
 *
 * Показывает/скрывает баннер с количеством pending-файлов домена.
 * Polling каждые 30 секунд пока есть pending-файлы.
 *
 * Использование:
 *   const banner = new PendingFilesBanner('chat-banner-area');
 *   banner.setDomain('domain-42', 'domain-42'); // запускает polling
 *   banner.destroy();                            // останавливает polling, убирает DOM
 */
class PendingFilesBanner {
    /**
     * @param {string} containerId  — id контейнера, куда вставляется баннер
     */
    constructor(containerId) {
        this._container = document.getElementById(containerId);
        this._el = null;       // DOM-элемент баннера
        this._timer = null;    // setInterval handle
        this._domainId = null;
    }

    /**
     * Устанавливает домен и запускает polling.
     * Передача null останавливает polling и скрывает баннер.
     *
     * @param {string|null} domainId
     */
    setDomain(domainId) {
        this._domainId = domainId;
        this._startPolling();
    }

    /**
     * Останавливает polling и удаляет DOM-элемент баннера.
     * Вызывается из ChatManager.reset().
     */
    destroy() {
        this._stopPolling();
        if (this._el) {
            this._el.remove();
            this._el = null;
        }
        this._domainId = null;
    }

    _startPolling() {
        this._stopPolling();
        if (!this._domainId) {
            this._hide();
            return;
        }
        // Немедленный первый запрос, затем каждые 30 с
        this._poll();
        this._timer = setInterval(() => this._poll(), 30_000);
    }

    _stopPolling() {
        if (this._timer !== null) {
            clearInterval(this._timer);
            this._timer = null;
        }
    }

    async _poll() {
        if (!this._domainId) return;
        try {
            const res = await fetch(`/api/v1/domains/${encodeURIComponent(this._domainId)}/pending-files`);
            if (!res.ok) return;
            const data = await res.json();
            if (data.total_pending > 0) {
                this._show(data.total_pending);
            } else {
                this._hide();
                // Нет pending — polling больше не нужен до следующего setDomain
                this._stopPolling();
            }
        } catch (_) {
            // Сетевая ошибка — молча игнорируем, попробуем на следующем тике
        }
    }

    _show(count) {
        if (!this._container) return;
        const label = this._pendingLabel(count);
        if (!this._el) {
            this._el = document.createElement('div');
            this._el.className = 'pending-banner';
            this._el.innerHTML = `
                <span class="pending-banner__text"></span>
                <button class="pending-banner__btn" type="button">Запустить индексацию</button>
            `;
            this._el.querySelector('.pending-banner__btn').addEventListener('click', () => this._triggerIndex());
            this._container.appendChild(this._el);
        }
        this._el.querySelector('.pending-banner__text').textContent = label;
        this._el.style.display = '';
    }

    _hide() {
        if (this._el) this._el.style.display = 'none';
    }

    async _triggerIndex() {
        if (!this._domainId) return;
        const btn = this._el?.querySelector('.pending-banner__btn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Запускается…';
        }
        try {
            const res = await fetch(
                `/api/v1/domains/${encodeURIComponent(this._domainId)}/index`,
                { method: 'POST' },
            );
            if (res.ok) {
                // Перезапускаем polling — indexer начал работу
                this._startPolling();
            }
        } catch (_) {
            // ignore
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Запустить индексацию';
            }
        }
    }

    /**
     * Возвращает строку с правильным склонением:
     * «1 файл ожидает индексации», «3 файла…», «5 файлов…»
     */
    _pendingLabel(n) {
        const mod100 = n % 100;
        const mod10  = n % 10;
        let form;
        if (mod100 >= 11 && mod100 <= 19) {
            form = 'файлов';
        } else if (mod10 === 1) {
            form = 'файл';
        } else if (mod10 >= 2 && mod10 <= 4) {
            form = 'файла';
        } else {
            form = 'файлов';
        }
        return `${n} ${form} ожидает индексации`;
    }
}
```

### 2. Изменения в `rag-backend/app/static/js/chat.js`

#### 2a. Конструктор `ChatManager` — добавить после `this.initEventListeners()`

```javascript
// Баннер pending-файлов (step-07)
this.pendingBanner = new PendingFilesBanner('chat-banner-area');
```

#### 2b. Метод `setupContextBar` — добавить в конец, после pipeline-логики

```javascript
// Запускаем / переключаем polling баннера
if (this.pendingBanner) {
    this.pendingBanner.setDomain(chat.domain_id || null);
}
```

#### 2c. Метод `reset()` — добавить перед `this.currentChatId = null`

> ⚠️ Используем `destroy()`, а **не** `setDomain(null)`.
> `destroy()` останавливает polling **и** удаляет DOM-элемент баннера,
> предотвращая утечку: при повторном открытии чата `setDomain()` создаст новый `_el`.

```javascript
if (this.pendingBanner) {
    this.pendingBanner.destroy();
}
```

### 3. HTML — добавить `#chat-banner-area` в `chat.html`

Вставить **перед** `#messages-container`:

```html
<!-- Баннер pending-files (step-07) -->
<div id="chat-banner-area"></div>
```

### 4. CSS — добавить стили баннера

В файл стилей чата (`chat.css` или `main.css`):

```css
.pending-banner {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 1rem;
    background: var(--color-warning-highlight, #fff3cd);
    border-bottom: 1px solid var(--color-warning, #e0a800);
    font-size: 0.875rem;
}

.pending-banner__text {
    flex: 1;
    color: var(--color-text, #333);
}

.pending-banner__btn {
    padding: 0.25rem 0.75rem;
    background: var(--color-primary, #01696f);
    color: #fff;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.875rem;
}

.pending-banner__btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
}
```

### 5. Подключение скрипта

В `chat.html` добавить **до** `chat.js`:

```html
<script src="/static/js/pending-banner.js"></script>
```

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `rag-backend/app/static/js/pending-banner.js` | Создать |
| `rag-backend/app/static/js/chat.js` | `+pendingBanner` в конструкторе, `setupContextBar`, `reset()` |
| `rag-backend/app/templates/chat.html` | `+#chat-banner-area` div, `+<script>` тег |
| `rag-backend/app/static/css/chat.css` (или `main.css`) | `+.pending-banner` стили |

## Зависимости

- Этап 5: `GET /api/v1/domains/{domain_id}/pending-files` и `POST /api/v1/domains/{domain_id}/index` должны быть зарегистрированы.

## Критерий готовности

- [ ] Баннер появляется при открытии чата с доменом, у которого есть pending-файлы
- [ ] Баннер скрыт если pending = 0
- [ ] Кнопка вызывает `POST /api/v1/domains/{domain_id}/index`
- [ ] Polling останавливается когда pending = 0
- [ ] `reset()` вызывает `destroy()` — polling останавливается, DOM очищается
- [ ] Нет утечки таймеров при переключении между чатами
- [ ] `STATUS.md` обновлён: этап 7 → ✅
