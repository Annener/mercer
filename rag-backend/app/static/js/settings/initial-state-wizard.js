// Initial State Wizard — UI-overlay для Initial State (Stage 4 + 3.v2).
//
// Состояния: idle → loading_documents → select_documents → preview_starting
//   → review → applying → result → (error)
// Закрытие из любого состояния → удаление overlay, Redis-proposal не трогаем.
//
// Public API (window.InitialStateWizard):
//   open(campaignId, opts) — открыть Wizard для кампании.
//   close()                 — закрыть текущий Wizard (если открыт).
//
// Опции opts (все опциональны):
//   domainId        — string, используется для загрузки документов;
//   proposeFields   — boolean (default false) — Stage 3.v2: при 0 enabled-полей
//                     кампании ИЛИ для режима "Сформировать контекст с помощью ИИ".
//                     На preview Wizard прокинет propose_fields=true.
//   maxSuggestedFields — number (default 15) — soft cap для suggested_fields[].
//   onApplied()     — вызывается ПОСЛЕ успешного apply и ДО close();
//   onClosed()      — вызывается после close() (вне зависимости от apply).
//
// Если у кампании 0 enabled-полей и proposeFields=false, Wizard все равно
// позволит выбрать документы и запустить preview — backend вернёт 422
// no_fields_configured_no_propose, и Wizard покажет понятную ошибку.

(function () {
    'use strict';

    const PER_DOC_TOKEN_LIMIT = 32000;
    const TOTAL_TOKEN_BUDGET = 64000;

    const ERROR_MESSAGES = {
        no_markdown_documents:
            'В домене нет подходящих Markdown-документов.',
        document_not_markdown:
            'Некоторые выбранные документы не являются Markdown.',
        document_not_indexed:
            'Некоторые документы ещё не проиндексированы.',
        generation_provider_unavailable:
            'Генеративная модель недоступна.',
        invalid_generation_output:
            'Модель вернула некорректный ответ. Попробуйте ещё раз.',
        proposal_not_found:
            'Предложение не найдено или уже удалено.',
        proposal_expired:
            'Предложение истекло (TTL 3 часа). Сформируйте заново.',
        initial_already_applied:
            'Initial State уже применён ранее.',
        config_version_conflict:
            'Конфигурация полей изменилась. Обновите список полей и повторите.',
        source_snapshot_stale:
            'Некоторые источники изменились между preview и apply.',
        campaign_not_found:
            'Кампания не найдена.',
        no_campaign_tags:
            'У кампании нет тегов. Добавьте собственные или подключите глобальные, иначе Initial State невозможно сформировать.',
        no_fields_configured_no_propose:
            'У кампании нет ни одного поля. Откройте Wizard ещё раз или используйте режим «Сформировать контекст с помощью ИИ», который сам предложит поля.',
        suggested_field_key_conflict:
            'Конфликт ключа поля: одно из предложенных ИИ полей уже существует в кампании.',
        suggested_field_creation_failed:
            'Не удалось создать предложенное ИИ поле.',
    };

    function _errMessage(err) {
        if (err && typeof err.isCode === 'function') {
            for (const code of Object.keys(ERROR_MESSAGES)) {
                if (err.isCode(code)) return { code, text: ERROR_MESSAGES[code] };
            }
            if (typeof err.detail === 'string') return { code: null, text: err.detail };
            if (err.detail && typeof err.detail === 'object') {
                const c = err.detail.code;
                return { code: typeof c === 'string' ? c : null, text: JSON.stringify(err.detail) };
            }
        }
        return { code: null, text: (err && err.message) || 'Неизвестная ошибка' };
    }

    function _formatTokens(n) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('ru-RU');
    }

    function _modalHtml(campaignId) {
        return `
            <div class="iswizard" role="dialog" aria-modal="true" aria-label="Initial State Wizard" data-campaign-id="${_escapeHtml(campaignId)}">
                <div class="iswizard__panel">
                    <div class="iswizard__header">
                        <h3 class="iswizard__title">Initial State Wizard</h3>
                        <button class="iswizard__close" type="button" data-action="close" aria-label="Закрыть">✕</button>
                    </div>
                    <div class="iswizard__stepper">
                        <span class="iswizard__step iswizard__step--active" data-step="1"><span class="iswizard__step-num">1</span>Документы</span>
                        <span class="iswizard__step" data-step="2"><span class="iswizard__step-num">2</span>Сводка</span>
                        <span class="iswizard__step" data-step="3"><span class="iswizard__step-num">3</span>Результат</span>
                    </div>
                    <div class="iswizard__body" data-body></div>
                    <div class="iswizard__actions" data-actions></div>
                </div>
            </div>
        `;
    }

    // ----- Document helpers -----

    function _isMarkdown(doc) {
        return typeof doc.source_path === 'string'
            && doc.source_path.toLowerCase().endsWith('.md');
    }

    function _docIsOversized(doc) {
        return typeof doc.estimated_tokens === 'number'
            && doc.estimated_tokens > PER_DOC_TOKEN_LIMIT;
    }

    function _docTitle(doc) {
        return doc.title || doc.source_path || doc.id;
    }

    // ----- Module state -----

    let _active = null; // { overlay, panel, opts, controller }

    function _activeOpen() {
        return _active !== null && _active !== undefined;
    }

    function close() {
        if (!_active) return;
        const a = _active;
        _active = null;
        if (a.overlay && a.overlay.parentNode) {
            a.overlay.parentNode.removeChild(a.overlay);
        }
        if (typeof a.opts.onClosed === 'function') {
            try { a.opts.onClosed(); } catch (_) { /* ignore */ }
        }
    }

    function open(campaignId, opts) {
        if (!campaignId) throw new Error('campaignId is required');
        const o = opts || {};
        if (_activeOpen()) close();
        const api = window.chatAPI;
        if (!api) throw new Error('window.chatAPI is not available');

        const wrap = document.createElement('div');
        wrap.innerHTML = _modalHtml(campaignId);
        const overlay = wrap.firstElementChild;
        const panel = overlay.querySelector('.iswizard__panel');
        document.body.appendChild(overlay);

        const proposeFields = !!o.proposeFields;
        const maxSuggestedFields = Number.isFinite(o.maxSuggestedFields)
            ? o.maxSuggestedFields
            : 15;

        const ctx = {
            campaignId,
            opts: o,
            api,
            overlay,
            panel,
            step: 1,
            state: 'idle',
            documents: [],
            filteredDocuments: [],
            search: '',
            selectedIds: new Set(),
            proposal: null,
            appliedVersion: null,
            error: null,
            highlightDocIds: new Set(),
            campaignTagIds: [],
            // Stage 3.v2:
            proposeFields,
            maxSuggestedFields,
            // Suggested-field UI state (мутируется inline-edit'ом).
            suggestedFields: [], // [{key, label, description, mode, initial_status,
                                 //  single_value, list_value, accepted, originalKey}]
        };

        const controller = _buildController(ctx);
        _active = { overlay, panel, opts: o, controller };

        // Закрытие по клику на крестик или клик вне панели.
        overlay.addEventListener('click', (ev) => {
            if (ev.target === overlay) close();
        });
        panel.querySelector('[data-action="close"]').addEventListener('click', close);

        controller.start();
        return overlay;
    }

    // ----- Controller / state machine -----

    function _buildController(ctx) {
        const body = ctx.panel.querySelector('[data-body]');
        const actions = ctx.panel.querySelector('[data-actions]');

        function setState(next, extra) {
            ctx.state = next;
            if (next === 'review' || next === 'review_editing') ctx.step = 2;
            else if (next === 'result') ctx.step = 3;
            else ctx.step = 1;
            if (extra) Object.assign(ctx, extra);
            render();
        }

        function clearError() {
            ctx.error = null;
        }

        function setStep(n) {
            ctx.step = n;
            const steps = ctx.panel.querySelectorAll('.iswizard__step');
            steps.forEach((el) => {
                const idx = Number(el.dataset.step);
                el.classList.remove('iswizard__step--active', 'iswizard__step--done');
                if (idx < n) el.classList.add('iswizard__step--done');
                else if (idx === n) el.classList.add('iswizard__step--active');
            });
        }

        async function _loadCampaignTagIds() {
            const ids = new Set();
            // Параллельная загрузка — теги нужны редко (раз при открытии Wizard).
            const [own, linked] = await Promise.all([
                ctx.api.getCampaignTags(ctx.campaignId).catch(() => []),
                ctx.api.getCampaignGlobalTags(ctx.campaignId).catch(() => []),
            ]);
            for (const t of (own || [])) ids.add(String(t.id));
            for (const t of (linked || [])) ids.add(String(t.id));
            return Array.from(ids);
        }

        async function start() {
            setState('loading_documents');
            // Сначала — теги кампании; если их нет, Wizard не сможет отобрать документы.
            let tagIds = [];
            try {
                tagIds = await _loadCampaignTagIds();
            } catch (_) {
                tagIds = [];
            }
            ctx.campaignTagIds = tagIds;

            if (!tagIds.length) {
                const info = { code: 'no_campaign_tags', text: ERROR_MESSAGES.no_campaign_tags };
                ctx.error = info;
                setState('select_documents', { documents: [], filteredDocuments: [] });
                return;
            }

            let docs = [];
            try {
                const fetched = await ctx.api.getSettingsDocuments({
                    domainId: ctx.opts.domainId || null,
                    status: 'indexed',
                    tagIds,
                });
                docs = Array.isArray(fetched) ? fetched : [];
            } catch (_) {
                // Не критично — Wizard всё равно покажет пустой список и попробует
                // восстановить proposal из Redis.
                docs = [];
            }
            const filtered = docs.filter((d) => _isMarkdown(d) && d.status === 'indexed');

            // Если в Redis уже есть proposal — сразу переходим на review.
            try {
                const existing = await ctx.api.getInitialStateProposal(ctx.campaignId);
                if (existing) {
                    setState('review', { documents: docs, filteredDocuments: filtered, proposal: existing });
                    return;
                }
            } catch (_) { /* пропускаем — покажем select_documents */ }

            setState('select_documents', { documents: docs, filteredDocuments: filtered });
        }

        async function doPreview() {
            setState('preview_starting');
            try {
                const opts = {
                    propose_fields: !!ctx.proposeFields,
                    max_suggested_fields: ctx.maxSuggestedFields,
                };
                const proposal = await ctx.api.previewInitialState(
                    ctx.campaignId,
                    Array.from(ctx.selectedIds),
                    opts,
                );
                // Если Wizard открыт в режиме propose_fields=false, но пришёл
                // V2-proposal с suggested_fields (например backend стал по
                // дефолту прокидывать) — отбрасываем suggested.
                if (!ctx.proposeFields && proposal && proposal.proposal) {
                    proposal.proposal.suggested_fields = [];
                }
                // Инициализируем suggestedFields state из proposal (UI работает
                // с локальной мутабельной копией).
                ctx.suggestedFields = _initSuggestedFromProposal(proposal);
                setState('review', { proposal, appliedVersion: null });
            } catch (err) {
                const info = _errMessage(err);
                ctx.error = info;
                setState('select_documents');
            }
        }

        function _buildProposalOverrides(proposal) {
            // Снимаем копию изменяемых полей из proposal.
            // Бэкенд мерджит overrides по field_key поверх proposal из Redis.
            const src = proposal && proposal.proposal;
            if (!src || !Array.isArray(src.fields)) return null;
            return {
                fields: src.fields.map((f) => ({
                    field_key: f.field_key,
                    mode: f.mode,
                    status: f.status,
                    single_value: f.single_value ? { ...f.single_value } : null,
                    list_value: f.list_value
                        ? { items: (f.list_value.items || []).map((it) => ({ ...it })) }
                        : null,
                })),
                questions: Array.isArray(src.questions) ? src.questions.slice() : [],
            };
        }

        // Преобразовать suggested_fields[] из proposal в массив UI-стейта.
        // accepted по умолчанию = true. Каждый элемент имеет originalKey для
        // отслеживания, менялся ли key на стороне клиента.
        function _initSuggestedFromProposal(proposal) {
            const sfs = (proposal && proposal.proposal && proposal.proposal.suggested_fields) || [];
            return sfs.map((sf) => {
                const status = (sf.initial_status && sf.initial_status.status) || 'empty';
                return {
                    key: sf.key,
                    originalKey: sf.key,  // для отслеживания изменений key
                    label: sf.label || sf.key,
                    description: sf.description || '',
                    mode: sf.mode,
                    initial_status: {
                        status,
                        clarification_question: sf.clarification_question
                            || (sf.initial_status && sf.initial_status.clarification_question)
                            || null,
                    },
                    single_value: sf.single_value
                        ? { text: sf.single_value.text || '', source_refs: [...(sf.single_value.source_refs || [])] }
                        : null,
                    list_value: sf.list_value
                        ? { items: (sf.list_value.items || []).map((it) => ({ ...it })) }
                        : null,
                    accepted: true,
                };
            });
        }

        // Собрать accepted/rejected ключи suggested_fields по текущему UI-стейту.
        function _buildSuggestedFieldKeys(suggestedFields) {
            const accepted = [];
            const rejected = [];
            for (const sf of suggestedFields) {
                if (sf.accepted) accepted.push(sf.key);
                else rejected.push(sf.key);
            }
            return { accepted, rejected };
        }

        async function doApply() {
            if (!ctx.proposal) return;
            setState('applying');
            const overrides = _buildProposalOverrides(ctx.proposal);
            const { accepted, rejected } = _buildSuggestedFieldKeys(ctx.suggestedFields);
            try {
                const version = await ctx.api.applyInitialState(
                    ctx.campaignId,
                    ctx.proposal.proposal_id,
                    ctx.proposal.config_version,
                    overrides,
                    accepted,
                    rejected,
                );
                setState('result', { appliedVersion: version });
                if (typeof ctx.opts.onApplied === 'function') {
                    try { ctx.opts.onApplied(version); } catch (_) { /* ignore */ }
                }
            } catch (err) {
                const info = _errMessage(err);
                ctx.error = info;
                if (info.code === 'initial_already_applied') {
                    if (typeof ctx.opts.onApplied === 'function') {
                        try { ctx.opts.onApplied(null); } catch (_) { /* ignore */ }
                    }
                    setState('select_documents', { proposal: null });
                } else if (info.code === 'source_snapshot_stale'
                    || info.code === 'proposal_expired') {
                    setState('select_documents', { proposal: null });
                } else if (info.code === 'suggested_field_key_conflict'
                    || info.code === 'suggested_field_creation_failed') {
                    // Остаёмся на review — пользователь должен отредактировать.
                    setState('review');
                } else {
                    setState('review');
                }
            }
        }

        function doBackToSelect() {
            if (ctx.proposal) {
                ctx.selectedIds = new Set(
                    ctx.proposal.source_snapshot.map((s) => s.document_id)
                );
            }
            setState('select_documents', { proposal: null, error: null, highlightDocIds: new Set() });
        }

        // ----- Rendering -----

        function render() {
            setStep(ctx.step);
            body.innerHTML = '';
            actions.innerHTML = '';

            if (ctx.state === 'loading_documents') return _renderLoading();
            if (ctx.state === 'select_documents') return _renderSelect();
            if (ctx.state === 'preview_starting') {
                _renderPreviewStarting();
                return;
            }
            if (ctx.state === 'review' || ctx.state === 'review_editing') return _renderReview();
            if (ctx.state === 'applying') return _renderApplying();
            if (ctx.state === 'result') return _renderResult();
            if (ctx.state === 'error') return _renderError();
        }

        function _renderLoading() {
            body.innerHTML = `
                <div class="iswizard__loading">
                    <span class="iswizard__spinner"></span>
                    <span>Загрузка документов…</span>
                </div>
            `;
        }

        function _renderPreviewStarting() {
            body.innerHTML = `
                <div class="iswizard__loading">
                    <span class="iswizard__spinner"></span>
                    <span>Генерация Initial State…</span>
                </div>
            `;
            _renderActions([
                _btn('Закрыть', 'close', 'secondary'),
            ]);
        }

        function _renderApplying() {
            body.innerHTML = `
                <div class="iswizard__loading">
                    <span class="iswizard__spinner"></span>
                    <span>Применение Initial State…</span>
                </div>
            `;
            _renderActions([]);
        }

        function _renderActions(buttons) {
            actions.innerHTML = '';
            buttons.forEach((b) => {
                const el = document.createElement('button');
                el.type = 'button';
                el.className = 'iswizard__btn' + (b.variant === 'primary' ? ' iswizard__btn--primary'
                    : b.variant === 'danger' ? ' iswizard__btn--danger' : '');
                if (b.action) el.dataset.action = b.action;
                el.textContent = b.label;
                if (b.disabled) el.disabled = true;
                el.addEventListener('click', () => b.onClick());
                actions.appendChild(el);
            });
        }

        function _btn(label, action, variant) {
            return {
                label, action, variant,
                disabled: false,
                onClick: () => _onAction(action),
            };
        }

        function _btnDisabled(label, action, variant) {
            return {
                label,
                action,
                variant: variant || 'secondary',
                disabled: true,
                onClick: () => _onAction(action),
            };
        }

        function _renderError() {
            body.innerHTML = _errorBannerHtml(ctx.error);
            _renderActions([
                _btn('Повторить', 'retry', 'secondary'),
                _btn('Закрыть', 'close', 'secondary'),
            ]);
            _attachErrorDismiss(body);
        }

        // Универсальная отрисовка баннера ошибки с привязкой dismiss-handler.
        // Используется в любом стейте, где показывается error.
        function _errorBannerHtml(info) {
            if (!info) return '';
            return `
                <div class="iswizard__error" data-error>
                    <span class="iswizard__error-text">${_escapeHtml(info.text || 'Ошибка')}</span>
                    <button class="iswizard__btn" type="button" data-action="dismiss-error" aria-label="Закрыть ошибку">×</button>
                </div>
            `;
        }

        function _attachErrorDismiss(scope) {
            if (!scope) return;
            const banner = scope.querySelector('[data-action="dismiss-error"]');
            if (banner) {
                banner.addEventListener('click', () => {
                    ctx.error = null;
                    render();
                });
            }
        }

        function _filteredDocs() {
            const q = ctx.search.trim().toLowerCase();
            if (!q) return ctx.filteredDocuments;
            return ctx.filteredDocuments.filter((d) => {
                const t = (_docTitle(d) || '').toLowerCase();
                const p = (d.source_path || '').toLowerCase();
                return t.includes(q) || p.includes(q);
            });
        }

        function _selectedTokens() {
            let total = 0;
            ctx.selectedIds.forEach((id) => {
                const d = ctx.documents.find((x) => String(x.id) === String(id));
                if (d && typeof d.estimated_tokens === 'number') total += d.estimated_tokens;
            });
            return total;
        }

        // Точечное обновление счётчиков выбранных документов и прогресс-бара —
        // без перерендера всего тела, чтобы сохранить scrollTop контейнера .iswizard__docs.
        function _updateBudgetView() {
            const totalSel = ctx.selectedIds.size;
            const tokens = _selectedTokens();
            const overBudget = tokens > TOTAL_TOKEN_BUDGET;
            const pct = Math.min(100, Math.round((tokens / TOTAL_TOKEN_BUDGET) * 100));

            const valueEl = body.querySelector('[data-budget-selected]');
            if (valueEl) {
                valueEl.innerHTML = `<strong>${totalSel}</strong> док. / ${_formatTokens(tokens)} ток.`;
            }
            const fractionEl = body.querySelector('[data-budget-fraction]');
            if (fractionEl) {
                fractionEl.textContent = `${_formatTokens(tokens)} / ${_formatTokens(TOTAL_TOKEN_BUDGET)}`;
            }
            const fillEl = body.querySelector('[data-budget-fill]');
            if (fillEl) {
                fillEl.style.width = `${pct}%`;
                fillEl.classList.toggle('iswizard__budget-fill--over', overBudget);
            }
            const nextBtn = actions.querySelector('[data-action="preview"]');
            if (nextBtn) {
                const canNext = totalSel > 0 && !overBudget && ctx.state !== 'preview_starting';
                nextBtn.disabled = !canNext;
            }
        }

        function _renderSelect() {
            const docs = _filteredDocs();
            const totalSel = ctx.selectedIds.size;
            const tokens = _selectedTokens();
            const overBudget = tokens > TOTAL_TOKEN_BUDGET;
            const pct = Math.min(100, Math.round((tokens / TOTAL_TOKEN_BUDGET) * 100));
            const noTags = ctx.campaignTagIds.length === 0;

            const errorHtml = ctx.error ? _errorBannerHtml(ctx.error) : '';

            const tagsHint = noTags
                ? ''
                : `<div class="iswizard__hint" style="margin-bottom:8px;color:var(--color-text-muted);font-size:11.5px;">
                       Показаны только документы, привязанные к тегам кампании (${ctx.campaignTagIds.length} тег${_plural(ctx.campaignTagIds.length)}).
                   </div>`;

            body.innerHTML = `
                ${errorHtml}
                <p class="iswizard__hint">Выберите Markdown-документы для формирования Initial State. Лимит на документ: ${_formatTokens(PER_DOC_TOKEN_LIMIT)} токенов; общий бюджет: ${_formatTokens(TOTAL_TOKEN_BUDGET)}.</p>
                ${tagsHint}
                <input class="iswizard__search" type="search" placeholder="Поиск по названию или пути…" data-search />
                <div class="iswizard__docs" data-docs></div>
                <div class="iswizard__budget">
                    <span class="iswizard__budget-label">Выбрано:</span>
                    <span class="iswizard__budget-value" data-budget-selected><strong>${totalSel}</strong> док. / ${_formatTokens(tokens)} ток.</span>
                    <div class="iswizard__budget-bar">
                        <div class="iswizard__budget-fill${overBudget ? ' iswizard__budget-fill--over' : ''}" data-budget-fill style="width:${pct}%"></div>
                    </div>
                    <span class="iswizard__budget-value" data-budget-fraction>${_formatTokens(tokens)} / ${_formatTokens(TOTAL_TOKEN_BUDGET)}</span>
                </div>
            `;
            _attachErrorDismiss(body);

            const docsEl = body.querySelector('[data-docs]');
            _renderDocsList(docsEl, docs);

            body.querySelector('[data-search]').addEventListener('input', (ev) => {
                ctx.search = ev.target.value || '';
                // Перерендерим только список, сохранив scrollTop.
                const el = body.querySelector('[data-docs]');
                if (!el) return;
                const savedScroll = el.scrollTop;
                _renderDocsList(el, _filteredDocs());
                el.scrollTop = savedScroll;
            });

            const canNext = totalSel > 0 && !overBudget && ctx.state !== 'preview_starting';
            _renderActions([
                _btn('Отмена', 'close', 'secondary'),
                canNext
                    ? _btn('Далее →', 'preview', 'primary')
                    : _btnDisabled('Далее →', 'preview', 'primary'),
            ]);
        }

        // Рендерит только содержимое контейнера [data-docs] — без пересоздания
        // самого контейнера, чтобы сохранить scrollTop.
        function _renderDocsList(container, docs) {
            if (!container) return;
            if (!docs.length) {
                container.innerHTML = '<div class="iswizard__field-empty-text" style="padding:14px;text-align:center;">Нет подходящих Markdown-документов.</div>';
                return;
            }
            container.innerHTML = docs.map((d) => {
                const oversized = _docIsOversized(d);
                const checked = ctx.selectedIds.has(String(d.id));
                const highlighted = ctx.highlightDocIds && ctx.highlightDocIds.has(String(d.id));
                const disabled = oversized;
                return `
                    <label class="iswizard__doc${disabled ? ' iswizard__doc--disabled' : ''}${highlighted ? ' iswizard__doc--highlighted' : ''}" data-doc-id="${_escapeHtml(String(d.id))}">
                        <input class="iswizard__doc-check" type="checkbox" data-doc-check ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''} />
                        <div class="iswizard__doc-body">
                            <div class="iswizard__doc-title">${_escapeHtml(_docTitle(d))}</div>
                            <div class="iswizard__doc-path">${_escapeHtml(d.source_path || '')}</div>
                            ${disabled ? '<div class="iswizard__doc-warning">Документ слишком большой для Initial State (&gt; ' + _formatTokens(PER_DOC_TOKEN_LIMIT) + ' ток.)</div>' : ''}
                        </div>
                        <div class="iswizard__doc-meta">${_formatTokens(d.estimated_tokens)} ток.</div>
                    </label>
                `;
            }).join('');

            container.querySelectorAll('[data-doc-check]').forEach((cb) => {
                cb.addEventListener('change', (ev) => {
                    const wrap = ev.target.closest('[data-doc-id]');
                    const id = wrap ? wrap.dataset.docId : null;
                    if (!id) return;
                    if (ev.target.checked) ctx.selectedIds.add(id);
                    else ctx.selectedIds.delete(id);
                    // Точечное обновление счётчиков/бара вместо полного перерендера —
                    // иначе scrollTop контейнера сбрасывается в 0.
                    _updateBudgetView();
                });
            });
        }

        function _fieldHtml(field, snapshotById) {
            const status = field.status && field.status.status ? field.status.status : 'empty';
            const statusCls = `iswizard__field-status--${status}`;
            const statusLabel = status === 'proposed' ? 'предложено'
                : status === 'empty' ? 'нет данных'
                : 'требуется уточнение';
            const isSingle = field.mode === 'single';
            let valueHtml = '';
            let sourcesHtml = '';

            if (status === 'proposed') {
                if (isSingle && field.single_value) {
                    valueHtml = `<div class="iswizard__field-value" data-single-value="${_escapeHtml(field.field_key)}">${_escapeHtml(field.single_value.text || '')}</div>`;
                    sourcesHtml = _sourcesHtml(field.single_value.source_refs || [], snapshotById);
                } else if (!isSingle && field.list_value) {
                    const items = field.list_value.items || [];
                    if (!items.length) {
                        valueHtml = '<div class="iswizard__field-empty-text">Список пуст.</div>';
                    } else {
                        const itemsHtml = items.map((it, i) => `
                            <div class="iswizard__list-item" data-list-idx="${i}">
                                <div class="iswizard__list-item-text" data-list-text>${_escapeHtml(it.text || '')}</div>
                                ${_sourcesHtmlInline(it.source_refs || [], snapshotById)}
                                <div class="iswizard__list-item-actions">
                                    <button class="iswizard__btn" type="button" data-action="edit-list-item" data-list-idx="${i}" title="Редактировать">✎</button>
                                    <button class="iswizard__btn" type="button" data-action="remove-list-item" data-list-idx="${i}" title="Удалить">🗑</button>
                                </div>
                            </div>
                        `).join('');
                        valueHtml = `<div class="iswizard__list-items" data-list-items>${itemsHtml}</div>`;
                    }
                }
            } else if (status === 'needs_clarification') {
                const q = field.status && field.status.clarification_question ? field.status.clarification_question : '';
                valueHtml = `<div class="iswizard__field-question">${_escapeHtml(q)}</div>`;
            } else {
                valueHtml = '<div class="iswizard__field-empty-text">Нет данных.</div>';
            }

            const editBtn = (status === 'proposed' && isSingle)
                ? `<button class="iswizard__btn" type="button" data-action="edit-field" data-field-key="${_escapeHtml(field.field_key)}">Изменить</button>`
                : '';
            const addListBtn = (status === 'proposed' && !isSingle)
                ? `<button class="iswizard__btn" type="button" data-action="add-list-item">+ Добавить элемент</button>`
                : '';

            return `
                <div class="iswizard__field" data-field-key="${_escapeHtml(field.field_key)}">
                    <div class="iswizard__field-header">
                        <span class="iswizard__field-label">${_escapeHtml(field.label || field.field_key)}</span>
                        <span class="iswizard__field-mode">${_escapeHtml(field.mode)}</span>
                        <span class="iswizard__field-status ${statusCls}">${_escapeHtml(statusLabel)}</span>
                    </div>
                    ${valueHtml}
                    ${sourcesHtml}
                    <div class="iswizard__field-actions">
                        ${editBtn}
                        ${addListBtn}
                    </div>
                </div>
            `;
        }

        function _sourcesHtml(refs, snapshotById) {
            if (!refs || !refs.length) return '';
            const lines = refs.map((ref) => _refLine(ref, snapshotById)).filter(Boolean);
            if (!lines.length) return '';
            return `<div class="iswizard__source">Источник: ${lines.join('; ')}</div>`;
        }

        function _sourcesHtmlInline(refs, snapshotById) {
            const lines = refs.map((ref) => _refLine(ref, snapshotById)).filter(Boolean);
            if (!lines.length) return '';
            return `<div class="iswizard__list-item-meta">${lines.join('; ')}</div>`;
        }

        function _refLine(ref, snapshotById) {
            const snap = snapshotById[ref];
            if (!snap) return _escapeHtml(ref);
            const label = snap.title || snap.source_path || snap.document_id;
            return `<span class="iswizard__source-link" title="${_escapeHtml(ref)}">${_escapeHtml(label)}</span>`;
        }

        // Рендер карточки одного suggested_field в review-секции.
        // idx — индекс в ctx.suggestedFields, по нему ищем элемент.
        function _suggestedFieldHtml(sf, idx) {
            const status = (sf.initial_status && sf.initial_status.status) || 'empty';
            const statusCls = `iswizard__field-status--${status}`;
            const statusLabel = status === 'proposed' ? 'предложено'
                : status === 'empty' ? 'нет данных'
                : 'требуется уточнение';
            const isSingle = sf.mode === 'single';

            let valueHtml = '';
            if (status === 'proposed') {
                if (isSingle && sf.single_value) {
                    const text = sf.single_value.text || '';
                    valueHtml = `<div class="iswizard__field-value" data-suggested-single-value="${idx}">${_escapeHtml(text)}</div>`;
                } else if (!isSingle && sf.list_value) {
                    const items = sf.list_value.items || [];
                    if (!items.length) {
                        valueHtml = '<div class="iswizard__field-empty-text">Список пуст.</div>';
                    } else {
                        const itemsHtml = items.map((it, i) => `
                            <div class="iswizard__list-item" data-suggested-list-idx="${i}">
                                <div class="iswizard__list-item-text">${_escapeHtml(it.text || '')}</div>
                                <div class="iswizard__list-item-actions">
                                    <button class="iswizard__btn" type="button" data-action="edit-suggested-list-item" data-suggested-list-idx="${i}" title="Редактировать">✎</button>
                                    <button class="iswizard__btn" type="button" data-action="remove-suggested-list-item" data-suggested-list-idx="${i}" title="Удалить">🗑</button>
                                </div>
                            </div>
                        `).join('');
                        valueHtml = `<div class="iswizard__list-items">${itemsHtml}</div>`;
                    }
                }
            } else if (status === 'needs_clarification') {
                const q = sf.initial_status && sf.initial_status.clarification_question
                    ? sf.initial_status.clarification_question : '';
                valueHtml = `<div class="iswizard__field-question">${_escapeHtml(q)}</div>`;
            } else {
                valueHtml = '<div class="iswizard__field-empty-text">Нет данных.</div>';
            }

            const editBtn = (status === 'proposed' && isSingle)
                ? `<button class="iswizard__btn" type="button" data-action="edit-suggested-single" data-suggested-idx="${idx}">Изменить</button>`
                : '';
            const addListBtn = (status === 'proposed' && !isSingle)
                ? `<button class="iswizard__btn" type="button" data-action="add-suggested-list-item" data-suggested-idx="${idx}">+ Добавить элемент</button>`
                : '';

            return `
                <div class="iswizard__field iswizard__suggested-field${sf.accepted ? '' : ' iswizard__field--rejected'}" data-suggested-idx="${idx}">
                    <div class="iswizard__field-header">
                        <input type="checkbox" class="iswizard__suggested-accept" data-suggested-accept-idx="${idx}" ${sf.accepted ? 'checked' : ''} title="Принять поле" />
                        <input class="iswizard__suggested-key" data-suggested-key-idx="${idx}" value="${_escapeHtml(sf.key)}" pattern="^[a-z][a-z0-9_]{0,63}$" title="stable snake_case key" />
                        <span class="iswizard__field-mode">${_escapeHtml(sf.mode)}</span>
                        <span class="iswizard__field-status ${statusCls}">${_escapeHtml(statusLabel)}</span>
                    </div>
                    <div class="iswizard__suggested-meta">
                        <label class="iswizard__suggested-label">
                            Название:
                            <input class="iswizard__suggested-label-input" data-suggested-label-idx="${idx}" value="${_escapeHtml(sf.label || '')}" maxlength="256" />
                        </label>
                        <label class="iswizard__suggested-label">
                            Описание:
                            <textarea class="iswizard__suggested-desc" data-suggested-desc-idx="${idx}" rows="2" placeholder="Подсказка для будущих LLM (опц.)">${_escapeHtml(sf.description || '')}</textarea>
                        </label>
                        <div class="iswizard__suggested-mode-toggle">
                            Тип поля:
                            <label><input type="radio" name="suggested-mode-${idx}" value="single" data-suggested-mode-idx="${idx}" ${isSingle ? 'checked' : ''} /> single</label>
                            <label><input type="radio" name="suggested-mode-${idx}" value="list" data-suggested-mode-idx="${idx}" ${!isSingle ? 'checked' : ''} /> list</label>
                        </div>
                    </div>
                    <div class="iswizard__suggested-value">${valueHtml}</div>
                    <div class="iswizard__field-actions">
                        ${editBtn}
                        ${addListBtn}
                    </div>
                </div>
            `;
        }

        // Привязка handlers для suggested_fields карточек.
        function _attachSuggestedHandlers(bodyEl) {
            const getSf = (idx) => ctx.suggestedFields[idx];

            // Accept toggle.
            bodyEl.querySelectorAll('[data-suggested-accept-idx]').forEach((cb) => {
                cb.addEventListener('change', (ev) => {
                    const idx = Number(ev.target.dataset.suggestedAcceptIdx);
                    const sf = getSf(idx);
                    if (!sf) return;
                    sf.accepted = ev.target.checked;
                    render();
                });
            });

            // Key.
            bodyEl.querySelectorAll('[data-suggested-key-idx]').forEach((inp) => {
                inp.addEventListener('input', (ev) => {
                    const idx = Number(ev.target.dataset.suggestedKeyIdx);
                    const sf = getSf(idx);
                    if (!sf) return;
                    sf.key = ev.target.value || sf.key;
                });
            });

            // Label.
            bodyEl.querySelectorAll('[data-suggested-label-idx]').forEach((inp) => {
                inp.addEventListener('input', (ev) => {
                    const idx = Number(ev.target.dataset.suggestedLabelIdx);
                    const sf = getSf(idx);
                    if (!sf) return;
                    sf.label = ev.target.value || sf.label;
                });
            });

            // Description.
            bodyEl.querySelectorAll('[data-suggested-desc-idx]').forEach((inp) => {
                inp.addEventListener('input', (ev) => {
                    const idx = Number(ev.target.dataset.suggestedDescIdx);
                    const sf = getSf(idx);
                    if (!sf) return;
                    sf.description = ev.target.value || '';
                });
            });

            // Mode radio.
            bodyEl.querySelectorAll('[data-suggested-mode-idx]').forEach((radio) => {
                radio.addEventListener('change', (ev) => {
                    const idx = Number(ev.target.dataset.suggestedModeIdx);
                    const sf = getSf(idx);
                    if (!sf) return;
                    const newMode = ev.target.value;
                    if (sf.mode === newMode) return;
                    sf.mode = newMode;
                    if (newMode === 'single' && !sf.single_value) {
                        sf.single_value = { text: '', source_refs: [] };
                        sf.list_value = null;
                    } else if (newMode === 'list' && !sf.list_value) {
                        sf.list_value = { items: [] };
                        sf.single_value = null;
                    }
                    render();
                });
            });

            // Edit single value.
            bodyEl.querySelectorAll('[data-action="edit-suggested-single"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.dataset.suggestedIdx);
                    const sf = getSf(idx);
                    if (!sf || !sf.single_value) return;
                    const wrap = btn.closest('.iswizard__suggested-field');
                    if (!wrap) return;
                    _enterSuggestedSingleEditMode(wrap, sf);
                });
            });

            // Add list item.
            bodyEl.querySelectorAll('[data-action="add-suggested-list-item"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.dataset.suggestedIdx);
                    const sf = getSf(idx);
                    if (!sf) return;
                    if (!sf.list_value) {
                        sf.list_value = { items: [] };
                    }
                    sf.list_value.items.push({ text: '', source_refs: [] });
                    render();
                });
            });

            // Edit list item.
            bodyEl.querySelectorAll('[data-action="edit-suggested-list-item"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.dataset.suggestedListIdx);
                    const itemEl = btn.closest('.iswizard__list-item');
                    const wrap = btn.closest('.iswizard__suggested-field');
                    const wrapIdx = wrap ? Number(wrap.dataset.suggestedIdx) : NaN;
                    const sf = Number.isFinite(wrapIdx) ? getSf(wrapIdx) : null;
                    if (!sf || !sf.list_value || !sf.list_value.items[idx]) return;
                    _enterSuggestedListItemEditMode(itemEl, sf, idx);
                });
            });

            // Remove list item.
            bodyEl.querySelectorAll('[data-action="remove-suggested-list-item"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const idx = Number(btn.dataset.suggestedListIdx);
                    const wrap = btn.closest('.iswizard__suggested-field');
                    const wrapIdx = wrap ? Number(wrap.dataset.suggestedIdx) : NaN;
                    const sf = Number.isFinite(wrapIdx) ? getSf(wrapIdx) : null;
                    if (!sf || !sf.list_value) return;
                    sf.list_value.items.splice(idx, 1);
                    render();
                });
            });
        }

        // Inline-edit single_value в suggested_field.
        function _enterSuggestedSingleEditMode(wrap, sf) {
            const valueEl = wrap.querySelector(`[data-suggested-single-value]`);
            if (!valueEl) return;
            const current = (sf.single_value && sf.single_value.text) || '';
            const ta = document.createElement('textarea');
            ta.className = 'iswizard__field-edit-textarea';
            ta.value = current;
            valueEl.replaceWith(ta);
            const actions = wrap.querySelector('.iswizard__field-actions');
            if (actions) {
                actions.innerHTML = `
                    <button class="iswizard__btn" type="button" data-action="cancel-suggested-edit">Отменить</button>
                    <button class="iswizard__btn iswizard__btn--primary" type="button" data-action="save-suggested-edit">Сохранить</button>
                `;
                actions.querySelector('[data-action="cancel-suggested-edit"]').addEventListener('click', () => render());
                actions.querySelector('[data-action="save-suggested-edit"]').addEventListener('click', () => {
                    const newText = (ta.value || '').trim();
                    if (!newText) {
                        render();
                        return;
                    }
                    sf.single_value = { ...(sf.single_value || {}), text: newText };
                    render();
                });
            }
        }

        // Inline-edit list item в suggested_field.
        function _enterSuggestedListItemEditMode(itemEl, sf, idx) {
            if (!itemEl) return;
            const items = sf.list_value.items;
            const item = items[idx];
            if (!item) return;
            const current = item.text || '';
            const ta = document.createElement('textarea');
            ta.className = 'iswizard__field-edit-textarea';
            ta.value = current;
            const actions = itemEl.querySelector('.iswizard__list-item-actions');
            const textEl = itemEl.querySelector('.iswizard__list-item-text');
            if (textEl) textEl.replaceWith(ta);
            if (actions) {
                actions.innerHTML = `
                    <button class="iswizard__btn" type="button" data-action="cancel-suggested-list-edit">Отменить</button>
                    <button class="iswizard__btn iswizard__btn--primary" type="button" data-action="save-suggested-list-edit">Сохранить</button>
                `;
                actions.querySelector('[data-action="cancel-suggested-list-edit"]').addEventListener('click', () => render());
                actions.querySelector('[data-action="save-suggested-list-edit"]').addEventListener('click', () => {
                    const newText = (ta.value || '').trim();
                    if (!newText) {
                        render();
                        return;
                    }
                    items[idx] = { ...item, text: newText };
                    render();
                });
            }
        }

        function _snapshotById() {
            const m = {};
            (ctx.proposal && ctx.proposal.source_snapshot || []).forEach((s) => {
                m[`file:${s.document_id}:sha:${s.content_sha}`] = s;
            });
            return m;
        }

        function _renderReview() {
            const errorHtml = ctx.error ? _errorBannerHtml(ctx.error) : '';
            const proposal = ctx.proposal || { proposal: { fields: [], suggested_fields: [], questions: [], warnings: [] } };
            const p = proposal.proposal || { fields: [], suggested_fields: [], questions: [] };
            const fields = Array.isArray(p.fields) ? p.fields : [];
            const questions = Array.isArray(p.questions) ? p.questions : [];
            const warnings = Array.isArray(proposal.warnings) ? proposal.warnings : [];
            const snapshotById = _snapshotById();

            // Suggested fields: ctx.suggestedFields — локальный UI-стейт, обновляемый inline-edit'ом.
            const suggestedFields = Array.isArray(ctx.suggestedFields) ? ctx.suggestedFields : [];
            const acceptedSuggested = suggestedFields.filter((s) => s.accepted).length;

            const introHint = suggestedFields.length
                ? `<p class="iswizard__hint">Проверьте и отредактируйте предложения ИИ: ключ/название/описание/тип каждого нового поля и значения для всех полей. Непринятые поля (✗) не будут созданы.</p>`
                : `<p class="iswizard__hint">Проверьте предложенные значения. Можно отредактировать текст single-полей, добавлять/удалять/редактировать элементы list-полей. Источники зафиксированы snapshot'ом.</p>`;

            body.innerHTML = `
                ${errorHtml}
                ${introHint}
                ${suggestedFields.length ? `
                    <section class="iswizard__suggested-section">
                        <h4 class="iswizard__suggested-title">
                            Предложенные новые поля (${acceptedSuggested}/${suggestedFields.length})
                        </h4>
                        <div data-suggested>${suggestedFields.map((sf, i) => _suggestedFieldHtml(sf, i)).join('')}</div>
                    </section>
                ` : ''}
                <div data-fields>${fields.map((f) => _fieldHtml(f, snapshotById)).join('') || '<div class="iswizard__field-empty-text">Модель не вернула полей.</div>'}</div>
                ${questions.length ? `
                    <div class="iswizard__questions">
                        <div class="iswizard__questions-title">Вопросы от модели</div>
                        <ul style="margin:0;padding-left:18px;">${questions.map((q) => `<li>${_escapeHtml(q)}</li>`).join('')}</ul>
                    </div>
                ` : ''}
                ${warnings.length ? `
                    <div class="iswizard__warnings">
                        <div class="iswizard__warnings-title">Предупреждения</div>
                        <ul style="margin:0;padding-left:18px;">${warnings.map((w) => `<li>${_escapeHtml(String(w))}</li>`).join('')}</ul>
                    </div>
                ` : ''}
            `;
            _attachErrorDismiss(body);

            // Хуки suggested_fields
            _attachSuggestedHandlers(body);

            // Хук «Изменить» для single-полей (existing fields).
            body.querySelectorAll('[data-action="edit-field"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const key = btn.dataset.fieldKey;
                    const field = fields.find((f) => f.field_key === key);
                    if (!field || !field.single_value) return;
                    const wrap = btn.closest('.iswizard__field');
                    if (!wrap) return;
                    _enterSingleEditMode(wrap, field);
                });
            });

            // Хуки для list items existing fields: edit / remove.
            body.querySelectorAll('[data-action="edit-list-item"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const fieldKey = btn.closest('.iswizard__field')?.dataset.fieldKey;
                    const idx = Number(btn.dataset.listIdx);
                    if (!Number.isFinite(idx) || !fieldKey) return;
                    const field = fields.find((f) => f.field_key === fieldKey);
                    if (!field || !field.list_value || !field.list_value.items[idx]) return;
                    _enterListItemEditMode(btn.closest('.iswizard__list-item'), field, idx);
                });
            });

            body.querySelectorAll('[data-action="remove-list-item"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const fieldKey = btn.closest('.iswizard__field')?.dataset.fieldKey;
                    const idx = Number(btn.dataset.listIdx);
                    if (!Number.isFinite(idx) || !fieldKey) return;
                    const field = fields.find((f) => f.field_key === fieldKey);
                    if (!field || !field.list_value) return;
                    field.list_value.items.splice(idx, 1);
                    render();
                });
            });

            // Хук «+ Добавить элемент» для existing fields.
            body.querySelectorAll('[data-action="add-list-item"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const fieldKey = btn.closest('.iswizard__field')?.dataset.fieldKey;
                    if (!fieldKey) return;
                    const field = fields.find((f) => f.field_key === fieldKey);
                    if (!field) return;
                    if (!field.list_value) {
                        field.list_value = { items: [] };
                    }
                    field.list_value.items.push({ text: '', source_refs: [] });
                    render();
                });
            });

            // Кнопка «Применить» активна, если есть proposal (положительный UX —
// пользователь может применить пустой state, или state с пустыми полями).
const canApply = !!(ctx.proposal);
_renderActions([
    _btn('← Назад', 'back', 'secondary'),
    _btn('Отмена', 'close', 'secondary'),
    canApply
        ? _btn('Применить', 'apply', 'primary')
        : _btnDisabled('Применить', 'apply', 'primary'),
]);
}

        function _enterSingleEditMode(wrap, field) {
            const valueEl = wrap.querySelector('[data-single-value]');
            if (!valueEl) return;
            const current = field.single_value.text || '';
            const ta = document.createElement('textarea');
            ta.className = 'iswizard__field-edit-textarea';
            ta.value = current;
            valueEl.replaceWith(ta);
            const actions = wrap.querySelector('.iswizard__field-actions');
            if (actions) {
                actions.innerHTML = `
                    <button class="iswizard__btn" type="button" data-action="cancel-edit">Отменить</button>
                    <button class="iswizard__btn iswizard__btn--primary" type="button" data-action="save-edit">Сохранить</button>
                `;
                actions.querySelector('[data-action="cancel-edit"]').addEventListener('click', () => render());
                actions.querySelector('[data-action="save-edit"]').addEventListener('click', () => {
                    const newText = (ta.value || '').trim();
                    if (!newText) {
                        // Не позволяем сохранить пустое значение — откат к предыдущему.
                        render();
                        return;
                    }
                    field.single_value = { ...field.single_value, text: newText };
                    render();
                });
            }
        }

        function _enterListItemEditMode(itemEl, field, idx) {
            if (!itemEl) return;
            const items = field.list_value.items;
            const item = items[idx];
            if (!item) return;
            const current = item.text || '';
            const ta = document.createElement('textarea');
            ta.className = 'iswizard__field-edit-textarea';
            ta.value = current;

            const actions = itemEl.querySelector('.iswizard__list-item-actions');
            const textEl = itemEl.querySelector('[data-list-text]');
            const metaEl = itemEl.querySelector('.iswizard__list-item-meta');

            if (textEl) textEl.replaceWith(ta);

            if (actions) {
                actions.innerHTML = `
                    <button class="iswizard__btn" type="button" data-action="cancel-list-edit">Отменить</button>
                    <button class="iswizard__btn iswizard__btn--primary" type="button" data-action="save-list-edit">Сохранить</button>
                `;
                actions.querySelector('[data-action="cancel-list-edit"]').addEventListener('click', () => render());
                actions.querySelector('[data-action="save-list-edit"]').addEventListener('click', () => {
                    const newText = (ta.value || '').trim();
                    if (!newText) {
                        render();
                        return;
                    }
                    items[idx] = { ...item, text: newText };
                    render();
                });
            }
            // meta-блок (источники) временно скрываем во время редактирования,
            // чтобы не мешал textarea. Восстановится при cancel/save (render()).
            if (metaEl) metaEl.style.display = 'none';
        }

        function _renderResult() {
            const v = ctx.appliedVersion || {};
            const summary = v.summary || {};
            const values = Array.isArray(v.values) ? v.values : [];
            const listItems = Array.isArray(v.list_items) ? v.list_items : [];
            const singleHtml = values.map((val) => `
                <div style="margin-bottom:6px;">
                    <div style="font-size:11.5px;color:#6b7d8f;">${_escapeHtml(val.field_key)}</div>
                    <div>${_escapeHtml(val.text || '')}</div>
                </div>
            `).join('');
            const listHtml = listItems.length
                ? listItems.map((it) => `
                    <div style="margin-bottom:4px;">
                        <span style="font-size:11.5px;color:#6b7d8f;">${_escapeHtml(it.field_key)}:</span>
                        ${_escapeHtml(it.text || '')}
                    </div>
                `).join('')
                : '';
            body.innerHTML = `
                <div class="iswizard__result">
                    <div class="iswizard__result-badge">✓ Initial State применён</div>
                    <div style="color:#6b7d8f;font-size:12.5px;">state_version = ${_escapeHtml(String(summary.state_version ?? '—'))} · source_kind = ${_escapeHtml(String(summary.source_kind ?? 'initial'))}</div>
                    <div class="iswizard__result-summary">
                        ${singleHtml || '<div class="iswizard__field-empty-text">Single-полей нет.</div>'}
                        ${listHtml}
                    </div>
                </div>
            `;
            _renderActions([
                _btn('Готово', 'close', 'primary'),
            ]);
        }

        // ----- Actions -----

        function _onAction(action) {
            clearError();
            if (action === 'close') return close();
            if (action === 'back') return doBackToSelect();
            if (action === 'preview') return doPreview();
            if (action === 'apply') return doApply();
            if (action === 'retry') {
                if (ctx.step === 1) return start();
                return render();
            }
        }

        function _plural(n) {
            const mod10 = n % 10;
            const mod100 = n % 100;
            if (mod10 === 1 && mod100 !== 11) return '';
            if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'а';
            return 'ов';
        }

        return { start, render };
    }

    function _escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    window.InitialStateWizard = {
        open,
        close,
        PER_DOC_TOKEN_LIMIT,
        TOTAL_TOKEN_BUDGET,
        _internals: { _escapeHtml, _isMarkdown, _docIsOversized, _errMessage, ERROR_MESSAGES },
    };
})();
