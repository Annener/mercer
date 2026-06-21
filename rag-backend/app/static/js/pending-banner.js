/**
 * PendingFilesBanner
 *
 * Показывает/скрывает баннер с количеством pending-файлов домена.
 * Polling каждые 30 секунд пока есть pending-файлы.
 *
 * Использование:
 *   const banner = new PendingFilesBanner('chat-banner-area');
 *   banner.setDomain('domain-42'); // запускает polling
 *   banner.destroy();              // останавливает polling, убирает DOM
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
