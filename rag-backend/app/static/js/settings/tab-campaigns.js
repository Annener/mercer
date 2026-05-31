const CampaignsTabMixin = {
    async renderCampaignsTab() {
        const vaultId = this._activeVaultId || null;
        let campaigns = [];
        try {
            const resp = await this.api.getCampaigns(vaultId);
            campaigns = Array.isArray(resp) ? resp : (resp.campaigns || []);
        } catch (e) { /* ignore */ }

        const toolbar = `<div class="settings-toolbar">
            <button class="btn btn-primary" data-action="new-campaign">+ Новая кампания</button>
        </div>`;
        if (!campaigns.length) return toolbar + '<div class="empty-state">Кампаний нет. Создайте первую.</div>';

        return toolbar + `<div class="settings-grid">${campaigns.map(c => `
            <article class="settings-card" data-id="${this.escapeHtml(String(c.id))}">
                <div>
                    <h3>${this.escapeHtml(c.name)}</h3>
                    <p style="color:var(--color-text-muted);font-size:var(--text-sm);">${this.escapeHtml(c.description || '')}</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(String(c.id))}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-campaign" data-id="${this.escapeHtml(String(c.id))}">✏️ Редактировать</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-campaign" data-id="${this.escapeHtml(String(c.id))}">🗑️ Удалить</button>
                    </div>
                </div>
            </article>`).join('')}</div>`;
    },

    async showCampaignModal(campaignId = null) {
        const isEdit = !!campaignId;
        let campaign = { name: '', description: '', system_prompt: '' };
        let campaignTags = [];
        let globalTags = [];
        const vaultId = this._activeVaultId || null;

        if (isEdit) {
            try {
                campaign = await this.api.getCampaign(campaignId);
                campaignTags = campaign.tags || [];
            } catch (e) { alert('Ошибка загрузки кампании: ' + e.message); return; }
        }
        if (vaultId) {
            try {
                const tagsResp = await this.api.getTags(vaultId);
                const all = Array.isArray(tagsResp) ? tagsResp : (tagsResp.tags || []);
                globalTags = all.filter(t => t.is_global);
            } catch (e) { /* ignore */ }
        }

        const overlay = document.createElement('div');
        overlay.className = 'modal';
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:1000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.55);';
        overlay.innerHTML = `<div class="modal-content" style="max-width:560px;width:100%;max-height:90vh;overflow-y:auto;">
            <div class="modal-header">
                <h3>${isEdit ? 'Редактировать' : 'Создать'} кампанию</h3>
                <button class="btn-close" id="camp-modal-close">✕</button>
            </div>
            <div class="form-group" style="padding:0 1.5rem;margin-top:1rem;">
                <label>Название</label>
                <input type="text" id="camp-name" class="input-field" value="${this.escapeHtml(campaign.name)}">
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Описание</label>
                <textarea id="camp-desc" class="input-field" rows="2">${this.escapeHtml(campaign.description || '')}</textarea>
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>System Prompt</label>
                <textarea id="camp-prompt" class="input-field" rows="5" placeholder="Инструкция для AI в этой кампании">${this.escapeHtml(campaign.system_prompt || '')}</textarea>
            </div>
            ${isEdit ? `
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Теги кампании</label>
                <div id="camp-tags-list" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;"></div>
                <details>
                    <summary style="cursor:pointer;font-size:var(--text-sm);color:var(--color-primary);margin-top:4px;">+ Создать тег</summary>
                    <div style="display:flex;gap:8px;margin-top:8px;align-items:center;">
                        <input type="text" id="new-tag-name" class="input-field" placeholder="Название" style="flex:1;">
                        <input type="color" id="new-tag-color" value="#4f98a3" style="width:36px;height:32px;border:none;cursor:pointer;border-radius:var(--radius-sm);">
                        <button class="btn btn-secondary" style="padding:4px 12px;" id="create-ctag-btn">Создать</button>
                    </div>
                </details>
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Глобальные теги <span style="color:var(--color-text-faint);font-size:var(--text-xs);">(только просмотр)</span></label>
                <div style="display:flex;flex-wrap:wrap;gap:4px;">
                    ${globalTags.map(t => `<span class="badge" style="background:var(--color-surface-offset);color:var(--color-text-muted);">${this.escapeHtml(t.name)}</span>`).join('') || '<span style="color:var(--color-text-faint)">нет</span>'}
                </div>
            </div>` : ''}
            <div class="modal-actions" style="display:flex;justify-content:space-between;gap:8px;margin-top:1rem;padding:1rem 1.5rem;border-top:1px solid var(--color-border);">
                <button class="btn btn-primary" id="camp-save-btn">${isEdit ? 'Сохранить' : 'Создать'}</button>
                ${isEdit ? `<button class="btn" style="color:var(--color-error);" id="camp-delete-btn">Удалить кампанию</button>` : ''}
            </div>
        </div>`;
        document.body.appendChild(overlay);

        let localCampTags = [...campaignTags];

        const refreshTagsList = () => {
            const list = overlay.querySelector('#camp-tags-list');
            if (!list) return;
            list.innerHTML = localCampTags.map(t =>
                `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};cursor:pointer;" data-remove-ctag="${this.escapeHtml(String(t.id))}">${this.escapeHtml(t.name)} ×</span>`
            ).join('') || '<span style="color:var(--color-text-faint)">нет тегов</span>';
            list.querySelectorAll('[data-remove-ctag]').forEach(el => {
                el.onclick = async () => {
                    const tid = el.dataset.removeCtag;
                    if (!confirm('Удалить тег?')) return;
                    try { await this.api.deleteTag(tid); localCampTags = localCampTags.filter(t => String(t.id) !== tid); refreshTagsList(); }
                    catch (e) { alert(e.message); }
                };
            });
        };
        refreshTagsList();

        overlay.querySelector('#camp-modal-close').onclick = () => overlay.remove();

        if (isEdit) {
            overlay.querySelector('#create-ctag-btn')?.addEventListener('click', async () => {
                const name = overlay.querySelector('#new-tag-name').value.trim();
                const color = overlay.querySelector('#new-tag-color').value;
                if (!name) return;
                try {
                    const tag = await this.api.createCampaignTag(campaignId, { name, color });
                    localCampTags.push(tag);
                    refreshTagsList();
                    overlay.querySelector('#new-tag-name').value = '';
                } catch (e) { alert(e.message); }
            });

            overlay.querySelector('#camp-delete-btn')?.addEventListener('click', async () => {
                if (!confirm('Удалить кампанию?')) return;
                try { await this.api.deleteCampaign(campaignId); overlay.remove(); this.loadTab('campaigns'); }
                catch (e) { alert(e.message); }
            });
        }

        overlay.querySelector('#camp-save-btn').addEventListener('click', async () => {
            const data = {
                name: overlay.querySelector('#camp-name').value.trim(),
                description: overlay.querySelector('#camp-desc').value.trim(),
                system_prompt: overlay.querySelector('#camp-prompt').value.trim(),
            };
            if (!data.name) { alert('Введите название'); return; }
            try {
                if (isEdit) { await this.api.updateCampaign(campaignId, data); }
                else { if (this._activeVaultId) data.vault_id = this._activeVaultId; await this.api.createCampaign(data); }
                overlay.remove();
                this.loadTab('campaigns');
            } catch (e) { alert('Ошибка: ' + e.message); }
        });
    },

    async handleCampaignsAction(action, id) {
        if (action === 'new-campaign') { await this.showCampaignModal(); return; }
        if (action === 'edit-campaign') { await this.showCampaignModal(id); return; }
        if (action === 'delete-campaign') {
            if (!confirm('Удалить кампанию?')) return;
            try { await this.api.deleteCampaign(id); this.loadTab('campaigns'); }
            catch (e) { alert(e.message); }
        }
    },
};

Object.assign(SettingsManager.prototype, CampaignsTabMixin);
