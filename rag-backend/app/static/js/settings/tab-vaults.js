const VaultsTabMixin = {
    async renderVaultsTab() {
        let vaults = await this.api.getSettingsVaults();
        if (!Array.isArray(vaults)) vaults = [];
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-vault">+ Новый vault</button></div>`;
        if (vaults.length === 0) return toolbar + `<div class="empty-state">Vault'ов нет</div>`;
        return toolbar + `<div class="settings-grid">${vaults.map(vault => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(vault.display_name || vault.vault_id)}</h3>
                    <p>/data/vaults/${this.escapeHtml(vault.vault_id)}</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(vault.vault_id)}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-vault" data-id="${this.escapeHtml(vault.vault_id)}">✏️ Изменить</button>
                        <button class="card-menu-item" data-action="toggle-vault" data-id="${this.escapeHtml(vault.vault_id)}">${vault.enabled ? '⏸️ Выключить' : '▶️ Включить'}</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-vault" data-id="${this.escapeHtml(vault.vault_id)}">🗑️ Удалить</button>
                    </div>
                </div>
                <div>
                    <span class="badge ${vault.enabled ? 'ok' : 'muted'}">${this.escapeHtml(vault.binding_status)}</span>
                </div>
            </article>`).join('')}</div>`;
    },

    async showVaultModal(vaultId = null) {
        try {
            let vault = null;
            if (vaultId) {
                const vaultsList = await this.api.getSettingsVaults();
                vault = (Array.isArray(vaultsList) ? vaultsList : []).find(v => v.vault_id === vaultId);
            }
            const resp = await this.api.getDomains();
            const allDomains = Array.isArray(resp) ? resp : (resp.domains || []);
            const domains = allDomains.filter(d => d.enabled !== false);
            const embModels = await this.api.getEmbeddingModels();
            const embModelsArr = Array.isArray(embModels) ? embModels : [];
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <h3>${vault ? 'Редактировать vault' : 'Новый vault'}</h3>
                    <div class="form-group">
                        <label>ID vault</label>
                        <input type="text" id="vault-id-input" value="${this.escapeHtml(vault?.vault_id || '')}" ${vault ? 'disabled' : ''}>
                    </div>
                    <div class="form-group">
                        <label>Название</label>
                        <input type="text" id="vault-name-input" value="${this.escapeHtml(vault?.display_name || '')}">
                    </div>
                    <div class="form-group">
                        <label>Домен</label>
                        <select id="vault-domain-select">
                            ${domains.map(d => `<option value="${this.escapeHtml(d.domain_id)}" ${vault?.domain_id === d.domain_id ? 'selected' : ''}>${this.escapeHtml(d.display_name || d.domain_id)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Embedding-модель</label>
                        <select id="vault-emb-model">
                            <option value="">— не выбрана —</option>
                            ${embModelsArr.map(m => `<option value="${this.escapeHtml(m.model_id)}" ${vault?.embedding_model_id === m.model_id ? 'selected' : ''}>${this.escapeHtml(m.display_name || m.model_id)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="modal-actions">
                        <button id="vault-save-btn" class="btn btn-primary">Сохранить</button>
                        <button id="vault-cancel-btn" class="btn btn-secondary">Отмена</button>
                    </div>
                </div>`;
            document.body.appendChild(modal);
            modal.querySelector('#vault-cancel-btn')?.addEventListener('click', () => modal.remove());
            modal.querySelector('#vault-save-btn')?.addEventListener('click', async () => {
                const data = {
                    display_name: modal.querySelector('#vault-name-input').value,
                    domain_id: modal.querySelector('#vault-domain-select').value,
                    embedding_model_id: modal.querySelector('#vault-emb-model').value || null,
                };
                if (vaultId) await this.api.updateVault(vaultId, data);
                else { data.vault_id = modal.querySelector('#vault-id-input').value; await this.api.createVault(data); }
                modal.remove();
                await this.loadTab(this.currentTab);
            });
        } catch (err) {
            console.error('Error in showVaultModal:', err);
            alert('Ошибка при открытии модального окна: ' + err.message);
        }
    },
};

Object.assign(SettingsManager.prototype, VaultsTabMixin);
