const ModelsTabMixin = {

    // ─── Единый рендерер карточки ─────────────────────────────────────────────
    // config: { id, title, subtitle, subInfo?, badge: {text, class}, isActive, modelType, menuItems[] }
    // menuItem: { action, label, disabled?, danger? }
    renderModelCard(config) {
        const menuItemsHtml = config.menuItems.map(item => `
            <button class="card-menu-item${item.danger ? ' card-menu-danger' : ''}"
                    data-action="${this.escapeHtml(item.action)}"
                    data-id="${this.escapeHtml(config.id)}"
                    data-model-type="${this.escapeHtml(config.modelType)}"
                    ${item.disabled ? 'disabled' : ''}>
                ${item.label}
            </button>`).join('');

        return `<article class="settings-card${config.isActive ? ' settings-card--active' : ''}">
            <div class="settings-card-body">
                <h3>${this.escapeHtml(config.title)}</h3>
                <p class="settings-card-meta">${this.escapeHtml(config.subtitle)}</p>
                ${config.subInfo ? `<p class="settings-card-meta">${this.escapeHtml(config.subInfo)}</p>` : ''}
            </div>
            <div class="card-menu-container">
                <button class="card-menu-toggle"
                        data-id="${this.escapeHtml(config.id)}"
                        aria-label="Меню модели">⋮</button>
                <div class="card-menu">${menuItemsHtml}</div>
            </div>
            <div><span class="badge ${config.badge.class}">${config.badge.text}</span></div>
        </article>`;
    },

    // ─── Обёртка секции ───────────────────────────────────────────────────────
    _renderModelsSection(title, addAction, modelType, bodyHtml) {
        return `
        <div class="models-section">
            <div class="models-section-header">
                <h3 class="models-section-title">${title}</h3>
                <button class="btn btn-primary btn-sm"
                        data-action="${addAction}"
                        data-model-type="${modelType}">+ Добавить модель</button>
            </div>
            <div class="models-section-body">
                ${bodyHtml}
            </div>
        </div>`;
    },

    // ─── Главный рендерер вкладки ─────────────────────────────────────────────
    async renderModelsTab() {
        const [genHtml, embHtml, rerankHtml] = await Promise.all([
            this._renderGenSection(),
            this._renderEmbSection(),
            this._renderRerankSection(),
        ]);
        return genHtml + embHtml + rerankHtml;
    },

    // ─── Секция: Генеративные ─────────────────────────────────────────────────
    async _renderGenSection() {
        const models = await this.api.getGenerationModels();
        const modelsArr = Array.isArray(models) ? models : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="empty-state">Нет моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => this.renderModelCard(this._genModelConfig(m))).join('')}
               </div>`;

        return this._renderModelsSection('Генеративные', 'new-gen', 'gen', bodyHtml);
    },

    _genModelConfig(model) {
        const isActive = !!model.is_active;
        const isEnabled = model.enabled !== false;
        return {
            id: model.model_id,
            modelType: 'gen',
            title: model.display_name || model.model_id,
            subtitle: model.provider || '',
            badge: isActive
                ? { text: 'active', class: 'ok' }
                : (!isEnabled ? { text: 'disabled', class: 'muted' } : { text: 'ready', class: 'muted' }),
            isActive,
            menuItems: [
                { action: 'edit-gen',     label: '✏️ Изменить' },
                { action: 'check-gen',    label: '🔍 Проверить' },
                { action: 'activate-gen', label: '▶️ Активировать', disabled: isActive },
                { action: 'toggle-gen',   label: isEnabled ? '⏸️ Выключить' : '▶️ Включить' },
                { action: 'delete-gen',   label: '🗑️ Удалить', danger: true, disabled: isActive },
            ],
        };
    },

    // ─── Секция: Embedding ────────────────────────────────────────────────────
    async _renderEmbSection() {
        const [models, vaults] = await Promise.all([
            this.api.getEmbeddingModels(),
            this.api.getSettingsVaults(),
        ]);
        const modelsArr = Array.isArray(models) ? models : [];
        const vaultsArr = Array.isArray(vaults) ? vaults : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="empty-state">Нет моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => {
                    const connectedVaults = vaultsArr.filter(v => v.embedding_model_id === m.model_id);
                    return this.renderModelCard(this._embModelConfig(m, connectedVaults));
                }).join('')}
               </div>`;

        return this._renderModelsSection('Embedding', 'new-emb', 'emb', bodyHtml);
    },

    _embModelConfig(model, connectedVaults = []) {
        const hasVaults = connectedVaults.length > 0;
        return {
            id: model.model_id,
            modelType: 'emb',
            title: model.display_name || model.model_id,
            subtitle: `${model.provider || ''}${model.dimensions ? ` · ${model.dimensions}` : ''}`,
            subInfo: hasVaults ? `${connectedVaults.length} vault'ов` : undefined,
            badge: { text: 'ready', class: 'ok' },
            isActive: false,
            menuItems: [
                { action: 'edit-emb',   label: '✏️ Изменить' },
                { action: 'check-emb',  label: '🔍 Проверить' },
                { action: 'delete-emb', label: '🗑️ Удалить', danger: true, disabled: hasVaults },
            ],
        };
    },

    // ─── Секция: Reranker ─────────────────────────────────────────────────────
    async _renderRerankSection() {
        const models = await this.api.getRerankModels();
        const modelsArr = Array.isArray(models) ? models : [];

        const bodyHtml = modelsArr.length === 0
            ? '<div class="empty-state">Нет reranker-моделей</div>'
            : `<div class="settings-grid">
                ${modelsArr.map(m => this.renderModelCard(this._rerankModelConfig(m))).join('')}
               </div>`;

        return this._renderModelsSection('Reranker', 'new-rerank', 'rerank', bodyHtml);
    },

    _rerankModelConfig(model) {
        const isActive = !!model.is_active;
        const isEnabled = model.enabled !== false;
        return {
            id: model.model_id,
            modelType: 'rerank',
            title: model.display_name || model.model_id,
            subtitle: `${model.base_url || ''} · ${model.provider || ''}`,
            badge: isActive && isEnabled
                ? { text: 'АКТИВНА', class: 'ok' }
                : (!isEnabled ? { text: 'отключена', class: 'muted' } : { text: 'неактивна', class: 'muted' }),
            isActive,
            menuItems: [
                ...(isActive
                    ? [{ action: 'deactivate-rerank', label: '⏸️ Деактивировать' }]
                    : [{ action: 'activate-rerank',   label: '▶️ Активировать' }]
                ),
                { action: 'edit-rerank',   label: '✏️ Редактировать' },
                { action: 'check-rerank',  label: '🔍 Проверить' },
                { action: 'delete-rerank', label: '🗑️ Удалить', danger: true, disabled: isActive },
            ],
        };
    },
};

Object.assign(SettingsManager.prototype, ModelsTabMixin);
