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

### API endpoint

```
GET /api/v1/domains/{domain_id}/pending-files
→ { domain_id, total_pending, vaults: [{vault_id, pending_count}] }
```

Endpoint определён в `rag-backend/app/api/watchdog_settings.py` (этап 5).
Он проксируется через `rag-backend` — дополнительных запросов к `rag-indexer`
напрямую с фронтенда не требуется.

## Что нужно сделать

### Новый файл `rag-backend/app/static/js/pending-banner.js`

```js
/**
 * PendingFilesBanner — баннер pending-файлов для чата.
 *
 * Архитектура: vanilla JS класс, аналогично ChatManager.
 * Polling раз в POLL_MS миллисекунд.
 * Баннер показывается только если total_pending > 0.
 */
class PendingFilesBanner {
  constructor(container) {
    this._container = container;  // DOM-элемент, куда вставляется баннер
    this._domainId = null;
    this._onStartIndex = null;
    this._timer = null;
    this._el = null;
    this._starting = false;
    this.POLL_MS = 30_000;
  }

  /**
   * Устанавливает домен и коллбэк запуска индексации.
   * Вызывать при каждой смене чата (в ChatManager.loadChat).
   * @param {string|null} domainId
   * @param {() => Promise<void>} onStartIndex
   */
  setDomain(domainId, onStartIndex) {
    this._domainId = domainId;
    this._onStartIndex = onStartIndex;
    this._startPolling();
  }

  /** Останавливает polling (вызвать при уничтожении чата / смене страницы). */
  destroy() {
    clearInterval(this._timer);
    this._timer = null;
    if (this._el) {
      this._el.remove();
      this._el = null;
    }
  }

  // --- private ---

  _startPolling() {
    clearInterval(this._timer);
    this._el?.remove();
    this._el = null;
    if (!this._domainId) return;
    this._poll();  // немедленный первый запрос
    this._timer = setInterval(() => this._poll(), this.POLL_MS);
  }

  async _poll() {
    if (!this._domainId) return;
    try {
      const res = await fetch(`/api/v1/domains/${this._domainId}/pending-files`);
      if (!res.ok) return;
      const data = await res.json();
      this._render(data.total_pending || 0);
    } catch {
      // сеть недоступна — баннер не трогаем
    }
  }

  _render(count) {
    if (count === 0) {
      if (this._el) { this._el.remove(); this._el = null; }
      return;
    }
    if (!this._el) {
      this._el = document.createElement('div');
      this._el.className = 'pending-banner';
      this._container.prepend(this._el);
    }
    // Склонение для русского языка: 1 → файл, 2-4 → файла, 5+ → файлов
    const label = _pendingLabel(count);
    this._el.innerHTML = `
      <span>› ${label} ожидают индексации</span>
      <button class="pending-banner__btn"${this._starting ? ' disabled' : ''}>
        ${this._starting ? 'Запуск…' : 'Запустить индексацию'}
      </button>`;
    this._el.querySelector('.pending-banner__btn').onclick = () => this._handleStart();
  }

  async _handleStart() {
    if (this._starting || !this._onStartIndex) return;
    this._starting = true;
    this._render(1);  // перерисовка с disabled-кнопкой
    try {
      await this._onStartIndex();
      this._render(0);
    } catch (e) {
      console.error('PendingFilesBanner: indexing start failed', e);
    } finally {
      this._starting = false;
      this._poll();
    }
  }
}

/**
 * Русское склонение: «1 файл», «2 файла», «5 файлов».
 * @param {number} n
 * @returns {string}
 */
function _pendingLabel(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
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
  return `${n} ${form}`;
}
```

### CSS в `rag-backend/app/static/css/main.css` (или отдельный файл)

```css
.pending-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--color-warning-highlight, #fff8e1);
  border-left: 4px solid var(--color-warning, #f59e0b);
  border-radius: 4px;
  font-size: 0.9rem;
  margin-bottom: 8px;
}
.pending-banner__btn {
  padding: 4px 12px;
  background: var(--color-warning, #f59e0b);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.pending-banner__btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
```

### Интеграция в `ChatManager` (`chat.js`)

#### 1. Инициализация в конструкторе

```js
// В конструкторе ChatManager, после this.initEventListeners():
const bannerContainer = document.getElementById('chat-banner-area');
this.pendingBanner = bannerContainer
  ? new PendingFilesBanner(bannerContainer)
  : null;
```

> `#chat-banner-area` — новый `<div>` в шаблоне чата, добавляется над областью сообщений.
> Если элемент не найден, баннер молча отключается (безопасный fallback).

#### 2. Запуск polling при загрузке чата

В `ChatManager.loadChat()`, после `await this.setupContextBar(data.chat)`:

```js
if (this.pendingBanner) {
  this.pendingBanner.setDomain(
    data.chat.domain_id || null,
    () => this._startIndexingForDomain(data.chat.domain_id),
  );
}
```

#### 3. Метод запуска индексации

```js
/**
 * Запускает индексацию всех vault-ов домена через rag-backend.
 * rag-backend проксирует задачу в rag-indexer.
 * @param {string} domainId
 */
async _startIndexingForDomain(domainId) {
  const res = await fetch(`/api/v1/domains/${domainId}/index`, { method: 'POST' });
  if (!res.ok) throw new Error(`Indexing start failed: ${res.status}`);
}
```

> ⚠️ Endpoint `POST /api/v1/domains/{domain_id}/index` должен быть добавлен
> в `rag-backend/app/api/watchdog_settings.py` или отдельный роутер.
> Реализация: получает все vault-ы домена из PG и отправляет
> `POST /api/v1/tasks` в `rag-indexer` для каждого vault.

#### 4. Остановка при сбросе чата

В `ChatManager.reset()`:

```js
if (this.pendingBanner) {
  this.pendingBanner.setDomain(null, null);
}
```

### HTML-шаблон (`chat.html`)

Добавить перед контейнером сообщений:

```html
<div id="chat-banner-area"></div>
<div id="messages-container"></div>
```

### Порядок подключения скриптов

`pending-banner.js` должен быть загружен **до** `chat.js`:

```html
<script src="/static/js/pending-banner.js"></script>
<script src="/static/js/chat.js"></script>
```

## Файлы для создания / изменения

| Файл | Действие |
|---|---|
| `rag-backend/app/static/js/pending-banner.js` | Создать |
| `rag-backend/app/static/css/main.css` | `+.pending-banner` стили |
| `rag-backend/app/static/js/chat.js` | `+PendingFilesBanner` в конструкторе, `+setDomain` в `loadChat`, `+_startIndexingForDomain`, `+setDomain(null)` в `reset` |
| `rag-backend/app/static/chat.html` | `+<div id="chat-banner-area">` перед `#messages-container` |

## Открытые зависимости

- `POST /api/v1/domains/{domain_id}/index` — endpoint запуска индексации по домену.
  Если он отсутствует, добавить в `step-05` или создать `step-05b`.
  Логика: `GET vaults WHERE domain_id=X` → `POST /api/v1/tasks` (rag-indexer) для каждого vault.

## Критерий готовности

- [ ] Баннер виден только при `total_pending > 0`
- [ ] Polling останавливается при `setDomain(null)` / `destroy()`
- [ ] При смене чата (смене `domain_id`) polling перезапускается
- [ ] Кнопка заблокирована во время запуска (`disabled`)
- [ ] Корректное склонение: 1 файл / 2 файла / 5 файлов
- [ ] `pending-banner.js` загружается до `chat.js`
- [ ] `STATUS.md` обновлён: этап 7 → ✅
