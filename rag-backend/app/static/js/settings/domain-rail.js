/**
 * DomainRail — модуль левого узкого сайдбара выбора домена.
 *
 * Пилот: вкладка Vault'ы. Будущие вкладки подключают по той же схеме.
 *
 * Публичный API (window.DomainRail):
 *   render(domains, activeDomainId, escapeHtml) → HTML-строка рейла
 *   attach(container, onSelect)                 → вешает обработчики кликов
 */
window.DomainRail = {
    /**
     * Возвращает HTML-строку для блока `.domain-rail`.
     *
     * @param {Array}    domains        — массив объектов домена из API
     * @param {string|null} activeDomainId — текущий выбранный domain_id (или null = «Все»)
     * @param {Function} escapeHtml     — this.escapeHtml из SettingsManager
     * @returns {string} HTML
     */
    render(domains, activeDomainId, escapeHtml) {
        // Фильтруем домен «default» — не показываем в рейле
        const visible = (domains || []).filter(d => {
            const id = d.domain_id || d.id || '';
            return id !== 'default';
        });

        const allActive = !activeDomainId ? ' domain-rail__item--active' : '';

        const items = visible.map(d => {
            const id = d.domain_id || d.id || '';
            const name = d.display_name || d.domain_id || d.id || id;
            const isActive = id === activeDomainId ? ' domain-rail__item--active' : '';
            return `<button
                class="domain-rail__item${isActive}"
                data-domain-id="${escapeHtml(id)}"
                title="${escapeHtml(name)}"
            >${escapeHtml(name)}</button>`;
        }).join('');

        return `<nav class="domain-rail" aria-label="Домены">
            <button class="domain-rail__item domain-rail__item--all${allActive}" data-domain-id="" title="Все домены">Все домены</button>
            ${items}
        </nav>`;
    },

    /**
     * Навешивает обработчики кликов на кнопки рейла внутри container.
     *
     * @param {Element}  container — DOM-контейнер с отрисованным рейлом
     * @param {Function} onSelect  — колбэк(domainId: string|null)
     *                               domainId === '' означает «Все домены»
     */
    attach(container, onSelect) {
        const rail = container.querySelector('.domain-rail');
        if (!rail) return;

        rail.addEventListener('click', e => {
            const btn = e.target.closest('.domain-rail__item');
            if (!btn) return;

            // Визуально переключаем active без ожидания перерисовки
            rail.querySelectorAll('.domain-rail__item').forEach(b =>
                b.classList.remove('domain-rail__item--active')
            );
            btn.classList.add('domain-rail__item--active');

            const domainId = btn.dataset.domainId || null;
            onSelect(domainId);
        });
    },
};
