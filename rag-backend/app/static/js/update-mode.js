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

/* global escapeHtml, renderMarkdown */

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
    unknown_state_op_index:              'Операция изменения контекста не найдена в сессии.',
    state_op_review_conflict:            'Операция изменения контекста уже обработана — обновите сессию.',
    config_version_conflict:             'Конфигурация полей изменилась — обновите сессию.',
    state_version_conflict:              'Контекст кампании изменился — обновите сессию.',
};

function _umErrorMsg(err) {
    if (err.code && UPDATE_MODE_ERROR_MESSAGES[err.code]) {
        return UPDATE_MODE_ERROR_MESSAGES[err.code];
    }
    return err.message || 'Неизвестная ошибка';
}

// Stage 5: human-readable labels for each patch op type. Used in the card header.
const STATE_P_OP_LABELS = {
    replace_single:    'Заменить',
    clear_single:      'Очистить',
    add_list_item:     'Добавить пункт',
    update_list_item:  'Обновить пункт',
    resolve_list_item: 'Закрыть пункт',
    remove_list_item:  'Удалить пункт',
};

// Ops that carry a text payload eligible for inline editing.
const STATE_P_TEXT_BEARING_OPS = new Set([
    'replace_single',
    'add_list_item',
    'update_list_item',
]);

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
// Render unified diff with per-line colour coding.
// Lines starting with '+' → green background (.um-diff-line--add)
// Lines starting with '-' → red background  (.um-diff-line--del)
// Lines starting with '@' → muted meta style (.um-diff-line--meta)
// Everything else          → plain           (.um-diff-line)
// ---------------------------------------------------------------------------
function _renderDiffHtml(rawDiff) {
    return rawDiff
        .split('\n')
        .map(line => {
            let cls = 'um-diff-line';
            if (line.startsWith('+') && !line.startsWith('+++')) {
                cls += ' um-diff-line--add';
            } else if (line.startsWith('-') && !line.startsWith('---')) {
                cls += ' um-diff-line--del';
            } else if (line.startsWith('@')) {
                cls += ' um-diff-line--meta';
            }
            return `<span class="${cls}">${_escapeHtml(line)}</span>`;
        })
        .join('\n');
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
        const lines = _renderDiffHtml(change.unified_diff);
        diffHtml = `
            <details class="um-change-diff">
                <summary class="um-change-diff__toggle">Показать diff</summary>
                <pre class="um-change-diff__pre">${lines}</pre>
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
        <div class="um-change-description">${_renderMarkdown(change.description)}</div>
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
// Stage 5: State-patch operation card helper is defined INSIDE _buildPanel
// (closure access to _pendingStateReview / _pendingStateEdits / render /
// _showEditBlock). See below.
// ---------------------------------------------------------------------------

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

    const vaultsBlock = `<div class="um-apply-result__vaults">${rows}</div>`;

    // Stage 5: state_patch_result отдельным блоком. Может быть null (кампания без
    // state fields, или state_ops не принимались / отклонялись).
    const stateResult = applyResp.state_patch_result;
    const stateBlock = stateResult ? _createStatePatchResultView(stateResult) : '';

    wrap.innerHTML = headline + vaultsBlock + stateBlock;
    return wrap;
}

// Stage 5: блок результата применения state_patch в apply-result.
function _createStatePatchResultView(stateResult) {
    const wrap = document.createElement('div');
    wrap.className = 'um-state-result';

    const hasApplied = (stateResult.applied_state_version || 0) > 0;
    const failed = Array.isArray(stateResult.failed_op_indexes)
        ? stateResult.failed_op_indexes
        : [];
    const applied = Array.isArray(stateResult.applied_op_indexes)
        ? stateResult.applied_op_indexes
        : [];
    const failedReasons = stateResult.failed_reasons || {};

    let headlineCls = 'um-state-result__headline--ok';
    let headlineText = '✓ Контекст кампании применён';
    if (!hasApplied && failed.length > 0) {
        headlineCls = 'um-state-result__headline--error';
        headlineText = '⚠ Контекст кампании не применён';
    } else if (failed.length > 0) {
        headlineCls = 'um-state-result__headline--warn';
        headlineText = '⚠ Контекст кампании применён частично';
    }

    const headline = document.createElement('div');
    headline.className = `um-state-result__headline ${headlineCls}`;
    headline.textContent = headlineText;
    wrap.appendChild(headline);

    const meta = document.createElement('div');
    meta.className = 'um-state-result__meta';

    const lines = [];
    if (hasApplied) {
        lines.push(`Версия state: <strong>${_escapeHtml(String(stateResult.applied_state_version))}</strong>`);
        lines.push(`Конфигурация: v${_escapeHtml(String(stateResult.config_version))}`);
        if (applied.length > 0) {
            lines.push(`Применено операций: <strong>${applied.length}</strong>`);
        }
    }
    if (failed.length > 0) {
        lines.push(`Не применено операций: <strong>${failed.length}</strong>`);
    }
    meta.innerHTML = lines.join('<br>');
    wrap.appendChild(meta);

    if (failed.length > 0) {
        const list = document.createElement('ul');
        list.className = 'um-state-result__failure-list';
        for (const idx of failed) {
            const reason = failedReasons[String(idx)] || failedReasons[idx] || 'unknown_error';
            const li = document.createElement('li');
            li.textContent = `op_index=${idx}: ${reason}`;
            list.appendChild(li);
        }
        wrap.appendChild(list);
    }

    return wrap.outerHTML;
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
    let _showApplyHint = false;           // BUG-9 fix: part of render cycle instead of direct DOM
    let _openDiffs = new Set();           // change_ids of <details> that were open before render()

    // Stage 5: state-patch decision state (per-op_index).
    let _pendingStateReview = {};          // op_index → 'accept' | 'reject'
    let _pendingStateEdits = {};           // op_index → edited text (auto-accept)
    let _openStateEdits = new Set();       // op_index для открытых edit-block

    // BUG-NOTE-PRESERVE fix: хранит последнюю введённую заметку между попытками.
    // Используется при ошибке (retryBtn в _showError) и при пустом review-list
    // (retryBtn в _renderReview), чтобы текст не сбрасывался — пользователь
    // может отредактировать и повторно отправить без повторного ввода.
    // Записывается в _doStart до любых state-переходов; сбрасывается только
    // когда пользователь явно нажимает «Назад» из формы или успешно стартовал.
    let _lastNote = '';

    function _resetStateReview() {
        _pendingStateReview = {};
        _pendingStateEdits = {};
        _openStateEdits = new Set();
    }

    // -------- root element --------
    const panel = document.createElement('div');
    panel.className = 'um-panel';
    panel.dataset.chatId = chatId;

    // -------- render pipeline --------
    function render() {
        // Сохраняем открытые <details> перед уничтожением DOM
        _openDiffs = new Set(
            [...panel.querySelectorAll('.um-change-diff[open]')]
                .map(el => el.closest('.um-change-card')?.dataset.changeId)
                .filter(Boolean)
        );
        // Stage 5: сохраняем открытые state-edit блоки
        _openStateEdits = new Set(
            [...panel.querySelectorAll('.um-state-card[data-edit-open="1"]')]
                .map(el => el.dataset.opIndex)
                .filter(Boolean)
        );
        panel.innerHTML = '';
        panel.appendChild(_renderHeader());
        if (state === 'idle')               panel.appendChild(_renderIdle());
        else if (state === 'entering_note') panel.appendChild(_renderNoteForm());
        else if (state === 'starting')      panel.appendChild(_renderStarting());
        else if (state === 'review')        panel.appendChild(_renderReview());
        else if (state === 'applying')      panel.appendChild(_renderApplying());
        else if (state === 'result')        panel.appendChild(_renderResult());
        else if (state === 'error')         { /* error rendered in header */ }
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

    // BUG-13 fix: character counter for note textarea
    // BUG-NOTE-PRESERVE fix: textarea предзаполняется _lastNote — пользователь
    // может отредактировать и повторно отправить после ошибки, не вводя текст заново.
    // Курсор ставится в конец текста для удобства правки.
    function _renderNoteForm() {
        const MAX_LEN = 20000;
        const initial = _lastNote || '';
        const el = document.createElement('div');
        el.className = 'um-panel__note-form';
        el.innerHTML = `
            <label class="um-note-label" for="um-note-${chatId}">Заметка об изменениях:</label>
            <textarea class="um-note-textarea" id="um-note-${chatId}"
                placeholder="Например: добавить раздел про новую фичу X в документ Y…"
                maxlength="${MAX_LEN}" rows="5">${_escapeHtml(initial)}</textarea>
            <div class="um-note-counter">
                <span class="um-note-counter__current">${initial.length}</span> / ${MAX_LEN}
            </div>
            <div class="um-note-actions">
                <button class="um-note-btn um-note-btn--submit" type="button">Анализировать</button>
                <button class="um-note-btn um-note-btn--back" type="button">Назад</button>
            </div>
        `;

        const textarea = el.querySelector('textarea');
        const counter  = el.querySelector('.um-note-counter__current');

        // Update counter on every keystroke / paste
        textarea.addEventListener('input', () => {
            counter.textContent = textarea.value.length;
        });

        el.querySelector('.um-note-btn--back').addEventListener('click', () => {
            // BUG-NOTE-PRESERVE: «Назад» сбрасывает сохранённый текст —
            // пользователь явно вышел из режима ввода.
            _lastNote = '';
            state = 'idle'; render();
        });

        // FIX(double-click): локальный флаг внутри замыкания предотвращает
        // параллельный запуск двух _doStart при быстром двойном клике
        // до первого render() (state = 'starting').
        let _submitted = false;
        const submitBtn = el.querySelector('.um-note-btn--submit');
        submitBtn.addEventListener('click', () => {
            if (_submitted) return;
            const note = textarea.value.trim();
            if (!note) { textarea.focus(); return; }
            _submitted = true;
            submitBtn.disabled = true;
            _doStart(note);
        });

        // UX: autofocus textarea + ставим курсор в конец восстановленного текста.
        // selectionStart/End в конец — пользователь сразу правит продолжение,
        // а не вынужден кликать в конец строки.
        if (initial) {
            textarea.focus();
            const end = initial.length;
            try {
                textarea.setSelectionRange(end, end);
            } catch (_) { /* некоторые браузеры не поддерживают для textarea */ }
        } else {
            textarea.focus();
        }

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

        const hasFileChanges = !!(session.changes && session.changes.length > 0);
        const hasStateOps = !!(session.state_patch_operations && session.state_patch_operations.length > 0);

        // BUG-3 / FIX(empty-deadlock): при пустом review (ни файлов, ни state ops)
        // рендерим явные кнопки действий, иначе пользователь застрянет — кнопка
        // «Отмена» в header неочевидна.
        if (!hasFileChanges && !hasStateOps) {
            const empty = document.createElement('div');
            empty.className = 'um-panel__empty';
            empty.textContent = 'Изменений не обнаружено.';
            el.appendChild(empty);

            const emptyActions = document.createElement('div');
            emptyActions.className = 'um-panel__empty-actions';

            const retryBtn = document.createElement('button');
            retryBtn.className = 'um-note-btn um-note-btn--submit';
            retryBtn.type = 'button';
            retryBtn.textContent = 'Попробовать снова';
            // BUG-NOTE-PRESERVE fix: возвращаемся в 'entering_note' (не 'idle'),
            // чтобы _renderNoteForm() восстановил _lastNote. Серверная сессия
            // (если была) отменяется fire-and-forget — повторный _doStart
            // заведёт новую сессию.
            retryBtn.addEventListener('click', () => {
                chatAPI.updateModeCancel(chatId); // fire-and-forget
                session = null;
                _pendingReview = {};
                _resetStateReview();
                state = 'entering_note';
                render();
            });

            const closeBtn = document.createElement('button');
            closeBtn.className = 'um-note-btn um-note-btn--back';
            closeBtn.type = 'button';
            closeBtn.textContent = 'Закрыть';
            closeBtn.addEventListener('click', () => {
                chatAPI.updateModeCancel(chatId); // fire-and-forget
                panel.remove();
            });

            emptyActions.appendChild(retryBtn);
            emptyActions.appendChild(closeBtn);
            el.appendChild(emptyActions);
            return el;
        }

        // Stage 5: file changes + state-patch operations render независимо.
        // File changes сохраняем исходное поведение.
        if (hasFileChanges) {
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

            // Восстанавливаем открытые диффы, которые были до render()
            if (_openDiffs.size > 0) {
                changesList.querySelectorAll('.um-change-card').forEach(card => {
                    if (_openDiffs.has(card.dataset.changeId)) {
                        const details = card.querySelector('.um-change-diff');
                        if (details) details.open = true;
                    }
                });
            }

            el.appendChild(changesList);

            // Accept/Reject All controls для file changes
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
        }

        // Stage 5: state-patch operations section
        if (hasStateOps) {
            el.appendChild(_renderStatePatchSection(session.state_patch_operations));
        }

        // Footer: Save review + Apply
        const footer = document.createElement('div');
        footer.className = 'um-review-footer';

        // BUG-9 fix: hint is now part of the render cycle via _showApplyHint flag
        if (_showApplyHint) {
            const hint = document.createElement('div');
            hint.className = 'um-apply-hint';
            hint.textContent = 'Примите хотя бы одно изменение перед применением.';
            footer.appendChild(hint);
        }

        const saveBtn = document.createElement('button');
        saveBtn.className = 'um-review-btn um-review-btn--save';
        saveBtn.type = 'button';
        saveBtn.textContent = 'Сохранить разметку';
        saveBtn.addEventListener('click', _doSaveReview);

        // BUG-14 fix: disable Apply button when no accepted changes exist or apply is in flight.
        // Stage 5: учитываем принятые state-patch ops наряду с file changes.
        const pendingFileAcceptCount = Object.values(_pendingReview).filter(a => a === 'accept').length;
        const serverFileAcceptCount = hasFileChanges
            ? session.changes.filter(ch => ch.status === 'accepted').length
            : 0;
        const pendingStateAcceptCount = Object.values(_pendingStateReview).filter(a => a === 'accept').length
            + Object.keys(_pendingStateEdits).length;
        const serverStateAcceptCount = hasStateOps
            ? session.state_patch_operations.filter(o => o.status === 'accepted').length
            : 0;
        const hasAccepted = (
            pendingFileAcceptCount > 0 || serverFileAcceptCount > 0
            || pendingStateAcceptCount > 0 || serverStateAcceptCount > 0
        );

        const applyBtn = document.createElement('button');
        applyBtn.className = 'um-review-btn um-review-btn--apply';
        applyBtn.type = 'button';
        applyBtn.textContent = 'Применить принятые';
        applyBtn.disabled = !hasAccepted || _applying; // BUG-14
        applyBtn.addEventListener('click', () => {
            Promise.resolve(_doApply()).catch((err) => {
                console.error('update-mode apply unhandled:', err);
                if (_applying) {
                    _applying = false;
                    state = 'error';
                    if (panel.isConnected) {
                        render();
                    }
                }
            });
        });

        footer.appendChild(saveBtn);
        footer.appendChild(applyBtn);
        el.appendChild(footer);

        return el;
    }

    // Stage 5: рендер секции операций Campaign State patch.
    function _renderStatePatchSection(stateOps) {
        const section = document.createElement('div');
        section.className = 'um-state-section';

        const title = document.createElement('div');
        title.className = 'um-state-section__title';
        title.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>
                <path d="M12 8v4"/>
                <path d="M12 16h.01"/>
            </svg>
            <span>Изменения контекста кампании</span>
            <span class="um-state-section__hint">— ${stateOps.length}</span>
        `;
        section.appendChild(title);

        // Bulk actions (только для state-ops)
        const bulk = document.createElement('div');
        bulk.className = 'um-state-section__bulk';
        const acceptAllBtn = document.createElement('button');
        acceptAllBtn.className = 'um-bulk-btn';
        acceptAllBtn.type = 'button';
        acceptAllBtn.textContent = 'Принять все контекстные';
        acceptAllBtn.addEventListener('click', () => {
            stateOps.forEach(op => { _pendingStateReview[op.op_index] = 'accept'; });
            render();
        });
        const rejectAllBtn = document.createElement('button');
        rejectAllBtn.className = 'um-bulk-btn';
        rejectAllBtn.type = 'button';
        rejectAllBtn.textContent = 'Отклонить все контекстные';
        rejectAllBtn.addEventListener('click', () => {
            stateOps.forEach(op => { _pendingStateReview[op.op_index] = 'reject'; });
            render();
        });
        bulk.appendChild(acceptAllBtn);
        bulk.appendChild(rejectAllBtn);
        section.appendChild(bulk);

        // Карточки операций
        const list = document.createElement('div');
        list.className = 'um-state-list';

        for (const op of stateOps) {
            list.appendChild(_createStatePatchCard(op, _onToggleStateOp));
        }

        // Восстанавливаем открытые edit-блоки
        if (_openStateEdits.size > 0) {
            list.querySelectorAll('.um-state-card').forEach(card => {
                if (_openStateEdits.has(card.dataset.opIndex)) {
                    _showEditBlock(card, true);
                }
            });
        }

        section.appendChild(list);
        return section;
    }

    // Stage 5: helper для открытия/закрытия edit-блока на конкретной карточке.
    function _showEditBlock(card, open) {
        const editBlock = card.querySelector('.um-state-card__edit-block');
        const toggleBtn = card.querySelector('.um-state-card__edit-toggle');
        if (open) {
            if (editBlock) editBlock.style.display = '';
            if (toggleBtn) toggleBtn.textContent = 'Скрыть правку';
            card.dataset.editOpen = '1';
        } else {
            if (editBlock) editBlock.style.display = 'none';
            if (toggleBtn) toggleBtn.textContent = 'Изменить текст';
            delete card.dataset.editOpen;
        }
    }

    // Stage 5: карточка одной state-patch операции. Закрытие на _pendingStateReview,
    // _pendingStateEdits, render(), _showEditBlock() из closure _buildPanel.
    function _createStatePatchCard(op, onToggle) {
        const opType = op.operation ? op.operation.type : '';
        const opLabel = STATE_P_OP_LABELS[opType] || opType;

        const card = document.createElement('div');
        card.className = 'um-state-card';
        card.dataset.opIndex = String(op.op_index);

        // Resolve effective status с учётом pending review + edits.
        let effectiveStatus = op.status;
        if (_pendingStateReview[op.op_index] === 'accept') effectiveStatus = 'accepted';
        else if (_pendingStateReview[op.op_index] === 'reject') effectiveStatus = 'rejected';
        if (Object.prototype.hasOwnProperty.call(_pendingStateEdits, op.op_index)) effectiveStatus = 'accepted';
        card.dataset.status = effectiveStatus;

        // Header: type badge + field label + key + status badge
        const header = document.createElement('div');
        header.className = 'um-state-card__header';

        const opBadge = document.createElement('span');
        opBadge.className = `um-state-card__op-badge um-state-card__op-badge--${opType}`;
        opBadge.textContent = opLabel;
        header.appendChild(opBadge);

        const fieldEl = document.createElement('span');
        fieldEl.className = 'um-state-card__field';
        fieldEl.textContent = op.field_label || op.field_key;
        const keyEl = document.createElement('span');
        keyEl.className = 'um-state-card__field-key';
        keyEl.textContent = op.field_key;
        fieldEl.appendChild(keyEl);
        header.appendChild(fieldEl);

        header.appendChild(_statusBadge(effectiveStatus));
        card.appendChild(header);

        // Diff: «было → станет»
        const showFrom = (op.previous_text !== null && op.previous_text !== undefined);
        const showTo = (op.proposed_text !== null && op.proposed_text !== undefined);

        if (showFrom || showTo) {
            const diff = document.createElement('div');
            diff.className = 'um-state-card__diff';

            if (showFrom) {
                const fromLabel = document.createElement('div');
                fromLabel.className = 'um-state-card__diff-label';
                fromLabel.textContent = 'Было';
                diff.appendChild(fromLabel);
                const fromVal = document.createElement('div');
                fromVal.className = 'um-state-card__diff-value um-state-card__diff-value--from';
                if (op.previous_text === '') {
                    fromVal.classList.add('um-state-card__diff-value--empty');
                    fromVal.textContent = '(пусто)';
                } else {
                    fromVal.textContent = op.previous_text;
                }
                diff.appendChild(fromVal);
            }

            if (showTo) {
                const toLabel = document.createElement('div');
                toLabel.className = 'um-state-card__diff-label';
                toLabel.textContent = 'Станет';
                diff.appendChild(toLabel);
                const toVal = document.createElement('div');
                toVal.className = 'um-state-card__diff-value um-state-card__diff-value--to';
                toVal.textContent = op.proposed_text;
                diff.appendChild(toVal);
            }

            card.appendChild(diff);
        }

        // Reason (от LLM)
        if (op.operation && op.operation.reason) {
            const reason = document.createElement('div');
            reason.className = 'um-state-card__reason';
            reason.textContent = `Основание: ${op.operation.reason}`;
            card.appendChild(reason);
        }

        // Item-key hint (для list-операций)
        if (op.operation && op.operation.item_key) {
            const itemKey = document.createElement('div');
            itemKey.className = 'um-state-card__reason';
            const ik = document.createElement('span');
            ik.className = 'um-state-card__field-key';
            ik.textContent = `item_key: ${op.operation.item_key}`;
            itemKey.appendChild(document.createTextNode('Элемент списка: '));
            itemKey.appendChild(ik);
            card.appendChild(itemKey);
        }

        // Inline-edit block (только для text-bearing ops)
        const isTextBearing = STATE_P_TEXT_BEARING_OPS.has(opType);
        if (isTextBearing) {
            const editBlock = document.createElement('div');
            editBlock.className = 'um-state-card__edit-block';
            editBlock.style.display = 'none';

            const editLabel = document.createElement('div');
            editLabel.className = 'um-state-card__edit-label';
            editLabel.textContent = 'Изменить текст перед применением';
            editBlock.appendChild(editLabel);

            const textarea = document.createElement('textarea');
            textarea.className = 'um-state-card__edit-textarea';
            const hasPendingEdit = Object.prototype.hasOwnProperty.call(_pendingStateEdits, op.op_index);
            textarea.value = hasPendingEdit
                ? _pendingStateEdits[op.op_index]
                : (op.proposed_text || '');
            textarea.rows = 3;
            editBlock.appendChild(textarea);

            const editActions = document.createElement('div');
            editActions.className = 'um-state-card__edit-actions';

            const saveBtn = document.createElement('button');
            saveBtn.className = 'um-state-card__edit-save';
            saveBtn.type = 'button';
            saveBtn.textContent = 'Сохранить правку';
            saveBtn.addEventListener('click', () => {
                const newText = textarea.value;
                if (!newText || !newText.trim()) {
                    textarea.focus();
                    return;
                }
                _pendingStateEdits[op.op_index] = newText;
                // Сохранение правки автоматически принимает операцию (auto-accept).
                delete _pendingStateReview[op.op_index];
                _pendingStateReview[op.op_index] = 'accept';
                _showEditBlock(card, false);
                render();
            });
            editActions.appendChild(saveBtn);

            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'um-state-card__edit-cancel';
            cancelBtn.type = 'button';
            cancelBtn.textContent = 'Отменить';
            cancelBtn.addEventListener('click', () => {
                _showEditBlock(card, false);
            });
            editActions.appendChild(cancelBtn);

            editBlock.appendChild(editActions);
            card.appendChild(editBlock);
        }

        // Actions
        const actions = document.createElement('div');
        actions.className = 'um-state-card__actions';

        const acceptBtn = document.createElement('button');
        acceptBtn.className = 'um-change-btn um-change-btn--accept';
        if (effectiveStatus === 'accepted') acceptBtn.classList.add('is-active');
        acceptBtn.type = 'button';
        acceptBtn.dataset.action = 'accept';
        acceptBtn.title = 'Принять операцию';
        acceptBtn.textContent = '✓ Принять';
        acceptBtn.addEventListener('click', () => onToggle(op.op_index, 'accept'));
        actions.appendChild(acceptBtn);

        const rejectBtn = document.createElement('button');
        rejectBtn.className = 'um-change-btn um-change-btn--reject';
        if (effectiveStatus === 'rejected') rejectBtn.classList.add('is-active');
        rejectBtn.type = 'button';
        rejectBtn.dataset.action = 'reject';
        rejectBtn.title = 'Отклонить операцию';
        rejectBtn.textContent = '✕ Отклонить';
        rejectBtn.addEventListener('click', () => onToggle(op.op_index, 'reject'));
        actions.appendChild(rejectBtn);

        if (isTextBearing) {
            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'um-state-card__edit-toggle';
            toggleBtn.type = 'button';
            toggleBtn.textContent = 'Изменить текст';
            toggleBtn.addEventListener('click', () => {
                const isOpen = card.dataset.editOpen === '1';
                _showEditBlock(card, !isOpen);
                // При открытии edit-блока — авто-accept (как и сохранение)
                if (!isOpen) {
                    delete _pendingStateReview[op.op_index];
                    _pendingStateReview[op.op_index] = 'accept';
                    render();
                }
            });
            actions.appendChild(toggleBtn);
        }

        card.appendChild(actions);
        return card;
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
        // BUG-8 fix: cancel active server session before resetting to idle,
        // otherwise next _doStart will fail with session_already_active.
        const retryBtn = document.createElement('button');
        retryBtn.className = 'um-error-retry-btn';
        retryBtn.type = 'button';
        retryBtn.textContent = 'Попробовать снова';
        // BUG-NOTE-PRESERVE fix: возвращаемся в 'entering_note' (а не 'idle'),
        // чтобы _renderNoteForm() восстановил _lastNote — пользователь увидит
        // свой текст и сможет отредактировать/повторить без повторного ввода.
        retryBtn.addEventListener('click', async () => {
            retryBtn.disabled = true;
            retryBtn.textContent = 'Отмена сессии…';
            if (session) {
                try {
                    await chatAPI.updateModeCancel(chatId);
                } catch (_) { /* session may have already expired — safe to ignore */ }
                session = null;
            }
            _pendingReview = {};
            _resetStateReview();
            state = 'entering_note';
            render();
        });
        errEl.appendChild(retryBtn);
        panel.appendChild(errEl);
    }

    // -------- actions --------
    async function _doStart(note) {
        _showApplyHint = false; // BUG-9 fix: reset hint flag on fresh start
        // BUG-NOTE-PRESERVE fix: запоминаем текст ДО любых state-переходов —
        // _lastNote нужен если _doStart упадёт в _showError и пользователь
        // нажмёт «Попробовать снова». Записываем сюда, а не после успеха,
        // потому что при ошибке state не дойдёт до успешной ветки.
        _lastNote = note;
        state = 'starting';
        render();
        try {
            const resp = await chatAPI.updateModeStart(chatId, note);
            session = resp;
            _pendingReview = {};
            _resetStateReview();
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

    // Stage 5: state-patch toggle handler. Сохраняет симметрию с _onToggleChange,
    // плюс очищает pending edit при reject (правка не имеет смысла без принятия).
    function _onToggleStateOp(opIndex, action) {
        const idx = Number(opIndex);
        const current = _pendingStateReview[idx];
        if (
            (action === 'accept' && current === 'accept') ||
            (action === 'reject' && current === 'reject')
        ) {
            delete _pendingStateReview[idx];
            delete _pendingStateEdits[idx];
        } else {
            _pendingStateReview[idx] = action;
            if (action === 'reject') {
                // reject отменяет правку
                delete _pendingStateEdits[idx];
            }
        }
        render();
    }

    // BUG-12 fix: deduplicate accepted/rejected collection
    function _collectPendingLists() {
        const accepted = [];
        const rejected = [];
        for (const [id, action] of Object.entries(_pendingReview)) {
            if (action === 'accept') accepted.push(id);
            else rejected.push(id);
        }
        return { accepted, rejected };
    }

    // Stage 5: собирает state-patch decisions для отправки на сервер.
    // Возвращает null если нет ни одного решения — клиент сигнализирует серверу
    // «не обновляй state-решения» (back-compat со старым сервером, если такой есть).
    function _collectStatePatchDecisions() {
        const acceptedIndexes = [];
        const rejectedIndexes = [];
        for (const [idx, action] of Object.entries(_pendingStateReview)) {
            const i = Number(idx);
            if (action === 'accept') acceptedIndexes.push(i);
            else rejectedIndexes.push(i);
        }
        const edited = [];
        for (const [idx, text] of Object.entries(_pendingStateEdits)) {
            // edited имеет смысл только если op не rejected
            const i = Number(idx);
            if (_pendingStateReview[i] === 'reject') continue;
            edited.push({ op_index: i, text });
        }
        if (acceptedIndexes.length === 0 && rejectedIndexes.length === 0 && edited.length === 0) {
            return null;
        }
        const payload = {};
        if (acceptedIndexes.length > 0) payload.accepted_op_indexes = acceptedIndexes;
        if (rejectedIndexes.length > 0) payload.rejected_op_indexes = rejectedIndexes;
        if (edited.length > 0) payload.edited = edited;
        return payload;
    }

    async function _doSaveReview() {
        const { accepted, rejected } = _collectPendingLists(); // BUG-12
        const statePatchDecisions = _collectStatePatchDecisions();
        if (
            accepted.length === 0 && rejected.length === 0
            && statePatchDecisions === null
        ) return;
        try {
            const updated = await chatAPI.updateModeReview(
                chatId, accepted, rejected, statePatchDecisions
            );
            session = updated;
            _pendingReview = {};
            _resetStateReview();
            render();
        } catch (err) {
            _showError(_umErrorMsg(err));
        }
    }

    async function _doApply() {
        if (_applying) return;
        _showApplyHint = false; // BUG-9 fix: reset hint on each new attempt
        const { accepted, rejected } = _collectPendingLists(); // BUG-12
        const statePatchDecisions = _collectStatePatchDecisions();
        if (
            accepted.length > 0 || rejected.length > 0
            || statePatchDecisions !== null
        ) {
            try {
                const updated = await chatAPI.updateModeReview(
                    chatId, accepted, rejected, statePatchDecisions
                );
                session = updated;
                _pendingReview = {};
                _resetStateReview();
            } catch (err) {
                _showError(_umErrorMsg(err));
                return;
            }
        }
        // Stage 5: apply доступно если есть принятый file change ИЛИ state op.
        const hasAcceptedFile = session && session.changes &&
            session.changes.some(ch => ch.status === 'accepted');
        const hasAcceptedState = session && session.state_patch_operations &&
            session.state_patch_operations.some(op => op.status === 'accepted');
        if (!hasAcceptedFile && !hasAcceptedState) {
            // BUG-9 fix: set flag and re-render — hint stays alive through subsequent render() calls
            _showApplyHint = true;
            render();
            return;
        }
        _applying = true;
        state = 'applying';
        render();
        try {
            applyResult = await chatAPI.updateModeApply(chatId);
            _applying = false;              // BUG-1 fix: reset flag on success path
            // BUG-APPLY1 fix: переход в state='result' ДО guard'а isConnected.
            // Прежний код делал early-return при !isConnected, оставляя state='applying'
            // и спиннер «Применение изменений…» на экране, даже если apply уже прошёл.
            // Теперь финальный state ставится всегда; guard остался только для
            // невозможной ветки (панель уже удалена из DOM кем-то другим).
            state = 'result';
            if (panel.isConnected) {
                render();
            }
            // FIX(BUG-LIFECYCLE): UpdateModeLifecycle был undefined →
            // ReferenceError ломал success-ветку и оставлял спиннер навсегда.
            // Чистим сессию fire-and-forget через уже существующий chatAPI,
            // не блокируя рендер финального состояния.
            chatAPI.updateModeCancel(chatId).catch(() => { /* non-fatal */ });
        } catch (err) {
            _applying = false;
            // FIX(BUG-LIFECYCLE): сначала чистим сессию fire-and-forget,
            // затем показываем ошибку — даже если cleanup бросит,
            // спиннер уже ушёл и пользователь не залип на «Применение изменений…».
            const code = err && err.code;
            const shouldClear = !code || (code !== 'apply_in_progress' && code !== 'apply_already_started');
            if (shouldClear) {
                try {
                    chatAPI.updateModeCancel(chatId).catch(() => { /* non-fatal */ });
                } catch (_) { /* ignore */ }
            }
            if (!panel.isConnected) { return; }
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

window.createUpdateModePanel = createUpdateModePanel;
window.restoreUpdateModePanel = restoreUpdateModePanel;

