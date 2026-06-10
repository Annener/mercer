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

    // ─── Modal ────────────────────────────────────────────────────────────────────

    async showRerankModelModal() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новая reranker-модель</h3>

                <div class="form-group">
                    <label>ID модели <span style="color:var(--color-error,#c00)">*</span></label>
                    <input type="text" id="rerank-model-id" placeholder="bge-reranker-v2">
                    <small style="color:var(--color-text-muted,#888);margin-top:4px;display:block;">
                        Slug-идентификатор, передаётся как <code>"model"</code> в API-запросе.
                    </small>
                </div>

                <div class="form-group">
                    <label>Название (display name)</label>
                    <input type="text" id="rerank-model-name" placeholder="BGE Reranker v2">
                </div>

                <div class="form-group">
                    <label>Провайдер</label>
                    <select id="rerank-model-provider">
                        <option value="openai_compatible">OpenAI Compatible</option>
                        <option value="cohere">Cohere</option>
                        <option value="jina">Jina</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Base URL <span style="color:var(--color-error,#c00)">*</span></label>
                    <input type="text" id="rerank-model-base-url" placeholder="http://localhost:8001">
                </div>

                <div class="form-group">
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

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });

        modal.querySelector('#rerank-model-save-btn').addEventListener('click', async () => {
            const modelId = modal.querySelector('#rerank-model-id').value.trim();
            const baseUrl = modal.querySelector('#rerank-model-base-url').value.trim();

            if (!modelId) { alert('Укажите ID модели'); return; }
            if (!baseUrl) { alert('Укажите Base URL'); return; }

            const data = {
                model_id: modelId,
                display_name: modal.querySelector('#rerank-model-name').value.trim() || null,
                provider: modal.querySelector('#rerank-model-provider').value,
                base_url: baseUrl,
                timeout_seconds: parseInt(modal.querySelector('#rerank-model-timeout').value, 10) || 30,
            };

            const apiKey = modal.querySelector('#rerank-model-api-key').value;
            if (apiKey) data.api_key = apiKey;

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
};

Object.assign(SettingsManager.prototype, RerankModelsTabMixin);
