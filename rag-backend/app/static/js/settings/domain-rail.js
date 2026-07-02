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
     * Палитра аватаров — цикличный список фоновых цветов для доменов.
     * Цвета подобраны в тонах проекта (#3498db, #2ecc71 и т.д.).
     */
    _avatarColors: [
        { bg: '#3498db', fg: '#fff' },
        { bg: '#27ae60', fg: '#fff' },
        { bg: '#8e44ad', fg: '#fff' },
        { bg: '#e67e22', fg: '#fff' },
        { bg: '#16a085', fg: '#fff' },
        { bg: '#c0392b', fg: '#fff' },
        { bg: '#2980b9', fg: '#fff' },
        { bg: '#d35400', fg: '#fff' },
    ],

    /**
     * Возвращает инициал домена (первая буква display_name или id, в upper case).
     */
    _initial(domain) {
        const name = domain.display_name || domain.domain_id || domain.id || '?';
        return name.charAt(0).toUpperCase();
    },

    /**
     * Возвращает цвет аватара для домена по его порядковому индексу.
     */
    _avatarColor(index) {
        return this._avatarColors[index % this._avatarColors.length];
    },

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

        const allAvatar = `<span class="domain-rail__avatar" style="background:#e8eef5;color:#526579;">&#9776;</span>`;

        const items = visible.map((d, idx) => {
            const id = d.domain_id || d.id || '';
            const name = d.display_name || d.domain_id || d.id || id;
            const isActive = id === activeDomainId ? ' domain-rail__item--active' : '';
            const initial = this._initial(d);
            const color = this._avatarColor(idx);
            const avatarStyle = isActive
                ? '' /* цвет управляется CSS для --active */
                : `style="background:${color.bg};color:${color.fg};"`;
            return `<button
                class="domain-rail__item${isActive}"
                data-domain-id="${escapeHtml(id)}"
                title="${escapeHtml(name)}"
            ><span class="domain-rail__avatar"${avatarStyle}>${escapeHtml(initial)}</span
            ><span class="domain-rail__label">${escapeHtml(name)}</span></button>`;
        }).join('');

        return `<nav class="domain-rail" aria-label="Домены">
            <span class="domain-rail__heading">Домены</span>
            <button class="domain-rail__item domain-rail__item--all${allActive}" data-domain-id="" title="Все домены">${allAvatar}<span class="domain-rail__label">Все домены</span></button>
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
