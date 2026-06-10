const RerankModelsTabMixin = {

    // ─── Render ──────────────────────────────────────────────────────────────────

    async renderRerankModelsTab() {
        const models = await this.api.getRerankModels();
        const modelsArr = Array.isArray(models) ? models : [];
        return this._renderRerankModelList(modelsArr);
    },

    _renderRerankModelList(models) {
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-rerank">+ Добавить модель</button></div>`;
        if (!models || models.length === 0) {
            return toolbar + `<div class="empty-state">Нет reranker-моделей. Нажмите «Добавить модель», чтобы добавить первую.</div>`;
        }
        return toolbar + `<div class="settings-grid">${models.map(model => {
            const isActive = !!model.is_active;
            const isEnabled = model.enabled !== false;
            let badgeClass = 'muted';
            let badgeText = 'неактивна';
            let indicator = '⚪';
            if (isActive && isEnabled) {
                badgeClass = 'ok';
                badgeText = 'АКТИВНА';
                indicator = '🟢';
            } else if (!isEnabled) {
                badgeClass = 'muted';
                badgeText = 'отключена';
                indicator = '⚫';
            }
            const activateBtn = !isActive
                ? `<button class="card-menu-item" data-action="activate-rerank" data-id="${this.escapeHtml(model.model_id)}">▶️ Активировать</button>`
                : `<button class="card-menu-item" data-action="deactivate-rerank" data-id="${this.escapeHtml(model.model_id)}">⏸️ Деактивировать</button>`;
            return `<article class="settings-card${isActive ? ' settings-card--active' : ''}">
                <div class="settings-card-body">
                    <h3>${this.escapeHtml(model.display_name || model.model_id)} <span class="badge ${badgeClass}">${badgeText}</span> ${indicator}</h3>
                    <p class="settings-card-meta">${this.escapeHtml(model.base_url || '')} &nbsp;·&nbsp; ${this.escapeHtml(model.provider || '')}</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(model.model_id)}" aria-label="Меню модели">⋮</button>
                    <div class="card-menu">
                        ${activateBtn}
                        <button class="card-menu-item" data-action="edit-rerank" data-id="${this.escapeHtml(model.model_id)}">✏️ Редактировать</button>
                        <button class="card-menu-item" data-action="check-rerank" data-id="${this.escapeHtml(model.model_id)}">🔍 Проверить</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-rerank" data-id="${this.escapeHtml(model.model_id)}"${isActive ? ' disabled title="Нельзя удалить активную модель"' : ''}>🗑️ Удалить</button>
                    </div>
                </div>
            </article>`;
        }).join('')}</div>`;
    },

    // ─── Action handler ───────────────────────────────────────────────────────────

    async handleRerankModelsAction(action, id, btn) {
        if (action === 'new-rerank') {
            await this.showRerankModelModal();

        } else if (action === 'edit-rerank') {
            // Получаем актуальные данные модели из уже загруженного списка
            // или делаем запрос к API через список моделей
            try {
                const models = await this.api.getRerankModels();
                const model = (Array.isArray(models) ? models : []).find(m => m.model_id === id);
                if (!model) { alert('Модель не найдена'); return; }
                await this.showRerankModelEditModal(model);
            } catch (e) { alert('Ошибка загрузки данных модели: ' + e.message); }

        } else if (action === 'activate-rerank') {
            try {
                await this.api.activateRerankModel(id);
                await this.loadTab('rerank-models');
            } catch (e) { alert('Ошибка активации: ' + e.message); }

        } else if (action === 'deactivate-rerank') {
            try {
                await this.api.deactivateRerankModel(id);
                await this.loadTab('rerank-models');
            } catch (e) { alert('Ошибка деактивации: ' + e.message); }

        } else if (action === 'check-rerank') {
            const origText = btn ? btn.textContent : '';
            if (btn) btn.textContent = '⏳ Проверка...';
            try {
                const result = await this.api.checkRerankModel(id);
                if (result && result.ok) {
                    alert(`✅ Модель доступна (${result.latency_ms} мс)`);
                } else {
                    alert('❌ ' + (result?.error || 'Модель недоступна'));
                }
            } catch (e) {
                alert('❌ Ошибка проверки: ' + e.message);
            } finally {
                if (btn) btn.textContent = origText;
            }

        } else if (action === 'delete-rerank') {
            if (!confirm(`Удалить reranker-модель «${id}»?`)) return;
            try {
                await this.api.deleteRerankModel(id);
                await this.loadTab('rerank-models');
            } catch (e) { alert('Ошибка удаления: ' + e.message); }
        }
    },

    // ─── Create modal ─────────────────────────────────────────────────────────────

    async showRerankModelModal() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новая reranker-модель</h3>

                <div class="form-group">
                    <label>ID модели <span style="color:var(--color-error,#c00)">*</span></label>
                    <input type="text" id="rerank-model-id" placeholder="dengcao/Qwen3-Reranker-0.6B:Q8_0">
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">
                        Для Ollama — полное имя модели. Для других провайдеров — slug.
                    </small>
                </div>

                <div class="form-group">
                    <label>Название (display name)</label>
                    <input type="text" id="rerank-model-name" placeholder="Qwen3 Reranker 0.6B">
                </div>

                <div class="form-group">
                    <label>Провайдер</label>
                    <select id="rerank-model-provider">
                        <option value="openai_compatible">OpenAI Compatible</option>
                        <option value="cohere">Cohere</option>
                        <option value="jina">Jina</option>
                        <option value="ollama">Ollama</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Base URL <span style="color:var(--color-error,#c00)">*</span></label>
                    <input type="text" id="rerank-model-base-url" placeholder="http://localhost:11434">
                </div>

                <div class="form-group" id="rerank-api-key-group">
                    <label>API Key</label>
                    <input type="password" id="rerank-model-api-key" placeholder="••••••••">
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">
                        Оставьте пустым, если аутентификация не нужна.
                    </small>
                </div>

                <div class="form-group">
                    <label>Timeout (сек)</label>
                    <input type="number" id="rerank-model-timeout" value="30" min="1" max="300">
                </div>

                <div class="modal-actions">
                    <button id="rerank-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="rerank-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;

        document.body.appendChild(modal);
        const closeModal = () => modal.remove();

        modal.querySelector('#rerank-model-cancel-btn').addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

        const providerSelect = modal.querySelector('#rerank-model-provider');
        const apiKeyGroup = modal.querySelector('#rerank-api-key-group');
        const baseUrlInput = modal.querySelector('#rerank-model-base-url');

        const _onProviderChange = () => {
            const isOllama = providerSelect.value === 'ollama';
            apiKeyGroup.style.display = isOllama ? 'none' : '';
            baseUrlInput.placeholder = isOllama ? 'http://localhost:11434' : 'http://localhost:8001';
        };
        providerSelect.addEventListener('change', _onProviderChange);
        _onProviderChange();

        modal.querySelector('#rerank-model-save-btn').addEventListener('click', async () => {
            const modelId = modal.querySelector('#rerank-model-id').value.trim();
            const baseUrl = modal.querySelector('#rerank-model-base-url').value.trim();
            if (!modelId) { alert('Укажите ID модели'); return; }
            if (!baseUrl) { alert('Укажите Base URL'); return; }

            const provider = modal.querySelector('#rerank-model-provider').value;
            const data = {
                model_id: modelId,
                display_name: modal.querySelector('#rerank-model-name').value.trim() || null,
                provider,
                base_url: baseUrl,
                timeout_seconds: parseInt(modal.querySelector('#rerank-model-timeout').value, 10) || 30,
            };
            if (provider !== 'ollama') {
                const apiKey = modal.querySelector('#rerank-model-api-key').value;
                if (apiKey) data.api_key = apiKey;
            }

            const saveBtn = modal.querySelector('#rerank-model-save-btn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Сохранение...';
            try {
                await this.api.createRerankModel(data);
                closeModal();
                await this.loadTab('rerank-models');
            } catch (err) {
                alert('Ошибка: ' + err.message);
                saveBtn.disabled = false;
                saveBtn.textContent = 'Сохранить';
            }
        });
    },

    // ─── Edit modal ───────────────────────────────────────────────────────────────

    async showRerankModelEditModal(model) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Редактировать reranker-модель</h3>

                <div class="form-group">
                    <label>ID модели</label>
                    <input type="text" id="rerank-edit-id" value="${this.escapeHtml(model.model_id)}" disabled
                        style="background:var(--color-surface-offset,#f3f3f3);color:var(--color-text-muted,#888);cursor:not-allowed;">
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">ID нельзя изменить после создания.</small>
                </div>

                <div class="form-group">
                    <label>Название (display name)</label>
                    <input type="text" id="rerank-edit-name" value="${this.escapeHtml(model.display_name || '')}" placeholder="Qwen3 Reranker 0.6B">
                </div>

                <div class="form-group">
                    <label>Провайдер</label>
                    <select id="rerank-edit-provider">
                        <option value="openai_compatible"${model.provider === 'openai_compatible' ? ' selected' : ''}>OpenAI Compatible</option>
                        <option value="cohere"${model.provider === 'cohere' ? ' selected' : ''}>Cohere</option>
                        <option value="jina"${model.provider === 'jina' ? ' selected' : ''}>Jina</option>
                        <option value="ollama"${model.provider === 'ollama' ? ' selected' : ''}>Ollama</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Base URL <span style="color:var(--color-error,#c00)">*</span></label>
                    <input type="text" id="rerank-edit-base-url" value="${this.escapeHtml(model.base_url || '')}" placeholder="http://host.docker.internal:11434">
                </div>

                <div class="form-group" id="rerank-edit-api-key-group">
                    <label>API Key</label>
                    <input type="password" id="rerank-edit-api-key" placeholder="${model.has_api_key ? '••••••••  (оставьте пустым, чтобы не менять)' : '••••••••'}">
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">
                        ${model.has_api_key ? 'Ключ задан. Введите новый чтобы заменить, или оставьте пустым.' : 'Оставьте пустым, если аутентификация не нужна.'}
                    </small>
                </div>

                <div class="form-group">
                    <label>Timeout (сек)</label>
                    <input type="number" id="rerank-edit-timeout" value="${model.timeout_seconds || 30}" min="1" max="300">
                </div>

                <div class="form-group">
                    <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                        <input type="checkbox" id="rerank-edit-enabled"${model.enabled !== false ? ' checked' : ''}>
                        Включена (enabled)
                    </label>
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">Отключённую модель нельзя активировать.</small>
                </div>

                <div class="modal-actions">
                    <button id="rerank-edit-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="rerank-edit-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;

        document.body.appendChild(modal);
        const closeModal = () => modal.remove();

        modal.querySelector('#rerank-edit-cancel-btn').addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

        // Скрывать API key для Ollama
        const providerSelect = modal.querySelector('#rerank-edit-provider');
        const apiKeyGroup = modal.querySelector('#rerank-edit-api-key-group');
        const _onProviderChange = () => {
            apiKeyGroup.style.display = providerSelect.value === 'ollama' ? 'none' : '';
        };
        providerSelect.addEventListener('change', _onProviderChange);
        _onProviderChange();

        modal.querySelector('#rerank-edit-save-btn').addEventListener('click', async () => {
            const baseUrl = modal.querySelector('#rerank-edit-base-url').value.trim();
            if (!baseUrl) { alert('Укажите Base URL'); return; }

            const provider = modal.querySelector('#rerank-edit-provider').value;
            const data = {
                display_name: modal.querySelector('#rerank-edit-name').value.trim() || null,
                provider,
                base_url: baseUrl,
                timeout_seconds: parseInt(modal.querySelector('#rerank-edit-timeout').value, 10) || 30,
                enabled: modal.querySelector('#rerank-edit-enabled').checked,
            };

            // API key: отправляем только если что-то введено
            if (provider !== 'ollama') {
                const apiKey = modal.querySelector('#rerank-edit-api-key').value;
                if (apiKey) data.api_key = apiKey;
            }

            const saveBtn = modal.querySelector('#rerank-edit-save-btn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Сохранение...';
            try {
                await this.api.updateRerankModel(model.model_id, data);
                closeModal();
                await this.loadTab('rerank-models');
            } catch (err) {
                alert('Ошибка: ' + err.message);
                saveBtn.disabled = false;
                saveBtn.textContent = 'Сохранить';
            }
        });
    },
};

Object.assign(SettingsManager.prototype, RerankModelsTabMixin);
