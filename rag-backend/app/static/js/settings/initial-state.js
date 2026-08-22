// Initial State UI — Stage 3b (lightweight)
// Сегмент «Initial State» внутри модалки редактирования кампании.
// Состояние:
//   - если Initial State применён → badge «Initial State применён».
//   - если нет полей → скрыт.
//   - если есть поля, но не применён → кнопка «Сформировать начальный контекст»,
//     по клику открывается InitialStateWizard (Stage 4).

(function () {
    'use strict';

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
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
            onChanged: null,
            activeVersion: null,
            onApplyClick: null,
            onCancelClick: null,
        };

        const body = root.querySelector('.initial-state-section-body');

        function render() {
            body.innerHTML = '';

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

            if (state.fieldsCount === 0) {
                // Скрываем секцию — нет смысла без полей.
                root.style.display = 'none';
                return;
            }

            // Кнопка Initial State.
            root.style.display = '';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-primary';
            button.textContent = 'Сформировать начальный контекст';
            button.addEventListener('click', () => {
                if (typeof state.onApplyClick === 'function') {
                    state.onApplyClick(state.campaignId);
                } else if (window.InitialStateWizard) {
                    window.InitialStateWizard.open(state.campaignId, {
                        onApplied: () => state.refresh(state.campaignId),
                    });
                }
            });
            body.appendChild(button);

            const hint = document.createElement('div');
            hint.className = 'field-desc';
            hint.style.marginTop = '6px';
            hint.textContent = 'Откроется мастер выбора Markdown-документов и подтверждения значений полей.';
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
})();
