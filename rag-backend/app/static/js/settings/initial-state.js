// Initial State UI — Stage 3b (lightweight)
// Сегмент «Initial State» внутри модалки редактирования кампании.
// Состояние:
//   - если Initial State применён → badge «Initial State применён».
//   - если нет полей и нет тегов → скрыт (нужны теги для Wizard).
//   - если 0 тегов кампании → информационное сообщение (Wizard заблокирован).
//   - если есть поля, но не применён → кнопка «Сформировать начальный контекст».
//   - если 0 enabled-полей, но теги есть (Stage 3.v2) → кнопка
//     «Сформировать контекст с помощью ИИ». По клику Wizard автоматически
//     прокидывает propose_fields=true на preview.

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function _loadCampaignTagCount(campaignId, api) {
    let own = [];
    let linked = [];
    try { own = await api.getCampaignTags(campaignId); } catch (_) { own = []; }
    try { linked = await api.getCampaignGlobalTags(campaignId); } catch (_) { linked = []; }
    const ids = new Set();
    for (const t of (own || [])) ids.add(String(t.id));
    for (const t of (linked || [])) ids.add(String(t.id));
    return ids.size;
}

function build() {
    const root = document.createElement('div');
    root.className = 'form-group initial-state-section';
    // Контент наполняется через refresh().
    root.innerHTML = `
        <label>Initial State</label>
        <div class="field-desc">Initial State — компактная сводка кампании, которую LLM видит в каждом сообщении.</div>
        <div class="initial-state-section-body"></div>
    `;

    const state = {
        campaignId: null,
        api: window.chatAPI,
        fieldsCount: 0,
        hasActiveState: false,
        tagCount: 0,
        onChanged: null,
        activeVersion: null,
        onApplyClick: null,
        onCancelClick: null,
    };

    const body = root.querySelector('.initial-state-section-body');

    function render() {
        body.innerHTML = '';
        root.style.display = '';

        if (state.hasActiveState) {
            // Badge + краткая информация.
            const versionInfo = state.activeVersion?.summary;
            const item = document.createElement('div');
            item.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 12px;border:1px solid var(--color-border);border-radius:6px;background:#f5f7fa;';
            item.innerHTML = `
                <span class="badge" style="background:#27ae60;color:#fff;">Initial State применён</span>
                ${versionInfo?.created_at ? `<span style="color:#6b7d8f;font-size:12px;">создан ${escapeHtml(String(versionInfo.created_at).slice(0, 19))}</span>` : ''}
            `;
            body.appendChild(item);
            return;
        }

        if (state.fieldsCount === 0 && state.tagCount === 0) {
            // Скрываем секцию — Wizard заблокирован по обоим условиям.
            root.style.display = 'none';
            return;
        }

        if (state.tagCount === 0) {
            // У кампании нет ни собственных, ни подключённых глобальных тегов —
            // Wizard открыть нельзя (документы для Initial State не получится подобрать).
            const warn = document.createElement('div');
            warn.style.cssText = 'padding:10px 12px;border:1px solid #f5b7b1;border-radius:6px;background:#fdecea;color:#922b21;font-size:12.5px;';
            warn.innerHTML = `
                <div style="font-weight:600;margin-bottom:4px;">Initial State недоступен</div>
                <div>У кампании нет тегов (ни собственных, ни подключённых глобальных). Добавьте теги выше — это нужно, чтобы отобрать документы для формирования Initial State.</div>
            `;
            body.appendChild(warn);
            return;
        }

        // Stage 3.v2: при 0 enabled-полей показываем кнопку с подсказкой
        // "ИИ предложит поля и заполнит их значениями".
        const isProposeMode = state.fieldsCount === 0;
        const buttonText = isProposeMode
            ? 'Сформировать контекст с помощью ИИ'
            : 'Сформировать начальный контекст';
        const buttonHint = isProposeMode
            ? `ИИ проанализирует выбранные файлы, сам предложит поля и заполнит их значениями. Документы фильтруются по ${state.tagCount} тегу(ам) кампании.`
            : `Откроется мастер выбора Markdown-документов и подтверждения значений полей. Документы фильтруются по ${state.tagCount} тегу(ам) кампании.`;

        // Кнопка Initial State.
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-primary';
        button.textContent = buttonText;
        button.addEventListener('click', () => {
            if (typeof state.onApplyClick === 'function') {
                state.onApplyClick(state.campaignId, { proposeFields: isProposeMode });
            } else if (window.InitialStateWizard) {
                window.InitialStateWizard.open(state.campaignId, {
                    proposeFields: isProposeMode,
                    onApplied: () => state.refresh(state.campaignId),
                });
            }
        });
        body.appendChild(button);

        const hint = document.createElement('div');
        hint.className = 'field-desc';
        hint.style.marginTop = '6px';
        hint.textContent = buttonHint;
        body.appendChild(hint);
    }

    return {
        element: root,
        async load(campaignId, opts = {}) {
            state.campaignId = campaignId;
            state.onChanged = opts.onChanged || null;
            state.onApplyClick = opts.onApplyClick || null;
            state.onCancelClick = opts.onCancelClick || null;
            try {
                const fields = await state.api.getStateFields(campaignId);
                state.fieldsCount = Array.isArray(fields) ? fields.length : 0;
            } catch (_) {
                state.fieldsCount = 0;
            }
            try {
                state.activeVersion = await state.api.getActiveCampaignState(campaignId);
                state.hasActiveState = !!(state.activeVersion && state.activeVersion.summary);
            } catch (_) {
                state.activeVersion = null;
                state.hasActiveState = false;
            }
            if (state.api && typeof state.api.getCampaignTags === 'function') {
                state.tagCount = await _loadCampaignTagCount(campaignId, state.api);
            } else {
                state.tagCount = 0;
            }
            render();
        },
        refresh(campaignId) {
            return this.load(campaignId, {
                onChanged: state.onChanged,
                onApplyClick: state.onApplyClick,
            });
        },
    };
}

window.InitialStateSection = { build };
export const InitialStateSection = { build };
