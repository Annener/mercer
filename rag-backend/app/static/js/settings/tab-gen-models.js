const GenModelsTabMixin = {
    renderModelList(kind, models, label = '') {
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-${kind}">+ Новая ${label}модель</button></div>`;
        if (!models || models.length === 0) return toolbar + `<div class="empty-state">Нет моделей</div>`;
        return toolbar + `<div class="settings-grid">${models.map(model => {
            let badgeClass = 'muted', badgeText = 'ready';
            if (model.is_active) { badgeClass = 'ok'; badgeText = 'active'; }
            else if (model.enabled === false) { badgeClass = 'muted'; badgeText = 'disabled'; }
            else if (kind === 'emb') { badgeClass = 'ok'; badgeText = 'ready'; }
            const activateItem = kind === 'gen'
                ? `<button class="card-menu-item" data-action="activate-${kind}" data-id="${this.escapeHtml(model.model_id)}"${model.is_active ? ' disabled' : ''}>▶️ Активировать</button>`
                : '';
            const deleteDisabled = (kind === 'gen' && model.is_active) || (model.connected_vaults && model.connected_vaults.length) ? ' disabled' : '';
            return `<article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(model.display_name || model.model_id)}</h3>
                    <p>${this.escapeHtml(model.provider || '')}${model.dimensions ? ` · ${model.dimensions}` : ''}</p>
                    ${model.connected_vaults ? `<p>${model.connected_vaults.length} vault'ов</p>` : ''}
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(model.model_id)}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-${kind}" data-id="${this.escapeHtml(model.model_id)}">✏️ Изменить</button>
                        <button class="card-menu-item" data-action="check-${kind}" data-id="${this.escapeHtml(model.model_id)}">🔍 Проверить</button>
                        ${activateItem}
                        <button class="card-menu-item card-menu-danger" data-action="delete-${kind}" data-id="${this.escapeHtml(model.model_id)}"${deleteDisabled}>🗑️ Удалить</button>
                    </div>
                </div>
                <div><span class="badge ${badgeClass}">${badgeText}</span></div>
            </article>`;
        }).join('')}</div>`;
    },

    async renderGenerationModelsTab() {
        const models = await this.api.getGenerationModels();
        return this.renderModelList('gen', Array.isArray(models) ? models : []);
    },

    async showGenerationModelModal(modelId = null) {
        let model = null;
        if (modelId) {
            const models = await this.api.getGenerationModels();
            model = (Array.isArray(models) ? models : []).find(m => m.model_id === modelId);
            if (!model) { alert('Модель не найдена'); return; }
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${model ? 'Редактировать модель' : 'Новая generation-модель'}</h3>
                <div class="form-group">
                    <label>ID модели</label>
                    <input type="text" id="gen-model-id" value="${this.escapeHtml(model?.model_id || '')}" ${model ? 'disabled' : ''}>
                </div>
                <div class="form-group">
                    <label>Название</label>
                    <input type="text" id="gen-model-name" value="${this.escapeHtml(model?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Провайдер</label>
                    <select id="gen-model-provider" ${model ? 'disabled' : ''}>
                        <option value="openai_compatible" ${model?.provider === 'openai_compatible' ? 'selected' : ''}>OpenAI Compatible</option>
                        <option value="ollama" ${model?.provider === 'ollama' ? 'selected' : ''}>Ollama</option>
                        <option value="anthropic" ${model?.provider === 'anthropic' ? 'selected' : ''}>Anthropic</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>API Key (оставьте пустым чтобы не менять)</label>
                    <input type="password" id="gen-model-api-key" placeholder="••••••••">
                </div>
                <div class="form-group">
                    <label>Base URL</label>
                    <input type="text" id="gen-model-base-url" value="${this.escapeHtml(model?.base_url || '')}">
                </div>
                <div class="form-group">
                    <label>Timeout (сек)</label>
                    <input type="number" id="gen-model-timeout" value="${model?.timeout_seconds || 60}">
                </div>
                <div class="modal-actions">
                    <button id="gen-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="gen-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        const closeModal = () => modal.remove();
        modal.querySelector('#gen-model-cancel-btn').addEventListener('click', closeModal);
        modal.querySelector('#gen-model-save-btn').addEventListener('click', async () => {
            const data = {
                display_name: modal.querySelector('#gen-model-name').value,
                base_url: modal.querySelector('#gen-model-base-url').value,
                timeout_seconds: parseInt(modal.querySelector('#gen-model-timeout').value, 10),
            };
            const apiKey = modal.querySelector('#gen-model-api-key').value;
            if (apiKey) data.api_key = apiKey;
            try {
                if (modelId) await this.api.updateGenerationModel(modelId, data);
                else {
                    data.model_id = modal.querySelector('#gen-model-id').value;
                    data.provider = modal.querySelector('#gen-model-provider').value;
                    await this.api.createGenerationModel(data);
                }
                closeModal();
                await this.loadTab(this.currentTab);
            } catch (err) { alert('Ошибка: ' + err.message); }
        });
    },
};

Object.assign(SettingsManager.prototype, GenModelsTabMixin);