// ─── Единая статусная модель ──────────────────────────────────────────────────
function modelStatusBadge(isActive, isEnabled) {
    if (isActive)   return { text: 'active',   cssClass: 'badge--status-active' };
    if (!isEnabled) return { text: 'disabled', cssClass: 'badge--status-disabled' };
    return               { text: 'ready',    cssClass: 'badge--status-ready' };
}

const ModelsTabMixin = {
    renderModelCard(config) {
        const menuItemsHtml = config.menuItems.map(item => `
            <button class="card-menu-item${item.danger ? ' card-menu-danger' : ''}"
                    data-action="${this.escapeHtml(item.action)}"
                    data-id="${this.escapeHtml(config.id)}"
                    data-model-type="${this.escapeHtml(config.modelType)}"
                    ${item.disabled ? 'disabled' : ''}>
                ${item.label}
            </button>`).join('');

        return `
        <article class="settings-card${config.isActive ? ' settings-card--active' : ''}"
                 data-id="${this.escapeHtml(config.id)}"
                 data-model-type="${this.escapeHtml(config.modelType)}"
                 data-enabled="${config.isEnabled ? 'true' : 'false'}">
            <div class="settings-card-body">
                <div class="settings-card-name">${this.escapeHtml(config.name)}</div>
                <div class="settings-card-provider">${this.escapeHtml(config.provider)}</div>
            </div>
            <div class="settings-card-badge">
                <span class="badge ${config.badge.cssClass}">${config.badge.text}</span>
            </div>
            <div class="card-menu-container">
                <button class="card-menu-toggle"
                        data-id="${this.escapeHtml(config.id)}"
                        aria-label="Меню модели">⋮</button>
                <div class="card-menu">${menuItemsHtml}</div>
            </div>
        </article>`;
    },

    _renderModelsSection(title, addAction, modelType, bodyHtml) {
        return `
        <div class="models-section">
            <div class="models-section-header">
                <h3 class="models-section-title">${title}</h3>
                <button class="btn btn-primary btn-sm"
                        data-action="${addAction}"
                        data-model-type="${modelType}">+ Добавить</button>
            </div>
            <div class="models-section-body">
                ${bodyHtml}
            </div>
        </div>`;
    },

    async renderModelsTab() {
        const [genHtml, embHtml, rerankHtml] = await Promise.all([
            this._renderGenSection(),
            this._renderEmbSection(),
            this._renderRerankSection(),
        ]);
        return genHtml + embHtml + rerankHtml;
    },

    async _renderGenSection() {
        const models = await this.api.getGenerationModels();
        const modelsArr = Array.isArray(models) ? models : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="settings-empty">Нет моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => this.renderModelCard(this._genModelConfig(m))).join('')}
               </div>`;

        return this._renderModelsSection('Генеративные', 'new-gen', 'gen', bodyHtml);
    },

    _genModelConfig(m) {
        const isActive = !!m.is_active;
        const isEnabled = m.enabled !== false;
        return {
            id: m.model_id,
            modelType: 'gen',
            name: m.display_name || m.model_id,
            provider: m.provider || '',
            badge: modelStatusBadge(isActive, isEnabled),
            isActive,
            isEnabled,
            menuItems: [
                isActive
                    ? { action: 'deactivate-gen', label: '⏸️ Деактивировать' }
                    : { action: 'activate-gen', label: '▶️ Активировать', disabled: !isEnabled },
                { action: 'edit-gen', label: '✏️ Изменить' },
                { action: 'check-gen', label: '🔍 Проверить' },
                { action: 'toggle-gen', label: isEnabled ? '⏸️ Выключить' : '▶️ Включить' },
                { action: 'delete-gen', label: '🗑️ Удалить', danger: true, disabled: isActive },
            ],
        };
    },

    async _renderEmbSection() {
        const [models, vaults] = await Promise.all([
            this.api.getEmbeddingModels(),
            this.api.getSettingsVaults(),
        ]);
        const modelsArr = Array.isArray(models) ? models : [];
        const vaultsArr = Array.isArray(vaults) ? vaults : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="settings-empty">Нет моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => {
                    const linked = vaultsArr.filter(v => v.embedding_model_id === m.model_id);
                    return this.renderModelCard(this._embModelConfig(m, linked));
                }).join('')}
               </div>`;

        return this._renderModelsSection('Embedding', 'new-emb', 'emb', bodyHtml);
    },

    _embModelConfig(m, linkedVaults = []) {
        const hasVaults = linkedVaults.length > 0;
        const isEnabled = m.enabled !== false;
        return {
            id: m.model_id,
            modelType: 'emb',
            name: m.display_name || m.model_id,
            provider: m.provider || '',
            badge: modelStatusBadge(false, isEnabled),
            isActive: false,
            isEnabled,
            menuItems: [
                { action: 'edit-emb', label: '✏️ Изменить' },
                { action: 'check-emb', label: '🔍 Проверить' },
                { action: 'delete-emb', label: '🗑️ Удалить', danger: true, disabled: hasVaults },
            ],
        };
    },

    async _renderRerankSection() {
        const models = await this.api.getRerankModels();
        const modelsArr = Array.isArray(models) ? models : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="settings-empty">Нет reranker-моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => this.renderModelCard(this._rerankModelConfig(m))).join('')}
               </div>`;

        return this._renderModelsSection('Reranker', 'new-rerank', 'rerank', bodyHtml);
    },

    _rerankModelConfig(m) {
        const isActive = !!m.is_active;
        const isEnabled = m.enabled !== false;
        return {
            id: m.model_id,
            modelType: 'rerank',
            name: m.display_name || m.model_id,
            provider: m.provider || '',
            badge: modelStatusBadge(isActive, isEnabled),
            isActive,
            isEnabled,
            menuItems: [
                isActive
                    ? { action: 'deactivate-rerank', label: '⏸️ Деактивировать' }
                    : { action: 'activate-rerank', label: '▶️ Активировать', disabled: !isEnabled },
                { action: 'edit-rerank', label: '✏️ Изменить' },
                { action: 'check-rerank', label: '🔍 Проверить' },
                { action: 'toggle-rerank', label: isEnabled ? '⏸️ Выключить' : '▶️ Включить' },
                { action: 'delete-rerank', label: '🗑️ Удалить', danger: true, disabled: isActive },
            ],
        };
    },
};

Object.assign(SettingsManager.prototype, ModelsTabMixin);
