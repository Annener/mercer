// ============================================================
// Update Mode Panel — Campaign context update UI
// ============================================================
//
// States:   idle → entering_note → starting → review → applying → result
//           any  → error
//
// Public API:
//   createUpdateModePanel(chatId) → HTMLElement
//   restoreUpdateModePanel(chatId, session) → HTMLElement   (restore from existing session)
// ============================================================

/* global chatAPI, escapeHtml, renderMarkdown */

// ---------------------------------------------------------------------------
// BUG-5 fix: defensive wrappers for escapeHtml / renderMarkdown
// Both are declared in chat.js which loads AFTER this file.
// Inside functions this is safe (called at runtime, not parse-time),
// but explicit guards prevent silent breakage if call sites drift.
// ---------------------------------------------------------------------------
function _escapeHtml(str) {
    if (typeof escapeHtml === 'function') return escapeHtml(str);
    // Minimal fallback so the panel degrades gracefully instead of throwing
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function _renderMarkdown(str) {
    if (typeof renderMarkdown === 'function') return renderMarkdown(str);
    return _escapeHtml(str);
}

// ---------------------------------------------------------------------------
// Error code → human-readable message
// ---------------------------------------------------------------------------
const UPDATE_MODE_ERROR_MESSAGES = {
    session_already_active:              'Сессия уже активна — завершите или отмените текущую.',
    chat_not_found:                      'Чат не найден.',
    campaign_required:                   'Для Update Mode необходим контекст (кампания).',
    campaign_not_found:                  'Контекст (кампания) не найден.',
    campaign_domain_mismatch:            'Кампания не соответствует домену чата.',
    campaign_tags_required:              'У кампании нет тегов — нечего обновлять.',
    no_enabled_vaults:                   'Нет активных хранилищ для кампании.',
    no_indexed_markdown:                 'Нет проиндексированных документов в хранилищах.',
    no_relevant_context:                 'По вашей заметке не найдено релевантных документов.',
    no_usable_context:                   'Найденных документов недостаточно для генерации изменений.',
    generation_provider_unavailable:     'Генеративная модель недоступна.',
    invalid_generation_output:           'Модель вернула некорректный ответ — попробуйте ещё раз.',
    indexer_unavailable:                 'Индексер недоступен.',
    indexer_invalid_response:            'Некорректный ответ индексера.',
    review_store_unavailable:            'Хранилище сессии недоступно.',
};

function _umErrorMsg(err) {
    if (err.code && UPDATE_MODE_ERROR_MESSAGES[err.code]) {
        return UPDATE_MODE_ERROR_MESSAGES[err.code];
    }
    return err.message || 'Неизвестная ошибка';
}

// ---------------------------------------------------------------------------
// Change status helpers
// ---------------------------------------------------------------------------
const STATUS_LABELS = {
    pending:            { text: 'Ожидает', cls: 'um-status--pending' },
    accepted:           { text: 'Принято', cls: 'um-status--accepted' },
    rejected:           { text: 'Отклонено', cls: 'um-status--rejected' },
    resolution_failed:  { text: 'Не разрешено', cls: 'um-status--failed' },
};

// BUG-10 fix: whitelist for change.action used in CSS class names
const ACTION_WHITELIST = new Set(['update', 'create']);

function _safeActionCls(action) {
    // Returns the action string only if it's in the whitelist;
    // falls back to 'unknown' to keep CSS class well-formed.
    return ACTION_WHITELIST.has(action) ? action : 'unknown';
}

function _statusBadge(status) {
    const s = STATUS_LABELS[status] || { text: status, cls: '' };
    return `<span class="um-status-badge ${_escapeHtml(s.cls)}">${_escapeHtml(s.text)}</span>`;
}

function _actionLabel(action) {
    return action === 'create' ? 'Создать' : 'Обновить';
}

// ---------------------------------------------------------------------------
// Change card
// ---------------------------------------------------------------------------
function _createChangeCard(change, onToggle) {
    const card = document.createElement('div');
    card.className = 'um-change-card';
    card.dataset.changeId = change.change_id;
    card.dataset.status = change.status;

    const isFailed = change.status === 'resolution_failed';
    const isRejected = change.status === 'rejected';
    const isAccepted = change.status === 'accepted';

    const fileName = (change.file_path || '').split('/').pop() || change.file_path || '—';

    let diffHtml = '';
    if (change.unified_diff) {
        const escaped = _escapeHtml(change.unified_diff);
        diffHtml = `
            <details class="um-change-diff">
                <summary class="um-change-diff__toggle">Показать diff</summary>
                <pre class="um-change-diff__pre">${escaped}</pre>
            </details>
        `;
    }

    let errorHtml = '';
    if (isFailed && change.error_message) {
        errorHtml = `<div class="um-change-error">${_escapeHtml(change.error_message)}</div>`;
    }

    let actionsHtml = '';
    if (!isFailed) {
        const acceptActive = isAccepted ? 'is-active' : '';
        const rejectActive = isRejected ? 'is-active' : '';
        actionsHtml = `
            <div class="um-change-actions">
                <button class="um-change-btn um-change-btn--accept ${acceptActive}" type="button"
                    data-action="accept" title="Принять изменение">✓ Принять</button>
                <button class="um-change-btn um-change-btn--reject ${rejectActive}" type="button"
                    data-action="reject" title="Отклонить изменение">✕ Отклонить</button>
            </div>
        `;
    }

    // BUG-10 fix: use _safeActionCls() instead of escapeHtml(change.action) in CSS class
    card.innerHTML = `
        <div class="um-change-header">
            <span class="um-change-action-badge um-change-action-badge--${_safeActionCls(change.action)}">
                ${_escapeHtml(_actionLabel(change.action))}
            </span>
            <span class="um-change-filename" title="${_escapeHtml(change.file_path || '')}">
                ${_escapeHtml(fileName)}
            </span>
            ${_statusBadge(change.status)}
        </div>
        <div class="um-change-description">${_escapeHtml(change.description)}</div>
        ${errorHtml}
        ${diffHtml}
        ${actionsHtml}
    `;

    if (!isFailed) {
        card.querySelectorAll('.um-change-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                onToggle(change.change_id, action);
            });
        });
    }

    return card;
}

// ---------------------------------------------------------------------------
// Apply result card
// ---------------------------------------------------------------------------
function _createApplyResultView(applyResp) {
    const wrap = document.createElement('div');
    wrap.className = 'um-apply-result';

    const allOk = applyResp.results.every(r => r.status === 'applied');
    const headline = allOk
        ? '<div class="um-apply-result__headline um-apply-result__headline--ok">✓ Изменения применены</div>'
        : '<div class="um-apply-result__headline um-apply-result__headline--warn">⚠ Применено с предупреждениями</div>';

    const rows = applyResp.results.map(r => {
        const statusCls = r.status === 'applied' ? 'um-vault-result--ok'
            : r.status === 'no_changes' ? 'um-vault-result--neutral'
            : 'um-vault-result--error';
        const commitInfo = r.commit_sha
            ? `<span class="um-vault-result__commit" title="${_escapeHtml(r.commit_sha)}">commit: ${_escapeHtml(r.commit_sha.slice(0, 8))}</span>`
            : '';
        const reindexInfo = r.reindex_task_id
            ? `<span class="um-vault-result__reindex">Переиндексация: <code>${_escapeHtml(r.reindex_task_id)}</code></span>`
            : '';
        const errInfo = r.error_message
            ? `<div class="um-vault-result__error">${_escapeHtml(r.error_message)}</div>`
            : '';
        // BUG-4 fix: cast to Number, fallback to 0, then _escapeHtml(String(...)) to prevent XSS
        const appliedCount = _escapeHtml(String(typeof r.applied_count === 'number' ? r.applied_count : Number(r.applied_count) || 0));
        return `
            <div class="um-vault-result ${statusCls}">
                <div class="um-vault-result__header">
                    <code class="um-vault-result__id">${_escapeHtml(r.vault_id)}</code>
                    <span class="um-vault-result__status">${_escapeHtml(r.status)}</span>
                    <span class="um-vault-result__count">${appliedCount} файл(ов)</span>
                    ${commitInfo}
                    ${reindexInfo}
                </div>
                ${errInfo}
            </div>
        `;
    }).join('');

    wrap.innerHTML = headline + `<div class="um-apply-result__vaults">${rows}</div>`;
    return wrap;
}

// ---------------------------------------------------------------------------
// Main panel factory
// ---------------------------------------------------------------------------

/**
 * Создаёт панель Update Mode.
 * @param {string} chatId
 * @returns {HTMLElement}
 */
function createUpdateModePanel(chatId) {
    return _buildPanel(chatId, null);
}

/**
 * Восстанавливает панель из уже существующей сессии (при loadChat).
 * @param {string} chatId
 * @param {object} session  — UpdateModeSessionResponse
 * @returns {HTMLElement}
 */
function restoreUpdateModePanel(chatId, session) {
    return _buildPanel(chatId, session);
}

function _buildPanel(chatId, initialSession) {
    // -------- state --------
    let state = initialSession ? 'review' : 'idle';
    let session = initialSession || null;  // UpdateModeSessionResponse
    let applyResult = null;               // ApplyUpdateModeResponse
    let _pendingReview = {};              // change_id → 'accept' | 'reject'
    let _applying = false;

    // -------- root element --------
    const panel = document.createElement('div');
    panel.className = 'um-panel';
    panel.dataset.chatId = chatId;

    // -------- render pipeline --------
    function render() {
        panel.innerHTML = '';
        panel.appendChild(_renderHeader());
        if (state === 'idle')          panel.appendChild(_renderIdle());
        else if (state === 'entering_note') panel.appendChild(_renderNoteForm());
        else if (state === 'starting') panel.appendChild(_renderStarting());
        else if (state === 'review')   panel.appendChild(_renderReview());
        else if (state === 'applying') panel.appendChild(_renderApplying());
        else if (state === 'result')   panel.appendChild(_renderResult());
        else if (state === 'error')    { /* error rendered in header */ }
    }

    function _renderHeader() {
        const h = document.createElement('div');
        h.className = 'um-panel__header';
        h.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <polyline points="23 4 23 10 17 10"/>
                <polyline points="1 20 1 14 7 14"/>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
            </svg>
            <span class="um-panel__title">Обновить контекст</span>
        `;
        // BUG-2 fix: exclude 'applying' — cancel button must not be available during active apply request
        if (state !== 'idle' && state !== 'entering_note' && state !== 'starting' && state !== 'applying') {
            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'um-panel__cancel-btn';
            cancelBtn.type = 'button';
            cancelBtn.textContent = 'Отмена';
            cancelBtn.title = 'Отменить сессию и закрыть панель';
            cancelBtn.addEventListener('click', _doCancel);
            h.appendChild(cancelBtn);
        }
        return h;
    }

    function _renderIdle() {
        const el = document.createElement('div');
        el.className = 'um-panel__idle';
        el.innerHTML = `<p class="um-panel__hint">Опишите изменения, которые нужно внести в документы контекста.</p>`;
        const startBtn = document.createElement('button');
        startBtn.className = 'um-panel__start-btn btn-primary';
        startBtn.type = 'button';
        startBtn.textContent = 'Написать заметку';
        startBtn.addEventListener('click', () => { state = 'entering_note'; render(); });
        el.appendChild(startBtn);
        return el;
    }

    function _renderNoteForm() {
        const el = document.createElement('div');
        el.className = 'um-panel__note-form';
        el.innerHTML = `
            <label class="um-note-label" for="um-note-${chatId}">Заметка об изменениях:</label>
            <textarea class="um-note-textarea" id="um-note-${chatId}"
                placeholder="Например: добавить раздел про новую фичу X в документ Y…"
                maxlength="20000" rows="5"></textarea>
            <div class="um-note-actions">
                <button class="um-note-btn um-note-btn--submit" type="button">Анализировать</button>
                <button class="um-note-btn um-note-btn--back" type="button">Назад</button>
            </div>
        `;
        el.querySelector('.um-note-btn--back').addEventListener('click', () => {
            state = 'idle'; render();
        });
        el.querySelector('.um-note-btn--submit').addEventListener('click', () => {
            const note = el.querySelector('textarea').value.trim();
            if (!note) { el.querySelector('textarea').focus(); return; }
            _doStart(note);
        });
        return el;
    }

    function _renderStarting() {
        const el = document.createElement('div');
        el.className = 'um-panel__loading';
        el.innerHTML = `
            <span class="um-spinner" aria-hidden="true"></span>
            <span>Анализ документов и генерация изменений…</span>
        `;
        return el;
    }

    function _renderReview() {
        if (!session) return document.createElement('div');
        const el = document.createElement('div');
        el.className = 'um-panel__review';

        // Warnings
        if (session.warnings && session.warnings.length > 0) {
            const warn = document.createElement('div');
            warn.className = 'um-panel__warnings';
            warn.innerHTML = session.warnings.map(w =>
                `<div class="um-warning-item">⚠ ${_escapeHtml(w)}</div>`
            ).join('');
            el.appendChild(warn);
        }

        // BUG-3 fix: show explicit message when changes array is empty
        if (!session.changes || session.changes.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'um-panel__empty';
            empty.textContent = 'Изменений не обнаружено.';
            el.appendChild(empty);
            return el;
        }

        // Changes list
        const changesList = document.createElement('div');
        changesList.className = 'um-changes-list';

        // Build current display state from session + pending overrides
        const displayChanges = session.changes.map(ch => {
            const override = _pendingReview[ch.change_id];
            if (!override) return ch;
            return Object.assign({}, ch, {
                status: override === 'accept' ? 'accepted' : 'rejected',
            });
        });

        for (const ch of displayChanges) {
            changesList.appendChild(_createChangeCard(ch, _onToggleChange));
        }
        el.appendChild(changesList);

        // Accept/Reject All controls
        const bulkControls = document.createElement('div');
        bulkControls.className = 'um-bulk-controls';
        bulkControls.innerHTML = `
            <button class="um-bulk-btn" type="button" data-bulk="accept-all">Принять все</button>
            <button class="um-bulk-btn" type="button" data-bulk="reject-all">Отклонить все</button>
        `;
        bulkControls.querySelector('[data-bulk="accept-all"]').addEventListener('click', () => {
            session.changes.forEach(ch => {
                if (ch.status !== 'resolution_failed') _pendingReview[ch.change_id] = 'accept';
            });
            render();
        });
        bulkControls.querySelector('[data-bulk="reject-all"]').addEventListener('click', () => {
            session.changes.forEach(ch => {
                if (ch.status !== 'resolution_failed') _pendingReview[ch.change_id] = 'reject';
            });
            render();
        });
        el.appendChild(bulkControls);

        // Footer: Save review + Apply
        const footer = document.createElement('div');
        footer.className = 'um-review-footer';

        const saveBtn = document.createElement('button');
        saveBtn.className = 'um-review-btn um-review-btn--save';
        saveBtn.type = 'button';
        saveBtn.textContent = 'Сохранить разметку';
        saveBtn.addEventListener('click', _doSaveReview);

        const applyBtn = document.createElement('button');
        applyBtn.className = 'um-review-btn um-review-btn--apply';
        applyBtn.type = 'button';
        applyBtn.textContent = 'Применить принятые';
        applyBtn.addEventListener('click', _doApply);

        footer.appendChild(saveBtn);
        footer.appendChild(applyBtn);
        el.appendChild(footer);

        return el;
    }

    function _renderApplying() {
        const el = document.createElement('div');
        el.className = 'um-panel__loading';
        el.innerHTML = `
            <span class="um-spinner" aria-hidden="true"></span>
            <span>Применение изменений…</span>
        `;
        return el;
    }

    function _renderResult() {
        const el = document.createElement('div');
        el.className = 'um-panel__result';
        if (applyResult) {
            el.appendChild(_createApplyResultView(applyResult));
        }
        const closeBtn = document.createElement('button');
        closeBtn.className = 'um-result-close-btn';
        closeBtn.type = 'button';
        closeBtn.textContent = 'Закрыть';
        closeBtn.addEventListener('click', () => {
            panel.remove();
        });
        el.appendChild(closeBtn);
        return el;
    }

    // -------- error display --------
    function _showError(msg) {
        state = 'error';
        panel.innerHTML = '';
        panel.appendChild(_renderHeader());
        const errEl = document.createElement('div');
        errEl.className = 'um-panel__error';
        errEl.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <span>${_escapeHtml(msg)}</span>
        `;
        const retryBtn = document.createElement('button');
        retryBtn.className = 'um-error-retry-btn';
        retryBtn.type = 'button';
        retryBtn.textContent = 'Попробовать снова';
        retryBtn.addEventListener('click', () => { state = 'idle'; _pendingReview = {}; render(); });
        errEl.appendChild(retryBtn);
        panel.appendChild(errEl);
    }

    // -------- actions --------
    async function _doStart(note) {
        state = 'starting';
        render();
        try {
            const resp = await chatAPI.updateModeStart(chatId, note);
            // Promote to session-like shape (GET session has more fields;
            // StartUpdateModeResponse has changes + warnings + expires_at)
            session = resp;
            _pendingReview = {};
            state = 'review';
            render();
        } catch (err) {
            _showError(_umErrorMsg(err));
        }
    }

    function _onToggleChange(changeId, action) {
        const current = _pendingReview[changeId];
        // Toggle: click same button again → reset to original server status
        if (
            (action === 'accept' && current === 'accept') ||
            (action === 'reject' && current === 'reject')
        ) {
            delete _pendingReview[changeId];
        } else {
            _pendingReview[changeId] = action;
        }
        render();
    }

    async function _doSaveReview() {
        const accepted = [];
        const rejected = [];
        for (const [id, action] of Object.entries(_pendingReview)) {
            if (action === 'accept') accepted.push(id);
            else rejected.push(id);
        }
        if (accepted.length === 0 && rejected.length === 0) return;
        try {
            const updated = await chatAPI.updateModeReview(chatId, accepted, rejected);
            session = updated;
            _pendingReview = {};
            render();
        } catch (err) {
            _showError(_umErrorMsg(err));
        }
    }

    async function _doApply() {
        if (_applying) return;
        // Save any pending review before applying
        const accepted = [];
        const rejected = [];
        for (const [id, action] of Object.entries(_pendingReview)) {
            if (action === 'accept') accepted.push(id);
            else rejected.push(id);
        }
        if (accepted.length > 0 || rejected.length > 0) {
            try {
                const updated = await chatAPI.updateModeReview(chatId, accepted, rejected);
                session = updated;
                _pendingReview = {};
            } catch (err) {
                _showError(_umErrorMsg(err));
                return;
            }
        }
        const hasAccepted = session && session.changes &&
            session.changes.some(ch => ch.status === 'accepted');
        if (!hasAccepted) {
            // Nothing to apply — show gentle message
            const reviewEl = panel.querySelector('.um-review-footer');
            if (reviewEl) {
                let hint = reviewEl.querySelector('.um-apply-hint');
                if (!hint) {
                    hint = document.createElement('div');
                    hint.className = 'um-apply-hint';
                    hint.textContent = 'Примите хотя бы одно изменение перед применением.';
                    reviewEl.appendChild(hint);
                }
            }
            return;
        }
        _applying = true;
        state = 'applying';
        render();
        try {
            applyResult = await chatAPI.updateModeApply(chatId);
            _applying = false;              // BUG-1 fix: reset flag on success path
            if (!panel.isConnected) return; // BUG-2 fix: panel removed by concurrent _doCancel
            state = 'result';
            render();
        } catch (err) {
            _applying = false;
            if (!panel.isConnected) return; // BUG-2 fix: panel removed by concurrent _doCancel
            _showError(_umErrorMsg(err));
        }
    }

    async function _doCancel() {
        try {
            await chatAPI.updateModeCancel(chatId);
        } catch (_) { /* ignore cancel errors */ }
        panel.remove();
    }

    // -------- initial render --------
    render();
    return panel;
}

// Export to global scope (loaded as non-module defer script)
window.createUpdateModePanel = createUpdateModePanel;
window.restoreUpdateModePanel = restoreUpdateModePanel;
