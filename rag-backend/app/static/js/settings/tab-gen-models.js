const GenModelsTabMixin = {

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
                    <label>ID модели провайдера</label>
                    <input type="text" id="gen-model-provider-id"
                        value="${this.escapeHtml(model?.model_id || '')}"
                        placeholder="openrouter/deepseek/deepseek-chat-v3.1"
                        ${model ? 'disabled' : ''}>
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">
                        Точное имя модели для API провайдера. Будет передаваться как <code>"model"</code> в запросе.
                    </small>
                </div>
                <div class="form-group">
                    <label>Название модели в системе</label>
                    <input type="text" id="gen-model-name"
                        value="${this.escapeHtml(model?.display_name || '')}"
                        placeholder="Deepseek via Proxy">
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
                    <input type="text" id="gen-model-base-url" value="${this.escapeHtml(model?.base_url || '')}"
                        placeholder="https://openai.api.proxyapi.ru/v1">
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
                if (modelId) {
                    await this.api.updateGenerationModel(modelId, data);
                } else {
                    const providerModelId = modal.querySelector('#gen-model-provider-id').value.trim();
                    if (!providerModelId) { alert('Укажите ID модели провайдера'); return; }
                    // model_id = полный ID провайдера, слеши допустимы ({model_id:path} в API)
                    data.model_id = providerModelId;
                    data.provider = modal.querySelector('#gen-model-provider').value;
                    await this.api.createGenerationModel(data);
                }
                closeModal();
                await this.loadTab('models');
            } catch (err) { alert('Ошибка: ' + err.message); }
        });
    },
};

Object.assign(SettingsManager.prototype, GenModelsTabMixin);
