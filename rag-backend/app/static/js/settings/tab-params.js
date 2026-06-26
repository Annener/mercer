// tab-params.js — wrapped in IIFE to avoid global const re-declaration errors
// that broke tab-campaigns, tab-documents, tab-vaults etc.
(function () {
    const PARAMS_EXCLUDED_KEYS = new Set([
        'watchdog_auto_index_extensions',
    ]);

    const WATCHDOG_KNOWN_EXTENSIONS = ['.md', '.pdf', '.docx', '.txt', '.rst', '.html'];

    // Grouping config — order defines render order
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

        // ─────────────────────────────────────────────────────────────
        // Sidecar helpers
        // ─────────────────────────────────────────────────────────────

        /** Обновляет блок статуса sidecar в DOM. */
        _updateSidecarStatus(status) {
            const badge = document.getElementById('sidecar-status-badge');
            const pidEl = document.getElementById('sidecar-pid');
            if (!badge) return;

            badge.className = 'sidecar-status-badge';
            if (status.agent_unavailable) {
                badge.classList.add('sidecar-status--unavailable');
                badge.textContent = 'agent недоступен';
            } else if (!status.installed) {
                badge.classList.add('sidecar-status--not-installed');
                badge.textContent = 'не установлен';
            } else if (status.running) {
                badge.classList.add('sidecar-status--running');
                badge.textContent = 'запущен';
            } else {
                badge.classList.add('sidecar-status--stopped');
                badge.textContent = 'остановлен';
            }

            if (pidEl) {
                pidEl.textContent = status.running && status.pid ? `PID ${status.pid}` : '';
            }

            // Обновляем состояние кнопок
            const btnStart   = document.getElementById('sidecar-btn-start');
            const btnStop    = document.getElementById('sidecar-btn-stop');
            const btnRestart = document.getElementById('sidecar-btn-restart');
            const canControl = !status.agent_unavailable && status.installed;
            if (btnStart)   btnStart.disabled   = !canControl || status.running;
            if (btnStop)    btnStop.disabled    = !canControl || !status.running;
            if (btnRestart) btnRestart.disabled = !canControl || !status.running;
        },

        async _sidecarAction(action) {
            const msgEl = document.getElementById('sidecar-action-msg');
            const setMsg = (text, cls) => {
                if (!msgEl) return;
                msgEl.textContent = text;
                msgEl.className = `sidecar-action-msg sidecar-msg--${cls}`;
            };

            setMsg('Выполняется...', 'loading');
            try {
                let result;
                if (action === 'start')   result = await this.api.sidecarStart();
                if (action === 'stop')    result = await this.api.sidecarStop();
                if (action === 'restart') result = await this.api.sidecarRestart();
                setMsg(result.message || 'Готово', 'ok');
            } catch (err) {
                setMsg(`Ошибка: ${err.message}`, 'error');
            } finally {
                // Обновляем статус после действия
                try {
                    const status = await this.api.getSidecarStatus();
                    this._updateSidecarStatus(status);
                } catch (_) {}
            }
        },

        /** Открывает модальное окно и запускает SSE-поток install.sh. */
        _openInstallModal() {
            const modal = document.getElementById('sidecar-install-modal');
            const output = document.getElementById('sidecar-install-output');
            const closeBtn = document.getElementById('sidecar-install-modal-close');
            const title = document.getElementById('sidecar-install-modal-title');
            if (!modal || !output) return;

            output.textContent = '';
            title.textContent = 'Установка PDF Sidecar';
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');

            // Закрытие
            const closeModal = () => {
                modal.classList.add('hidden');
                modal.setAttribute('aria-hidden', 'true');
                if (this._installEventSource) {
                    this._installEventSource.close();
                    this._installEventSource = null;
                }
            };
            if (closeBtn) closeBtn.onclick = closeModal;
            modal.onclick = (e) => { if (e.target === modal) closeModal(); };

            // SSE поток
            const url = this.api.getSidecarInstallStreamUrl();
            const es = new EventSource(url);
            this._installEventSource = es;

            es.onmessage = (ev) => {
                const line = ev.data;
                output.textContent += line + '\n';
                output.scrollTop = output.scrollHeight;

                if (line.startsWith('[DONE]')) {
                    es.close();
                    this._installEventSource = null;
                    title.textContent = 'Установка завершена';
                    // Обновляем статус после установки
                    this.api.getSidecarStatus().then(s => this._updateSidecarStatus(s)).catch(() => {});
                }
            };

            es.onerror = () => {
                output.textContent += '\n[Соединение прервано]\n';
                es.close();
                this._installEventSource = null;
            };
        },

        // ─────────────────────────────────────────────────────────────
        // Main render
        // ─────────────────────────────────────────────────────────────

        async renderParamsTab() {
            const params = await this.api.getSettingsParams();

            const descriptions = {
                'retrieval.enabled':                { label: 'RAG включён',                        desc: 'Включает поиск по базе знаний при ответе. Если выключить — ИИ отвечает только из своей памяти.' },
                'retrieval.top_k':                  { label: 'Top-K результатов',                  desc: 'Сколько фрагментов документов передавать ИИ при каждом запросе. Рекомендуется 5–15.' },
                'chunking.chunk_size':              { label: 'Размер чанка',                        desc: 'Максимальное количество символов в одном фрагменте документа при индексации. Рекомендуется 1000–3000.' },
                'chunking.overlap':                 { label: 'Перекрытие чанков',                   desc: 'Сколько символов повторяется между соседними чанками. Рекомендуется 32–128.' },
                'chunking.entity_aware_mode':       { label: 'Режим осведомлённости об объектах',   desc: 'При нарезке учитывает границы сущностей (персонажи, места). Улучшает качество для D&D текстов.' },
                'chat.max_clarification_turns':     { label: 'Макс. уточняющих вопросов',           desc: 'Сколько раз ИИ может переспросить перед ответом. 0 — отвечает сразу.' },
                'chat.stream_answers':              { label: 'Стриминг ответов',                    desc: 'Ответ появляется постепенно, слово за словом. Если выключить — появится весь сразу.' },
                'chat.auto_title':                  { label: 'Авто-название чата',                  desc: 'Автоматически придумывает название для нового чата.' },
                'pdf_sidecar.url':                  { label: 'URL PDF-Sidecar',                     desc: 'Адрес вспомогательного сервиса для извлечения текста из PDF. Например: http://host.docker.internal:8765.' },
                'pdf_sidecar.timeout_seconds':      { label: 'Таймаут PDF-Sidecar (сек)',           desc: 'Сколько секунд ждать ответа от PDF-Sidecar.' },
                'pdf_sidecar.fallback_to_pdfminer': { label: 'Fallback на PDF-miner',               desc: 'Если PDF-Sidecar недоступен — использовать встроенный pdfminer.' },
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
                        ${info.desc ? `<span class="settings-param-desc">${this.escapeHtml(info.desc)}</span>` : ''}
                    </div>
                    ${inputHtml}
                </div>`;
            };

            const groupsHtml = PARAM_GROUPS.map(group => {
                const rowsHtml = group.keys.map(renderParamRow).filter(Boolean).join('');
                if (!rowsHtml) return '';
                return `
                <div class="settings-group" id="group-${group.id}">
                    <h3 class="settings-group-title">${this.escapeHtml(group.title)}</h3>
                    ${rowsHtml}
                </div>`;
            }).join('');

            const ungroupedHtml = ungroupedKeys.length
                ? `<div class="settings-group" id="group-other">
                    <h3 class="settings-group-title">Прочие параметры</h3>
                    ${ungroupedKeys.map(renderParamRow).filter(Boolean).join('')}
                   </div>`
                : '';

            // Watchdog extensions
            const watchdogExts = await this.api.getWatchdogExtensions().catch(() => []);
            const enabledExts = new Set(watchdogExts);
            const allExts = [...new Set([...WATCHDOG_KNOWN_EXTENSIONS, ...watchdogExts])].sort();
            const extRowsHtml = allExts.map(ext => `
                <label class="settings-param-row indexing-ext-row">
                    <input type="checkbox" data-ext="${this.escapeHtml(ext)}" ${enabledExts.has(ext) ? 'checked' : ''}>
                    <span>${this.escapeHtml(ext)}</span>
                </label>`).join('');

            return `
            <form id="params-form" onsubmit="return false;">
                ${groupsHtml}
                ${ungroupedHtml}

                <div class="settings-group" id="group-watchdog">
                    <h3 class="settings-group-title">Watchdog — отслеживаемые расширения</h3>
                    <p class="settings-param-desc">Файлы с этими расширениями будут автоматически индексироваться при добавлении в хранилище.</p>
                    <div id="watchdog-ext-list" class="watchdog-ext-list">
                        ${extRowsHtml}
                    </div>
                    <div class="watchdog-add-row">
                        <input id="watchdog-custom-ext" type="text" placeholder=".ext" class="watchdog-ext-input">
                        <button type="button" class="btn btn-secondary" data-action="add-watchdog-ext">Добавить</button>
                    </div>
                    <span id="watchdog-message" class="watchdog-message"></span>
                </div>

                <div class="params-actions">
                    <button type="button" class="btn btn-primary" data-action="save-params">Сохранить</button>
                    <button type="button" class="btn btn-outline" data-action="reset-params">Сбросить к умолчаниям</button>
                </div>
            </form>

            <div class="sidecar-block" id="sidecar-block">
                <h3 class="sidecar-block-title">PDF Sidecar</h3>
                <div class="sidecar-status-row">
                    <span class="sidecar-status-label">Статус:</span>
                    <span class="sidecar-status-badge sidecar-status--unknown" id="sidecar-status-badge">загрузка...</span>
                    <span class="sidecar-pid" id="sidecar-pid"></span>
                </div>
                <div class="sidecar-actions-row">
                    <button class="btn btn-primary btn-sm" id="sidecar-btn-start"   data-action="sidecar-start"   disabled>Запустить</button>
                    <button class="btn btn-secondary btn-sm" id="sidecar-btn-stop"  data-action="sidecar-stop"   disabled>Остановить</button>
                    <button class="btn btn-secondary btn-sm" id="sidecar-btn-restart" data-action="sidecar-restart" disabled>Перезапустить</button>
                    <button class="btn btn-outline btn-sm" id="sidecar-btn-install" data-action="sidecar-install">Установить / Переустановить</button>
                </div>
                <div class="sidecar-action-msg" id="sidecar-action-msg"></div>
            </div>

            <div class="sidecar-install-modal hidden" id="sidecar-install-modal" role="dialog" aria-modal="true" aria-hidden="true">
                <div class="sidecar-install-modal-box">
                    <div class="sidecar-install-modal-header">
                        <span id="sidecar-install-modal-title">Установка PDF Sidecar</span>
                        <button class="docs-modal-close" id="sidecar-install-modal-close" aria-label="Закрыть">✕</button>
                    </div>
                    <pre class="sidecar-install-output" id="sidecar-install-output"></pre>
                </div>
            </div>`;
        },

        // ─────────────────────────────────────────────────────────────
        // Bind sidecar actions (вызывается из _attachTabListeners)
        // ─────────────────────────────────────────────────────────────
        bindSidecarActions() {
            // Обработка кликов перенесена в handleParamsAction через _dispatch.
            // Метод оставлен для обратной совместимости — выполняет только загрузку статуса.
            this.api.getSidecarStatus()
                .then(s => this._updateSidecarStatus(s))
                .catch(() => this._updateSidecarStatus({ agent_unavailable: true }));
        },
    };

    Object.assign(SettingsManager.prototype, ParamsTabMixin);
})();
