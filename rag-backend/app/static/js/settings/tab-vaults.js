const VaultsTabMixin = {
    async renderVaultsTab() {
        const domainId = this._activeDomainId || null;
        let vaults = await this.api.getSettingsVaults(domainId);
        if (!Array.isArray(vaults)) vaults = [];

        let domains = [];
        try {
            const dr = await this.api.getSettingsDomains();
            domains = Array.isArray(dr) ? dr : (dr.domains || []);
        } catch (_) {}

        const railHtml = window.DomainRail
            ? window.DomainRail.render(domains, domainId, this.escapeHtml.bind(this))
            : '';

        const toolbar = `<div class="settings-toolbar">
            <button class="btn btn-primary" data-action="new-vault">Новое хранилище</button>
        </div>`;

        // --- Карточки vault'ов ---
        const cardsHtml = vaults.length === 0
            ? toolbar + `<div class="empty-state">Хранилищ нет</div>`
            : toolbar + `<div class="settings-grid">${vaults.map(vault => `
            <article class="settings-card" data-id="${this.escapeHtml(vault.vault_id)}">
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

        return `<div class="domain-rail-layout">
            ${railHtml}
            <div class="domain-rail-pane">${cardsHtml}</div>
        </div>`;
    },

    _attachVaultsTabListeners(container) {
        if (window.DomainRail) {
            window.DomainRail.attach(container, (domainId) => {
                this._activeDomainId = domainId || null;
                this.loadTab('vaults');
            });
        }
    },

    async showVaultModal(vaultId = null) {
        const isEdit = !!vaultId;
        let vault = null;
        if (vaultId) {
            try { vault = await this.api.getVault(vaultId); }
            catch (e) { alert('Ошибка загрузки хранилища: ' + e.message); return; }
        }

        let domains = [];
        try {
            const dr = await this.api.getSettingsDomains();
            domains = Array.isArray(dr) ? dr : (dr.domains || []);
        } catch (_) {}

        const selectedDomainId = this._activeDomainId || null;

        const overlay = document.createElement('div');
        overlay.className = 'modal';
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:1000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.55);';
        overlay.innerHTML = `<div class="modal-content" style="max-width:480px;width:100%;">
            <div class="modal-header">
                <h3>${vault ? 'Редактировать vault' : 'Новое хранилище'}</h3>
                <button class="btn-close" id="vault-modal-close">✕</button>
            </div>
            <div class="form-group" style="padding:0 1.5rem;margin-top:1rem;">
                <label>ID хранилища ${!isEdit ? '<span style="color:var(--color-error);">*</span>' : ''}</label>
                <input type="text" id="vault-id" class="input-field" value="${this.escapeHtml(vault?.vault_id || '')}" ${isEdit ? 'readonly' : ''} placeholder="my-vault">
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Отображаемое имя</label>
                <input type="text" id="vault-name" class="input-field" value="${this.escapeHtml(vault?.display_name || '')}" placeholder="Моё хранилище">
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Домен</label>
                <select id="vault-domain-id" class="input-field">
                    <option value="">— без домена —</option>
                    ${domains.map(d => {
                        const did = this.escapeHtml(d.domain_id || d.id || '');
                        const dname = this.escapeHtml(d.display_name || d.domain_id || d.id || '');
                        const currentDomainId = vault?.domain_id || selectedDomainId;
                        const sel = (d.domain_id || d.id) === currentDomainId ? ' selected' : '';
                        return `<option value="${did}"${sel}>${dname}</option>`;
                    }).join('')}
                </select>
            </div>
            <div class="modal-actions" style="display:flex;justify-content:space-between;gap:8px;margin-top:1rem;padding:1rem 1.5rem;border-top:1px solid var(--color-border);">
                <button class="btn btn-primary" id="vault-save-btn">${isEdit ? 'Сохранить' : 'Создать'}</button>
                ${isEdit ? `<button class="btn" style="color:var(--color-error);" id="vault-delete-btn">Удалить хранилище</button>` : ''}
            </div>
        </div>`;
        document.body.appendChild(overlay);

        overlay.querySelector('#vault-modal-close').onclick = () => overlay.remove();

        overlay.querySelector('#vault-save-btn').addEventListener('click', async () => {
            const vId = overlay.querySelector('#vault-id').value.trim();
            const vName = overlay.querySelector('#vault-name').value.trim();
            const vDomain = overlay.querySelector('#vault-domain-id').value || null;
            if (!vId) { alert('Введите ID хранилища'); return; }
            try {
                if (isEdit) {
                    await this.api.updateVault(vaultId, { display_name: vName, domain_id: vDomain });
                } else {
                    await this.api.createVault({ vault_id: vId, display_name: vName, domain_id: vDomain });
                }
                overlay.remove();
                this.loadTab('vaults');
            } catch (e) { alert('Ошибка: ' + e.message); }
        });

        overlay.querySelector('#vault-delete-btn')?.addEventListener('click', async () => {
            if (!confirm('Удалить хранилище? Это действие необратимо.')) return;
            try {
                await this.api.deleteVault(vaultId);
                overlay.remove();
                this.loadTab('vaults');
            } catch (e) { alert('Ошибка: ' + e.message); }
        });
    },

    async handleVaultsAction(action, id) {
        if (action === 'new-vault') { await this.showVaultModal(); return; }
        if (action === 'edit-vault') { await this.showVaultModal(id); return; }
        if (action === 'toggle-vault') {
            try {
                const vault = await this.api.getVault(id);
                await this.api.updateVault(id, { enabled: !vault.enabled });
                this.loadTab('vaults');
            } catch (e) { alert(e.message); }
        }
        if (action === 'delete-vault') {
            if (!confirm('Удалить хранилище?')) return;
            try { await this.api.deleteVault(id); this.loadTab('vaults'); }
            catch (e) { alert(e.message); }
        }
    },
};

Object.assign(SettingsManager.prototype, VaultsTabMixin);
