const EmbModelsTabMixin = {

    async showEmbeddingModelModal(modelId = null) {
        let model = null;
        if (modelId) {
            const models = await this.api.getEmbeddingModels();
            model = (Array.isArray(models) ? models : []).find(m => m.model_id === modelId);
            if (!model) { alert('Модель не найдена'); return; }
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${model ? 'Редактировать embedding-модель' : 'Новая embedding-модель'}</h3>
                <div class="form-group">
                    <label>ID модели</label>
                    <input type="text" id="emb-model-id" value="${this.escapeHtml(model?.model_id || '')}" ${model ? 'disabled' : ''}>
                </div>
                <div class="form-group">
                    <label>Название</label>
                    <input type="text" id="emb-model-name" value="${this.escapeHtml(model?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Провайдер</label>
                    <select id="emb-model-provider" ${model ? 'disabled' : ''}>
                        <option value="openai_compatible" ${model?.provider === 'openai_compatible' ? 'selected' : ''}>OpenAI Compatible</option>
                        <option value="ollama" ${model?.provider === 'ollama' ? 'selected' : ''}>Ollama</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Model name / ID</label>
                    <input type="text" id="emb-model-modelname" value="${this.escapeHtml(model?.model_name || '')}">
                </div>
                <div class="form-group">
                    <label>Размерность (dimensions)</label>
                    <input type="number" id="emb-model-dimensions" value="${model?.dimensions || 768}">
                </div>
                <div class="form-group">
                    <label>Base URL</label>
                    <input type="text" id="emb-model-base-url" value="${this.escapeHtml(model?.base_url || '')}">
                </div>
                <div class="form-group">
                    <label>API Key (оставьте пустым чтобы не менять)</label>
                    <input type="password" id="emb-model-api-key" placeholder="••••••••">
                </div>
                <div class="form-group">
                    <label>Timeout (сек)</label>
                    <input type="number" id="emb-model-timeout" value="${model?.timeout_seconds || 30}">
                </div>
                <div class="modal-actions">
                    <button id="emb-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="emb-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        const closeModal = () => modal.remove();
        modal.querySelector('#emb-model-cancel-btn').addEventListener('click', closeModal);
        modal.querySelector('#emb-model-save-btn').addEventListener('click', async () => {
            const data = {
                display_name: modal.querySelector('#emb-model-name').value,
                model_name: modal.querySelector('#emb-model-modelname').value,
                dimensions: parseInt(modal.querySelector('#emb-model-dimensions').value, 10),
                base_url: modal.querySelector('#emb-model-base-url').value,
                timeout_seconds: parseInt(modal.querySelector('#emb-model-timeout').value, 10),
            };
            const apiKey = modal.querySelector('#emb-model-api-key').value;
            if (apiKey) data.api_key = apiKey;
            try {
                if (modelId) await this.api.updateEmbeddingModel(modelId, data);
                else {
                    data.model_id = modal.querySelector('#emb-model-id').value;
                    data.provider = modal.querySelector('#emb-model-provider').value;
                    await this.api.createEmbeddingModel(data);
                }
                closeModal();
                await this.loadTab('models');
            } catch (err) { alert('Ошибка: ' + err.message); }
        });
    },
};

Object.assign(SettingsManager.prototype, EmbModelsTabMixin);
