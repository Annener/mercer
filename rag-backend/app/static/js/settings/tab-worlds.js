const WorldsTabMixin = {
    async renderWorldsTab() {
        const [vaults, worlds] = await Promise.all([this.api.getSettingsVaults(), this.api.getWorlds()]);
        const vaultsArr = Array.isArray(vaults) ? vaults : [];
        const worldsArr = Array.isArray(worlds) ? worlds : [];
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-world">+ Новый мир</button></div>`;
        if (worldsArr.length === 0) return toolbar + `<div class="empty-state">Миров нет</div>`;
        return toolbar + `<div class="settings-grid">${worldsArr.map(world => `
            <article class="settings-card world-card">
                <div>
                    <h3>${this.escapeHtml(world.name)}</h3>
                    <p>${this.escapeHtml(world.world_id)} · ${this.escapeHtml(world.path_prefix)}</p>
                    <p>${this.escapeHtml((vaultsArr.find(vault => vault.vault_id === world.vault_id) || {}).display_name || world.vault_id)}</p>
                </div>
                <div class="settings-actions">
                    <button class="btn btn-sm btn-secondary" data-action="toggle-world" data-id="${this.escapeHtml(world.world_id)}" data-active="${world.is_active ? '1' : '0'}">${world.is_active ? 'Выключить' : 'Включить'}</button>
                    <button class="btn btn-sm btn-secondary" data-action="edit-world" data-id="${world.world_id}">Редактировать</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-world" data-id="${world.world_id}" data-name="${world.name}">Удалить</button>
                </div>
                <div><span class="badge ${world.is_active ? 'ok' : 'muted'}">${world.is_active ? 'active' : 'off'}</span></div>
            </article>`).join('')}</div>`;
    },

    async showWorldModal(worldId = null) {
        const vaults = await this.api.getSettingsVaults();
        const vaultsArr = Array.isArray(vaults) ? vaults : [];

        let existing = null;
        if (worldId) {
            const worlds = await this.api.getWorlds();
            existing = (Array.isArray(worlds) ? worlds : []).find(w => w.world_id === worldId) || null;
        }

        const isEdit = existing !== null;
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${isEdit ? 'Редактировать мир' : 'Новый мир'}</h3>
                ${!isEdit ? `
                <div class="form-group">
                    <label>ID мира</label>
                    <input type="text" id="world-id-input" value="">
                </div>` : ''}
                <div class="form-group">
                    <label>Название</label>
                    <input type="text" id="world-name-input" value="${this.escapeHtml(existing?.name || '')}">
                </div>
                ${!isEdit ? `
                <div class="form-group">
                    <label>Vault</label>
                    <select id="world-vault-select">
                        ${vaultsArr.map(v => `<option value="${this.escapeHtml(v.vault_id)}">${this.escapeHtml(v.display_name || v.vault_id)}</option>`).join('')}
                    </select>
                </div>` : ''}
                <div class="form-group">
                    <label>Path prefix</label>
                    <input type="text" id="world-path-input" placeholder="worlds/myworld/" value="${this.escapeHtml(existing?.path_prefix || '')}">
                </div>
                <div class="form-group">
                    <label>Описание</label>
                    <input type="text" id="world-desc-input" value="${this.escapeHtml(existing?.description || '')}">
                </div>
                <div class="modal-actions">
                    <button id="world-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="world-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.querySelector('#world-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#world-save-btn')?.addEventListener('click', async () => {
            let pathPrefix = modal.querySelector('#world-path-input').value;
            if (pathPrefix && !pathPrefix.endsWith('/')) pathPrefix += '/';

            if (isEdit) {
                const data = {
                    name: modal.querySelector('#world-name-input').value,
                    path_prefix: pathPrefix,
                    description: modal.querySelector('#world-desc-input').value || null,
                };
                await this.api.updateWorld(worldId, data);
            } else {
                const data = {
                    world_id: modal.querySelector('#world-id-input').value,
                    name: modal.querySelector('#world-name-input').value,
                    vault_id: modal.querySelector('#world-vault-select').value,
                    path_prefix: pathPrefix,
                    description: modal.querySelector('#world-desc-input').value || null,
                };
                await this.api.createWorld(data);
            }
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    },
};

Object.assign(SettingsManager.prototype, WorldsTabMixin);