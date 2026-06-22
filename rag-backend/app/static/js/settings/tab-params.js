const SETTINGS_DEFAULTS = {
    'retrieval.enabled': true,
    'retrieval.top_k': 10,
    'retrieval.reranker_enabled': false,
    'chunking.chunk_size': 2000,
    'chunking.overlap': 64,
    'chunking.entity_aware_mode': true,
    'chat.max_clarification_turns': 3,
    'chat.stream_answers': true,
    'chat.auto_title': true,
    'pdf_sidecar.url': 'http://host.docker.internal:8765',
    'pdf_sidecar.timeout_seconds': 180,
    'pdf_sidecar.fallback_to_pdfminer': true,
};

const WATCHDOG_KNOWN_EXTENSIONS = ['.md', '.pdf', '.docx', '.txt', '.rst', '.html'];

const ParamsTabMixin = {
    getParamType(key) {
        const boolKeys = [
            'retrieval.enabled',
            'retrieval.reranker_enabled',
            'chat.stream_answers',
            'chat.auto_title',
            'chunking.entity_aware_mode',
            'pdf_sidecar.fallback_to_pdfminer',
        ];
        return boolKeys.includes(key) ? 'bool' : 'string';
    },

    async renderParamsTab() {
        const params = await this.api.getSettingsParams();
        const sortedKeys = Object.keys(params).sort();
        const descriptions = {
            'retrieval.enabled':                { label: 'RAG включён', desc: 'Включает поиск по базе знаний при ответе. Если выключить — ИИ отвечает только из своей памяти.' },
            'retrieval.top_k':                  { label: 'Top-K результатов', desc: 'Сколько фрагментов документов передавать ИИ при каждом запросе. Рекомендуется 5–15.' },
            'retrieval.reranker_enabled':       { label: 'Reranker включён (retrieval)', desc: 'Включает дополнительную модель переранжирования результатов поиска на уровне retrieval.' },
            'chunking.chunk_size':              { label: 'Размер чанка', desc: 'Максимальное количество символов в одном фрагменте документа при индексации. Рекомендуется 1000–3000.' },
            'chunking.overlap':                 { label: 'Перекрытие чанков', desc: 'Сколько символов повторяется между соседними чанками. Рекомендуется 32–128.' },
            'chunking.entity_aware_mode':       { label: 'Режим осведомлённости об объектах', desc: 'При нарезке учитывает границы сущностей (персонажи, места). Улучшает качество для D&D текстов.' },
            'chat.max_clarification_turns':     { label: 'Макс. уточняющих вопросов', desc: 'Сколько раз ИИ может переспросить перед ответом. 0 — отвечает сразу.' },
            'chat.stream_answers':              { label: 'Стриминг ответов', desc: 'Ответ появляется постепенно, слово за словом. Если выключить — появится весь сразу.' },
            'chat.auto_title':                  { label: 'Авто-название чата', desc: 'Автоматически придумывает название для нового чата.' },
            'pdf_sidecar.url':                  { label: 'URL PDF-Sidecar', desc: 'Адрес вспомогательного сервиса для извлечения текста из PDF. Например: http://host.docker.internal:8765.' },
            'pdf_sidecar.timeout_seconds':      { label: 'Таймаут PDF-Sidecar (сек)', desc: 'Сколько секунд ждать ответа от PDF-Sidecar.' },
            'pdf_sidecar.fallback_to_pdfminer': { label: 'Fallback на PDF-miner', desc: 'Если PDF-Sidecar недоступен — использовать встроенный pdfminer.' },
        };

        // Загружаем текущие watchdog-расширения
        let currentExtensions = [];
        try {
            const watchdogData = await this.api.getWatchdogExtensions();
            currentExtensions = watchdogData.auto_index_extensions || [];
        } catch (e) {
            console.error('Failed to load watchdog extensions', e);
        }
        const selectedSet = new Set(currentExtensions);
        const allExtensions = [
            ...WATCHDOG_KNOWN_EXTENSIONS,
            ...currentExtensions.filter(e => !WATCHDOG_KNOWN_EXTENSIONS.includes(e)),
        ];
        const watchdogCheckboxesHtml = allExtensions.map(ext => `
            <label class="settings-param-row indexing-ext-row">
                <input type="checkbox"
                       data-ext="${this.escapeHtml(ext)}"
                       ${selectedSet.has(ext) ? 'checked' : ''}>
                <span>${this.escapeHtml(ext)}</span>
            </label>
        `).join('');

        return `
            <div class="settings-toolbar">
                <button class="btn btn-secondary" data-action="reset-params">Сбросить все параметры</button>
            </div>
            <form id="params-form" class="settings-params-fullwidth">
                ${sortedKeys.map(key => {
                    const isBool = this.getParamType(key) === 'bool';
                    const currentValue = params[key];
                    const info = descriptions[key] || { label: key, desc: '' };
                    const inputHtml = isBool
                        ? `<input type="checkbox" data-key="${this.escapeHtml(key)}" ${(currentValue === true || currentValue === 'true') ? 'checked' : ''}>`
                        : `<input data-key="${this.escapeHtml(key)}" value="${this.escapeHtml(currentValue ?? '')}" style="width:100%; max-width:340px; box-sizing:border-box;">`;
                    return `
                        <div class="settings-param-row">
                            <div class="settings-param-info">
                                <strong>${this.escapeHtml(info.label)}</strong>
                                <span class="settings-param-desc">${this.escapeHtml(info.desc)}</span>
                                <span class="settings-param-key">${this.escapeHtml(key)}</span>
                            </div>
                            <div class="settings-param-control">
                                ${inputHtml}
                            </div>
                        </div>`;
                }).join('')}
            </form>

            <div class="settings-watchdog-block">
                <h3 class="settings-watchdog-title">Авто-индексация (Vault Watchdog)</h3>
                <p class="settings-param-desc">
                    Файлы этих типов будут переиндексированы автоматически при изменении в vault-директории.
                </p>
                <div id="watchdog-ext-list" class="indexing-ext-list">
                    ${watchdogCheckboxesHtml}
                </div>
                <div class="indexing-custom-input settings-toolbar">
                    <input type="text"
                           id="watchdog-custom-ext"
                           placeholder=".epub"
                           style="width: 140px;">
                    <button class="btn btn-secondary" data-action="add-watchdog-ext">Добавить</button>
                </div>
                <div id="watchdog-message" style="min-height: 1.5em; margin-top: 8px;"></div>
            </div>

            <div class="settings-params-footer">
                <button class="btn btn-primary" data-action="save-params">Сохранить параметры</button>
            </div>`;
    },
};

Object.assign(SettingsManager.prototype, ParamsTabMixin);
