const VaultsTabMixin = {
    // Дефолтные значения git identity, которые подставляются если пользователь оставил поле пустым.
    _gitDefaultName: 'Mercer',
    _gitDefaultEmail: 'mercer@local',

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
            <button class="btn btn-primary" data-action="new-vault">+ Новый vault</button>
        </div>`;

        const cardsHtml = vaults.length === 0
            ? `<div class="empty-state">Vault'ов нет</div>`
            : `<div class="settings-grid">${vaults.map(vault => `
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

        return `<div class="domain-rail-layout">
            ${railHtml}
            <div class="domain-rail-pane">${toolbar + cardsHtml}</div>
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
        try {
            let vault = null;
            if (vaultId) {
                const vaultsList = await this.api.getSettingsVaults();
                vault = (Array.isArray(vaultsList) ? vaultsList : []).find(v => v.vault_id === vaultId);
            }

            const resp = await this.api.getSettingsDomains();
            const allDomains = Array.isArray(resp) ? resp : (resp.domains || []);
            const domains = allDomains.filter(d => d.enabled !== false);

            const embModels = await this.api.getEmbeddingModels();
            const embModelsArr = Array.isArray(embModels) ? embModels : [];

            // Для git identity используем значение из БД (если есть), иначе — дефолт.
            const currentGitName  = vault?.git_author_name  || this._gitDefaultName;
            const currentGitEmail = vault?.git_author_email || this._gitDefaultEmail;

            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <h3>${vault ? 'Редактировать vault' : 'Новый vault'}</h3>

                    <div class="form-group">
                        <label>ID vault</label>
                        <input type="text" id="vault-id-input"
                               value="${this.escapeHtml(vault?.vault_id || '')}"
                               ${vault ? 'disabled' : ''}>
                    </div>

                    <div class="form-group">
                        <label>Название</label>
                        <input type="text" id="vault-name-input"
                               value="${this.escapeHtml(vault?.display_name || '')}">
                    </div>

                    <div class="form-group">
                        <label>Домен</label>
                        <select id="vault-domain-select">
                            ${domains.map(d =>
                                `<option value="${this.escapeHtml(d.domain_id)}"
                                         ${vault?.domain_id === d.domain_id ? 'selected' : ''}>
                                    ${this.escapeHtml(d.display_name || d.domain_id)}
                                </option>`
                            ).join('')}
                        </select>
                    </div>

                    <div class="form-group">
                        <label>Embedding-модель</label>
                        <select id="vault-emb-model">
                            <option value="">— не выбрана —</option>
                            ${embModelsArr.map(m =>
                                `<option value="${this.escapeHtml(m.model_id)}"
                                         ${vault?.embedding_model_id === m.model_id ? 'selected' : ''}>
                                    ${this.escapeHtml(m.display_name || m.model_id)}
                                </option>`
                            ).join('')}
                        </select>
                    </div>

                    <hr style="margin: 16px 0; border-color: var(--border, #333);">

                    <p style="font-size:0.82em; color:var(--text-muted, #888); margin: 0 0 10px;">
                        <strong>Git identity</strong> — имя автора и email для git-коммитов
                        Campaign Update Mode. Если оставить поля пустыми,
                        будет использоваться значение по умолчанию.
                    </p>

                    <div class="form-group">
                        <label>Git Author Name</label>
                        <input type="text" id="vault-git-name-input"
                               value="${this.escapeHtml(currentGitName)}"
                               placeholder="${this.escapeHtml(this._gitDefaultName)}">
                    </div>

                    <div class="form-group">
                        <label>Git Author Email</label>
                        <input type="email" id="vault-git-email-input"
                               value="${this.escapeHtml(currentGitEmail)}"
                               placeholder="${this.escapeHtml(this._gitDefaultEmail)}">
                    </div>

                    <div class="modal-actions">
                        <button id="vault-save-btn" class="btn btn-primary">Сохранить</button>
                        <button id="vault-cancel-btn" class="btn btn-secondary">Отмена</button>
                    </div>
                </div>`;

            document.body.appendChild(modal);

            modal.querySelector('#vault-cancel-btn')?.addEventListener('click', () => modal.remove());

            modal.querySelector('#vault-save-btn')?.addEventListener('click', async () => {
                // Если пользователь стёр поле — пишем дефолт, чтобы в БД не попала пустая строка.
                const gitName  = modal.querySelector('#vault-git-name-input').value.trim()  || this._gitDefaultName;
                const gitEmail = modal.querySelector('#vault-git-email-input').value.trim() || this._gitDefaultEmail;

                const data = {
                    display_name:       modal.querySelector('#vault-name-input').value,
                    domain_id:          modal.querySelector('#vault-domain-select').value,
                    embedding_model_id: modal.querySelector('#vault-emb-model').value || null,
                    git_author_name:    gitName,
                    git_author_email:   gitEmail,
                };

                if (vaultId) {
                    await this.api.updateVault(vaultId, data);
                } else {
                    data.vault_id = modal.querySelector('#vault-id-input').value;
                    await this.api.createVault(data);
                }

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
