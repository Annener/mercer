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
