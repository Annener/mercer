/**
 * PendingFilesBanner
 *
 * Показывает/скрывает баннер с количеством pending-файлов домена.
 * Polling каждые 30 секунд пока есть pending-файлы,
 * ускоряется до 5 секунд во время активной индексации.
 *
 * Использование:
 *   const banner = new PendingFilesBanner('chat-banner-area');
 *   banner.setDomain('domain-42'); // запускает polling
 *   banner.destroy();              // останавливает polling, убирает DOM
 */
class PendingFilesBanner {
    constructor(containerId) {
        this._container = document.getElementById(containerId);
        this._el = null;
        this._timer = null;
        this._domainId = null;
        this._indexing = false; // true пока идёт индексация
    }

    setDomain(domainId) {
        this._domainId = domainId;
        this._indexing = false;
        this._startPolling();
    }

    destroy() {
        this._stopPolling();
        if (this._el) {
            this._el.remove();
            this._el = null;
        }
        this._domainId = null;
        this._indexing = false;
    }

    // ------------------------------------------------------------------
    // Polling
    // ------------------------------------------------------------------

    _startPolling(interval = 30_000) {
        this._stopPolling();
        if (!this._domainId) {
            this._hide();
            return;
        }
        this._poll();
        this._timer = setInterval(() => this._poll(), interval);
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
                if (this._indexing) {
                    // Индексация ещё идёт — обновляем счётчик в статусной строке
                    this._showIndexing(data.total_pending);
                } else {
                    this._show(data.total_pending);
                }
            } else {
                // Pending-файлов нет — индексация завершена (или нечего делать)
                this._indexing = false;
                this._hide();
                this._stopPolling();
            }
        } catch (_) {
            // Сетевая ошибка — молча игнорируем
        }
    }

    // ------------------------------------------------------------------
    // DOM
    // ------------------------------------------------------------------

    /** Режим ожидания: «N файлов ожидает индексации» + кнопка «Запустить» */
    _show(count) {
        if (!this._container) return;
        this._ensureEl();
        this._el.querySelector('.pending-banner__text').textContent = this._pendingLabel(count);
        this._el.querySelector('.pending-banner__btn').style.display = '';
        this._el.querySelector('.pending-banner__btn').disabled = false;
        this._el.querySelector('.pending-banner__btn').textContent = 'Запустить индексацию';
        this._el.querySelector('.pending-banner__spinner').style.display = 'none';
        this._el.querySelector('.pending-banner__status').style.display = 'none';
        this._el.style.display = '';
    }

    /** Режим индексации: спиннер + «Индексация… (N файлов осталось)» */
    _showIndexing(remaining) {
        if (!this._container) return;
        this._ensureEl();
        const label = remaining != null
            ? `Индексация… (осталось ${remaining} ${this._fileForm(remaining)})`
            : 'Индексация…';
        this._el.querySelector('.pending-banner__text').textContent = '';
        this._el.querySelector('.pending-banner__btn').style.display = 'none';
        this._el.querySelector('.pending-banner__spinner').style.display = '';
        this._el.querySelector('.pending-banner__status').textContent = label;
        this._el.querySelector('.pending-banner__status').style.display = '';
        this._el.style.display = '';
    }

    _hide() {
        if (this._el) this._el.style.display = 'none';
    }

    _ensureEl() {
        if (this._el) return;
        this._el = document.createElement('div');
        this._el.className = 'pending-banner';
        this._el.innerHTML = `
            <span class="pending-banner__text"></span>
            <svg class="pending-banner__spinner" style="display:none" width="14" height="14"
                 viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-dasharray="20 14"/>
            </svg>
            <span class="pending-banner__status" style="display:none"></span>
            <button class="pending-banner__btn" type="button">Запустить индексацию</button>
        `;
        this._el.querySelector('.pending-banner__btn').addEventListener('click', () => this._triggerIndex());
        this._container.appendChild(this._el);
    }

    // ------------------------------------------------------------------
    // Trigger
    // ------------------------------------------------------------------

    async _triggerIndex() {
        if (!this._domainId) return;

        // Немедленно переключаемся в режим «индексируется»
        this._indexing = true;
        this._showIndexing(null);

        // Ускоряем polling до 5 с чтобы быстро поймать завершение
        this._startPolling(5_000);

        try {
            const res = await fetch(
                `/api/v1/domains/${encodeURIComponent(this._domainId)}/index`,
                { method: 'POST' },
            );
            if (!res.ok) {
                // Запуск не удался — откатываемся
                this._indexing = false;
                this._startPolling(30_000);
            }
        } catch (_) {
            this._indexing = false;
            this._startPolling(30_000);
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    _pendingLabel(n) {
        return `${n} ${this._fileForm(n)} ожидает индексации`;
    }

    _fileForm(n) {
        const mod100 = n % 100;
        const mod10  = n % 10;
        if (mod100 >= 11 && mod100 <= 19) return 'файлов';
        if (mod10 === 1)                   return 'файл';
        if (mod10 >= 2 && mod10 <= 4)      return 'файла';
        return 'файлов';
    }
}
