const EmbModelsTabMixin = {

    async showEmbeddingModelModal(modelId = null) {
        let model = null;
        if (modelId) {
            const models = await this.api.getEmbeddingModels();
            model = (Array.isArray(models) ? models : []).find(m => m.model_id === modelId);
            if (!model) { alert('\u041c\u043e\u0434\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430'); return; }
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${model ? '\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c embedding-\u043c\u043e\u0434\u0435\u043b\u044c' : '\u041d\u043e\u0432\u0430\u044f embedding-\u043c\u043e\u0434\u0435\u043b\u044c'}</h3>
                <div class="form-group">
                    <label>ID \u043c\u043e\u0434\u0435\u043b\u0438</label>
                    <input type="text" id="emb-model-id" value="${this.escapeHtml(model?.model_id || '')}" ${model ? 'disabled' : ''}>
                </div>
                <div class="form-group">
                    <label>\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435</label>
                    <input type="text" id="emb-model-name" value="${this.escapeHtml(model?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>\u041f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440</label>
                    <select id="emb-model-provider" ${model ? 'disabled' : ''}>
                        <option value="openai_compatible" ${model?.provider === 'openai_compatible' ? 'selected' : ''}>OpenAI Compatible</option>
                        <option value="ollama" ${model?.provider === 'ollama' ? 'selected' : ''}>Ollama</option>
                        <option value="sidecar" ${model?.provider === 'sidecar' ? 'selected' : ''}>Sidecar (bge-m3)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Model name / ID</label>
                    <input type="text" id="emb-model-modelname" value="${this.escapeHtml(model?.model_name || '')}">
                </div>
                <div class="form-group">
                    <label>\u0420\u0430\u0437\u043c\u0435\u0440\u043d\u043e\u0441\u0442\u044c (dimensions)</label>
                    <input type="number" id="emb-model-dimensions" value="${model?.dimensions || 768}">
                </div>
                <div class="form-group">
                    <label>Base URL</label>
                    <input type="text" id="emb-model-base-url" value="${this.escapeHtml(model?.base_url || '')}">
                </div>
                <div class="form-group">
                    <label>API Key (\u043e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u043f\u0443\u0441\u0442\u044b\u043c \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u043c\u0435\u043d\u044f\u0442\u044c)</label>
                    <input type="password" id="emb-model-api-key" placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022">
                </div>
                <div class="form-group">
                    <label>Timeout (\u0441\u0435\u043a)</label>
                    <input type="number" id="emb-model-timeout" value="${model?.timeout_seconds || 30}">
                </div>
                <div class="modal-actions">
                    <button id="emb-model-save-btn" class="btn btn-primary">\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c</button>
                    <button id="emb-model-cancel-btn" class="btn btn-secondary">\u041e\u0442\u043c\u0435\u043d\u0430</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        const closeModal = () => modal.remove();
        modal.querySelector('#emb-model-cancel-btn').addEventListener('click', closeModal);

        // \u0410\u0432\u0442\u043e\u0437\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435 \u043f\u043e\u043b\u0435\u0439 \u043f\u0440\u0438 \u0432\u044b\u0431\u043e\u0440\u0435 \u043f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440\u0430 (\u0442\u043e\u043b\u044c\u043a\u043e \u043f\u0440\u0438 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0438)
        if (!model) {
            const providerSelect = modal.querySelector('#emb-model-provider');
            const modelNameInput = modal.querySelector('#emb-model-modelname');
            const baseUrlInput = modal.querySelector('#emb-model-base-url');
            const dimensionsInput = modal.querySelector('#emb-model-dimensions');

            const PROVIDER_DEFAULTS = {
                sidecar: {
                    model_name: 'BAAI/bge-m3',
                    base_url: 'http://pdf-sidecar:8765',
                    dimensions: 1024,
                },
                ollama: {
                    model_name: 'bge-m3:latest',
                    base_url: 'http://ollama:11434',
                    dimensions: 1024,
                },
                openai_compatible: {
                    model_name: '',
                    base_url: '',
                    dimensions: 1536,
                },
            };

            const applyDefaults = () => {
                const defaults = PROVIDER_DEFAULTS[providerSelect.value];
                if (!defaults) return;
                // \u041f\u0435\u0440\u0435\u0437\u0430\u043f\u0438\u0441\u044b\u0432\u0430\u0435\u043c \u0442\u043e\u043b\u044c\u043a\u043e \u0435\u0441\u043b\u0438 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u0435\u0449\u0451 \u043d\u0435 \u0432\u0432\u043e\u0434\u0438\u043b \u0432\u0440\u0443\u0447\u043d\u0443\u044e
                if (!modelNameInput.value) modelNameInput.value = defaults.model_name;
                if (!baseUrlInput.value) baseUrlInput.value = defaults.base_url;
                if (dimensionsInput.value === '768' || !dimensionsInput.value) {
                    dimensionsInput.value = defaults.dimensions;
                }
            };

            providerSelect.addEventListener('change', applyDefaults);
            // \u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c \u0434\u0435\u0444\u043e\u043b\u0442\u044b \u0434\u043b\u044f \u0438\u0437\u043d\u0430\u0447\u0430\u043b\u044c\u043d\u043e \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0433\u043e \u043f\u0440\u043e\u0432\u0430\u0439\u0434\u0435\u0440\u0430
            applyDefaults();
        }

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
            } catch (err) { alert('\u041e\u0448\u0438\u0431\u043a\u0430: ' + err.message); }
        });
    },
};

Object.assign(SettingsManager.prototype, EmbModelsTabMixin);
