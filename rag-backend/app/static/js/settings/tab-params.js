const SETTINGS_DEFAULTS = {
    'retrieval.enabled': true,
    'retrieval.top_k': 10,
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

// Keys managed elsewhere (not rendered in the generic params list)
const PARAMS_EXCLUDED_KEYS = new Set([
    'watchdog_auto_index_extensions',
]);

const WATCHDOG_KNOWN_EXTENSIONS = ['.md', '.pdf', '.docx', '.txt', '.rst', '.html'];

// Grouping config
const PARAM_GROUPS = [
    {
        id: 'chat',
        title: 'Настройки чатов',
        keys: [
            'chat.auto_title',
            'chat.stream_answers',
            'chat.max_clarification_turns',
        ],
    },
    {
        id: 'rag',
        title: 'Настройки взаимодействия с RAG',
        keys: [
            'retrieval.enabled',
            'retrieval.top_k',
        ],
    },
    {
        id: 'indexing',
        title: 'Настройки индексации',
        keys: [
            'pdf_sidecar.fallback_to_pdfminer',
            'chunking.chunk_size',
            'chunking.entity_aware_mode',
            'chunking.overlap',
            'pdf_sidecar.timeout_seconds',
            'pdf_sidecar.url',
        ],
    },
];

const ParamsTabMixin = {
    getParamType(key) {
        const boolKeys = [
            'retrieval.enabled',
            'chat.stream_answers',
            'chat.auto_title',
            'chunking.entity_aware_mode',
            'pdf_sidecar.fallback_to_pdfminer',
        ];
        return boolKeys.includes(key) ? 'bool' : 'string';
    },

    async renderParamsTab() {
        const params = await this.api.getSettingsParams();

        const descriptions = {
            'retrieval.enabled':                { label: 'RAG включён',                        desc: 'Включает поиск по базе знаний при ответе. Если выключить — ИИ отвечает только из своей памяти.' },
            'retrieval.top_k':                  { label: 'Top-K результатов',                 desc: 'Сколько фрагментов документов передавать ИИ при каждом запросе. Рекомендуется 5–15.' },
            'chunking.chunk_size':              { label: 'Размер чанка',                       desc: 'Максимальное количество символов в одном фрагменте документа при индексации. Рекомендуется 1000–3000.' },
            'chunking.overlap':                 { label: 'Перекрытие чанков',                  desc: 'Сколько символов повторяется между соседними чанками. Рекомендуется 32–128.' },
            'chunking.entity_aware_mode':       { label: 'Режим осведомлённости об объектах', desc: 'При нарезке учитывает границы сущностей (персонажи, места). Улучшает качество для D&D текстов.' },
            'chat.max_clarification_turns':     { label: 'Макс. уточняющих вопросов',         desc: 'Сколько раз ИИ может переспросить перед ответом. 0 — отвечает сразу.' },
            'chat.stream_answers':              { label: 'Стриминг ответов',                   desc: 'Ответ появляется постепенно, слово за словом. Если выключить — появится весь сразу.' },
            'chat.auto_title':                  { label: 'Авто-название чата',                 desc: 'Автоматически придумывает название для нового чата.' },
            'pdf_sidecar.url':                  { label: 'URL PDF-Sidecar',                    desc: 'Адрес вспомогательного сервиса для извлечения текста из PDF. Например: http://host.docker.internal:8765.' },
            'pdf_sidecar.timeout_seconds':      { label: 'Таймаут PDF-Sidecar (сек)',          desc: 'Сколько секунд ждать ответа от PDF-Sidecar.' },
            'pdf_sidecar.fallback_to_pdfminer': { label: 'Fallback на PDF-miner',              desc: 'Если PDF-Sidecar недоступен — использовать встроенный pdfminer.' },
        };

        // Collect all keyed params so we don't lose any not listed in PARAM_GROUPS
        const allFilteredKeys = new Set(
            Object.keys(params).filter(k => !PARAMS_EXCLUDED_KEYS.has(k))
        );
        const groupedKeys = new Set(PARAM_GROUPS.flatMap(g => g.keys));
        const ungroupedKeys = [...allFilteredKeys].filter(k => !groupedKeys.has(k)).sort();

        const renderParamRow = (key) => {
            if (!allFilteredKeys.has(key)) return '';
            const isBool = this.getParamType(key) === 'bool';
            const currentValue = params[key];
            const info = descriptions[key] || { label: key, desc: '' };
            const inputHtml = isBool
                ? `<input type="checkbox" data-key="${this.escapeHtml(key)}" ${(currentValue === true || currentValue === 'true') ? 'checked' : ''}>`
                : `<input data-key="${this.escapeHtml(key)}" value="${this.escapeHtml(currentValue ?? '')}">`;
            const tooltipHtml = info.desc
                ? `<span class="param-help" tabindex="0" aria-label="${this.escapeHtml(info.desc)}" data-tooltip="${this.escapeHtml(info.desc)}">?</span>`
                : '';
            return `
                <div class="settings-param-row">
                    <div class="settings-param-info">
                        <span class="settings-param-label-row">
                            <strong>${this.escapeHtml(info.label)}</strong>${tooltipHtml}
                        </span>
                    </div>
                    <div class="settings-param-control">
                        ${inputHtml}
                    </div>
                </div>`;
        };

        const renderGroup = (group) => {
            const rows = group.keys.map(k => renderParamRow(k)).filter(Boolean).join('');
            if (!rows) return '';
            return `
                <div class="settings-param-group">
                    <h3 class="settings-param-group-title">${this.escapeHtml(group.title)}</h3>
                    ${rows}
                </div>`;
        };

        // Load current watchdog extensions
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
            <label class="indexing-ext-row">
                <input type="checkbox"
                       data-ext="${this.escapeHtml(ext)}"
                       ${selectedSet.has(ext) ? 'checked' : ''}>
                <span>${this.escapeHtml(ext)}</span>
            </label>
        `).join('');

        // Render ungrouped keys (fallback, shouldn't normally show)
        const ungroupedRows = ungroupedKeys.map(k => renderParamRow(k)).filter(Boolean).join('');

        return `
            <div class="settings-toolbar">
                <button class="btn btn-secondary" data-action="reset-params">Сбросить все параметры</button>
            </div>
            <form id="params-form" class="settings-params-fullwidth">
                ${PARAM_GROUPS.map(g => renderGroup(g)).join('')}
                ${ungroupedRows ? `<div class="settings-param-group">${ungroupedRows}</div>` : ''}
            </form>

            <div class="settings-watchdog-block">
                <h3 class="settings-watchdog-title">Настройки Vault Watchdog</h3>
                <p class="settings-param-desc">
                    Файлы этих типов будут переиндексированы автоматически при изменении в vault-директории.
                </p>
                <div id="watchdog-ext-list" class="indexing-ext-list">
                    ${watchdogCheckboxesHtml}
                </div>
                <div class="indexing-custom-input">
                    <input type="text"
                           id="watchdog-custom-ext"
                           placeholder=".epub">
                    <button class="btn btn-secondary" data-action="add-watchdog-ext">Добавить</button>
                </div>
                <div id="watchdog-message" style="min-height: 1.2em; margin-top: 6px; font-size: 12px;"></div>
            </div>

            <div class="settings-params-footer">
                <button class="btn btn-primary" data-action="save-params">Сохранить параметры</button>
            </div>`;
    },
};

Object.assign(SettingsManager.prototype, ParamsTabMixin);
