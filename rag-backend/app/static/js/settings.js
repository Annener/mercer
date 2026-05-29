class SettingsManager {
    constructor(api) {
        this.api = api;
        this.currentTab = 'domains';
        this._initialized = false;
        this.init();
    }

    async init() {
        try {
            this.attachEventListeners();
            await this.loadTab(this.currentTab);
            await this.updateStatusBanner();
            this._initialized = true;
        } catch (error) {
            console.error('SettingsManager init failed:', error);
        }
    }

    attachEventListeners() {
        const settingsBtn = document.getElementById('settings-btn');
        const backBtn = document.getElementById('back-to-chat-btn');

        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => this.show());
        } else {
            console.warn('settings-btn not found');
        }

        if (backBtn) {
            backBtn.addEventListener('click', () => this.hide());
        }

        document.querySelectorAll('.settings-tabs button').forEach((button) => {
            button.addEventListener('click', () => this.loadTab(button.dataset.tab));
        });
    }

    show() {
        const appContainer = document.querySelector('.app-container');
        const settingsPage = document.getElementById('settings-page');

        if (appContainer) appContainer.classList.add('hidden');
        if (settingsPage) settingsPage.classList.remove('hidden');

        this.loadTab(this.currentTab);
    }

    hide() {
        const settingsPage = document.getElementById('settings-page');
        const appContainer = document.querySelector('.app-container');

        if (settingsPage) settingsPage.classList.add('hidden');
        if (appContainer) appContainer.classList.remove('hidden');

        this.updateStatusBanner();
    }

    async loadTab(tabId) {
        if (!tabId) return;
        this.currentTab = tabId;
        document.querySelectorAll('.settings-tabs button').forEach((button) => {
            button.classList.toggle('active', button.dataset.tab === tabId);
        });
        const container = document.getElementById('settings-content');
        if (!container) return;
        container.innerHTML = '<div class="loading">Загрузка...</div>';
        try {
            const renderers = {
                domains: () => this.renderDomainsTab(),
                vaults: () => this.renderVaultsTab(),
                'gen-models': () => this.renderGenerationModelsTab(),
                'emb-models': () => this.renderEmbeddingModelsTab(),
                params: () => this.renderParamsTab(),
                pipelines: () => this.renderPipelinesTab(),
                worlds: () => this.renderWorldsTab(),
            };
            container.innerHTML = renderers[tabId]
                ? await renderers[tabId]()
                : '<div class="placeholder">Раздел будет доступен в следующих обновлениях</div>';
            this.attachTabEventHandlers(tabId);
        } catch (error) {
            container.innerHTML = `<div class="error">Ошибка: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    async updateStatusBanner() {
        try {
            const status = await this.api.getSettingsStatus();
            const banner = document.getElementById('status-banner');
            if (!banner) return;
            const messages = [];
            if (!status.has_active_generation_model) messages.push('Не настроена генеративная модель. Чат недоступен.');
            if (!status.has_active_embedding_model) messages.push('Не настроена embedding-модель. Индексация невозможна.');
            if (!status.has_vaults) messages.push('Создайте vault и добавьте документы для работы с RAG.');
            if (!status.pdf_sidecar_available) messages.push('PDF Sidecar недоступен. PDF будут обработаны через pdfminer.');
            banner.innerHTML = messages.map((message) => `<div>${this.escapeHtml(message)}</div>`).join('');
            banner.classList.toggle('hidden', messages.length === 0);
            const chatInput = document.getElementById('message-input');
            if (chatInput) {
                chatInput.disabled = !status.has_active_generation_model;
                if (!status.has_active_generation_model) chatInput.placeholder = 'Генеративная модель не настроена';
            }
        } catch (error) {
            console.error('Failed to update status banner', error);
        }
    }

    async renderDomainsTab() {
        const resp = await this.api.getDomains();
        const domains = resp.domains || [];
        const toolbar = '<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-domain">+ Новый домен</button></div>';
        if (!domains.length) {
            return toolbar + '<div class="empty-state">Домены не найдены</div>';
        }
        return toolbar + `
            <div class="settings-grid">
                ${domains.map((domain) => `
                    <article class="settings-card">
                        <div>
                            <h3>${this.escapeHtml(domain.display_name)}</h3>
                            <p>${this.escapeHtml(domain.domain_id)}</p>
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="edit-domain" data-id="${this.escapeHtml(domain.domain_id)}">Редактировать</button>
                                <button class="btn btn-sm btn-danger" data-action="delete-domain" data-id="${this.escapeHtml(domain.domain_id)}" ${domain.is_system ? 'disabled' : ''}>Удалить</button>
                            </div>
                        </div>
                        <span class="badge ${domain.enabled ? 'ok' : 'muted'}">${domain.enabled ? 'enabled' : 'disabled'}</span>
                    </article>
                `).join('')}
            </div>`;
    }

    async renderVaultsTab() {
        let vaults = await this.api.getSettingsVaults();
        if (!Array.isArray(vaults)) vaults = [];
        const toolbar = '<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-vault">+ Новый vault</button></div>';
        if (vaults.length === 0) {
            return toolbar + '<div class="empty-state">Vault&#39;ы не найдены</div>';
        }
        return toolbar + `
            <div class="settings-grid">
                ${vaults.map((vault) => `
                    <article class="settings-card">
                        <div>
                            <h3>${this.escapeHtml(vault.display_name || vault.vault_id)}</h3>
                            <p>/data/vaults/${this.escapeHtml(vault.vault_id)}</p>
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="edit-vault" data-id="${this.escapeHtml(vault.vault_id)}">Редактировать</button>
                                <button class="btn btn-sm btn-secondary" data-action="toggle-vault" data-id="${this.escapeHtml(vault.vault_id)}">${vault.enabled ? 'Выкл' : 'Вкл'}</button>
                                <button class="btn btn-sm btn-danger" data-action="delete-vault" data-id="${this.escapeHtml(vault.vault_id)}">Удалить</button>
                            </div>
                        </div>
                        <span class="badge ${vault.enabled ? 'ok' : 'muted'}">${this.escapeHtml(vault.binding_status || 'unbound')} · ${vault.chunk_count || 0}</span>
                    </article>
                `).join('')}
            </div>`;
    }

    async renderGenerationModelsTab() {
        const models = await this.api.getGenerationModels();
        return this.renderModelList('gen', models, '+ Новая модель');
    }

    async renderEmbeddingModelsTab() {
        const [models, vaults] = await Promise.all([this.api.getEmbeddingModels(), this.api.getSettingsVaults()]);
        const enriched = (models || []).map((model) => ({
            ...model,
            connected_vaults: (vaults || []).filter((vault) => vault.embedding_model_id === model.model_id),
        }));
        return this.renderModelList('emb', enriched, '+ Новая embedding-модель');
    }

    renderModelList(kind, models, label) {
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-${kind}">${label}</button></div>`;
        if (!models || models.length === 0) {
            return toolbar + '<div class="empty-state">Нет записей</div>';
        }
        return toolbar + `
            <div class="settings-grid">
                ${models.map((model) => `
                    <article class="settings-card">
                        <div>
                            <h3>${this.escapeHtml(model.display_name || model.model_id)}</h3>
                            <p>${this.escapeHtml(model.provider || '')} ${model.dimensions ? `· ${model.dimensions}` : ''}</p>
                            ${model.connected_vaults ? `<p>${model.connected_vaults.length} vault&#39;ов</p>` : ''}
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="edit-${kind}" data-id="${this.escapeHtml(model.model_id)}">Редактировать</button>
                                <button class="btn btn-sm btn-secondary" data-action="check-${kind}" data-id="${this.escapeHtml(model.model_id)}">Проверить</button>
                                ${kind === 'gen' ? `<button class="btn btn-sm btn-secondary" data-action="activate-gen" data-id="${this.escapeHtml(model.model_id)}" ${model.is_active ? 'disabled' : ''}>Активировать</button>` : ''}
                                <button class="btn btn-sm btn-danger" data-action="delete-${kind}" data-id="${this.escapeHtml(model.model_id)}" ${(kind === 'gen' && model.is_active) || (model.connected_vaults && model.connected_vaults.length) ? 'disabled' : ''}>Удалить</button>
                            </div>
                        </div>
                        <span class="badge ${model.is_active ? 'ok' : 'muted'}">${model.is_active ? 'активна' : (model.enabled === false ? 'disabled' : 'ready')}</span>
                    </article>
                `).join('')}
            </div>`;
    }

    _getParamType(key) {
        const boolKeys = [
            'retrieval.enabled', 'reranker.enabled', 'chat.stream_answers',
            'chat.auto_title', 'chunking.entity_aware_mode', 'pdf_sidecar.fallback_to_pdfminer'
        ];
        return boolKeys.includes(key) ? 'bool' : 'string';
    }

    async renderParamsTab() {
        const params = await this.api.getSettingsParams();
        const sortedKeys = Object.keys(params).sort();
        return `
            <div class="settings-toolbar"><button class="btn btn-secondary" data-action="reset-params">Сбросить все к дефолтам</button></div>
            <div class="settings-param-list">
                ${sortedKeys.map((key) => {
                    const isBool = this._getParamType(key) === 'bool';
                    const currentValue = params[key];
                    const inputHtml = isBool
                        ? `<input type="checkbox" data-param="${this.escapeHtml(key)}" ${(currentValue === true || currentValue === 'true') ? 'checked' : ''}>`
                        : `<input data-param="${this.escapeHtml(key)}" value="${this.escapeHtml(currentValue ?? '')}">`;
                    return `
                        <label class="settings-param-row">
                            <span>${this.escapeHtml(key)}</span>
                            ${inputHtml}
                            <button class="btn btn-sm btn-secondary" data-action="default-param" data-id="${this.escapeHtml(key)}">Дефолт</button>
                        </label>
                    `;
                }).join('')}
            </div>`;
    }

    async renderPipelinesTab() {
        let pipelines = await this.api.getPipelines();
        if (!Array.isArray(pipelines)) pipelines = [];
        const toolbar = '<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-pipeline">+ Новый pipeline</button></div>';
        if (pipelines.length === 0) {
            return toolbar + '<div class="empty-state">Pipeline&#39;ы не найдены</div>';
        }
        return toolbar + `
            <div class="settings-grid">
                ${pipelines.map((pipeline) => `
                    <article class="settings-card">
                        <div>
                            <h3>${this.escapeHtml(pipeline.name)}</h3>
                            <p>${this.escapeHtml(pipeline.pipeline_id)} · ${this.escapeHtml(pipeline.version)} · ${pipeline.steps?.length || 0} шаг.</p>
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="activate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">Активировать</button>
                                <button class="btn btn-sm btn-danger" data-action="deactivate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">Отключить</button>
                            </div>
                        </div>
                        <span class="badge ${pipeline.is_active ? 'ok' : 'muted'}">${pipeline.is_active ? 'активен' : 'архив'}</span>
                    </article>
                `).join('')}
            </div>`;
    }

    async renderWorldsTab() {
        const [vaults, worlds] = await Promise.all([this.api.getSettingsVaults(), this.api.getWorlds()]);
        const toolbar = '<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-world">+ Новый мир</button></div>';
        if (!worlds || worlds.length === 0) {
            return toolbar + '<div class="empty-state">Миры не найдены</div>' + '<p class="settings-note">Удаление миров и кампаний выполняется в файловой системе и через управление хранилищем.</p>';
        }
        return toolbar + `
            <div class="settings-grid">
                ${worlds.map((world) => `
                    <article class="settings-card world-card">
                        <div>
                            <h3>${this.escapeHtml(world.name)}</h3>
                            <p>${this.escapeHtml(world.world_id)} · ${this.escapeHtml(world.path_prefix)}</p>
                            <p>${this.escapeHtml((vaults.find((vault) => vault.vault_id === world.vault_id) || {}).display_name || world.vault_id)}</p>
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="toggle-world" data-id="${this.escapeHtml(world.world_id)}" data-active="${world.is_active ? '1' : '0'}">${world.is_active ? 'Выключить' : 'Включить'}</button>
                            </div>
                        </div>
                        <span class="badge ${world.is_active ? 'ok' : 'muted'}">${world.is_active ? 'active' : 'off'}</span>
                    </article>
                `).join('')}
            </div>
            <p class="settings-note">Удаление миров и кампаний выполняется в файловой системе и через управление хранилищем.</p>`;
    }

    attachTabEventHandlers(tabId) {
        const content = document.getElementById('settings-content');
        content?.querySelectorAll('[data-action]').forEach((button) => {
            button.addEventListener('click', () => this.handleAction(button.dataset.action, button.dataset.id, button));
        });
        content?.querySelectorAll('[data-param]').forEach((input) => {
            const saveParam = async () => {
                let value;
                if (input.type === 'checkbox') {
                    value = input.checked;
                } else {
                    value = input.value;
                }
                await this.api.updateSettingsParam(input.dataset.param, value);
                if (input.dataset.param === 'pdf_sidecar.url') await this.updateStatusBanner();
            };
            if (input.type === 'checkbox') {
                input.addEventListener('change', saveParam);
            } else {
                input.addEventListener('blur', saveParam);
            }
        });
    }

    async handleAction(action, id, button) {
        try {
            if (action === 'new-domain') await this.showDomainModal();
            if (action === 'edit-domain') await this.showDomainModal(id);
            if (action === 'delete-domain' && confirm('Удалить домен?')) await this.api.deleteDomain(id);

            if (action === 'new-vault') await this.showVaultModal();
            if (action === 'edit-vault') await this.showVaultModal(id);
            if (action === 'toggle-vault') await this.api.toggleVault(id);
            if (action === 'delete-vault' && confirm('Удалить vault и его векторы?')) await this.api.deleteVault(id);

            if (action === 'new-gen') await this.showGenerationModelModal();
            if (action === 'edit-gen') await this.showGenerationModelModal(id);
            if (action === 'check-gen') alert(JSON.stringify(await this.api.checkGenerationModel(id), null, 2));
            if (action === 'activate-gen') await this.api.activateGenerationModel(id);
            if (action === 'delete-gen' && confirm('Удалить модель?')) await this.api.deleteGenerationModel(id);

            if (action === 'new-emb') await this.showEmbeddingModelModal();
            if (action === 'edit-emb') await this.showEmbeddingModelModal(id);
            if (action === 'check-emb') alert(JSON.stringify(await this.api.checkEmbeddingModel(id), null, 2));
            if (action === 'delete-emb' && confirm('Удалить embedding-модель?')) await this.api.deleteEmbeddingModel(id);

            if (action === 'reset-params' && confirm('Сбросить все параметры?')) {
                await this.api.resetSettingsParams();
                await this.loadTab(this.currentTab);
                await this.updateStatusBanner();
                return;
            }
            if (action === 'default-param') await this.api.updateSettingsParam(id, SETTINGS_DEFAULTS[id] ?? '');

            if (action === 'new-pipeline') await this.showPipelineModal();
            if (action === 'activate-pipeline') await this.api.activatePipeline(id);
            if (action === 'deactivate-pipeline') await this.api.deactivatePipeline(id);

            if (action === 'new-world') await this.showWorldModal();
            if (action === 'toggle-world') await this.api.updateWorld(id, { is_active: button.dataset.active !== '1' });

            await this.loadTab(this.currentTab);
            await this.updateStatusBanner();
        } catch (error) {
            alert(error.message);
        }
    }

    // === Модальные окна ===
    async showDomainModal(domainId = null) {
        let domain = null;
        if (domainId) {
            const resp = await this.api.getDomains();
            domain = (resp.domains || []).find(d => d.domain_id === domainId) || null;
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${domain ? 'Редактировать домен' : 'Новый домен'}</h3>
                <div class="form-group">
                    <label>ID домена:</label>
                    <input type="text" id="domain-id-input" value="${this.escapeHtml(domain?.domain_id || '')}" ${domain ? 'disabled' : ''} pattern="[a-z0-9_]{3,32}" title="3-32 символа, только a-z, 0-9, _">
                </div>
                <div class="form-group">
                    <label>Отображаемое имя:</label>
                    <input type="text" id="domain-name-input" value="${this.escapeHtml(domain?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Описание:</label>
                    <textarea id="domain-desc-input">${this.escapeHtml(domain?.description || '')}</textarea>
                </div>
                <div class="modal-actions">
                    <button id="domain-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="domain-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#domain-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#domain-save-btn')?.addEventListener('click', async () => {
            const domainIdValue = modal.querySelector('#domain-id-input').value.trim();
            if (!domainId && !/^[a-z0-9_]{3,32}$/.test(domainIdValue)) {
                alert('ID домена должен содержать от 3 до 32 символов, только a-z, 0-9 и _');
                return;
            }
            const data = {
                display_name: modal.querySelector('#domain-name-input').value,
                description: modal.querySelector('#domain-desc-input').value,
            };
            if (domainId) {
                await this.api.updateDomain(domainId, data);
            } else {
                data.domain_id = domainIdValue;
                await this.api.createDomain(data);
            }
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    }

    async showVaultModal(vaultId = null) {
        try {
            let vault = null;
            if (vaultId) {
                const vaultsList = await this.api.getSettingsVaults();
                vault = vaultsList.find(v => v.vault_id === vaultId);
            }
            const resp = await this.api.getDomains();
            const domains = resp.domains || [];
            const embModels = await this.api.getEmbeddingModels();
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <h3>${vault ? 'Редактировать vault' : 'Новый vault'}</h3>
                    <div class="form-group">
                        <label>ID vault:</label>
                        <input type="text" id="vault-id-input" value="${this.escapeHtml(vault?.vault_id || '')}" ${vault ? 'disabled' : ''}>
                    </div>
                    <div class="form-group">
                        <label>Отображаемое имя:</label>
                        <input type="text" id="vault-name-input" value="${this.escapeHtml(vault?.display_name || '')}">
                    </div>
                    <div class="form-group">
                        <label>Домен:</label>
                        <select id="vault-domain-select">
                            ${domains.map((d) => `<option value="${this.escapeHtml(d.domain_id)}" ${vault?.domain_id === d.domain_id ? 'selected' : ''}>${this.escapeHtml(d.display_name)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Embedding-модель:</label>
                        <select id="vault-emb-model">
                            <option value="">— Не выбрана —</option>
                            ${embModels.map(m => `<option value="${this.escapeHtml(m.model_id)}" ${vault?.embedding_model_id === m.model_id ? 'selected' : ''}>${this.escapeHtml(m.display_name || m.model_id)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="modal-actions">
                        <button id="vault-save-btn" class="btn btn-primary">Сохранить</button>
                        <button id="vault-cancel-btn" class="btn btn-secondary">Отмена</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            modal.querySelector('#vault-cancel-btn')?.addEventListener('click', () => modal.remove());
            modal.querySelector('#vault-save-btn')?.addEventListener('click', async () => {
                const data = {
                    display_name: modal.querySelector('#vault-name-input').value,
                    domain_id: modal.querySelector('#vault-domain-select').value,
                    embedding_model_id: modal.querySelector('#vault-emb-model').value || null,
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
    }

    async showGenerationModelModal(modelId = null) {
        let model = null;
        if (modelId) {
            const models = await this.api.getGenerationModels();
            model = models.find(m => m.model_id === modelId);
            if (!model) {
                alert('Модель не найдена');
                return;
            }
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${model ? 'Редактировать генеративную модель' : 'Новая генеративная модель'}</h3>
                <div class="form-group">
                    <label>ID модели:</label>
                    <input type="text" id="gen-model-id" value="${this.escapeHtml(model?.model_id || '')}" ${model ? 'disabled' : ''}>
                </div>
                <div class="form-group">
                    <label>Отображаемое имя:</label>
                    <input type="text" id="gen-model-name" value="${this.escapeHtml(model?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Провайдер:</label>
                    <select id="gen-model-provider" ${model ? 'disabled' : ''}>
                        <option value="openai_compatible" ${model?.provider === 'openai_compatible' ? 'selected' : ''}>OpenAI</option>
                        <option value="ollama" ${model?.provider === 'ollama' ? 'selected' : ''}>Ollama</option>
                        <option value="anthropic" ${model?.provider === 'anthropic' ? 'selected' : ''}>Anthropic</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>API Key (оставьте пустым, если не меняется):</label>
                    <input type="password" id="gen-model-api-key" placeholder="Новый ключ">
                </div>
                <div class="form-group">
                    <label>Base URL:</label>
                    <input type="text" id="gen-model-base-url" value="${this.escapeHtml(model?.base_url || '')}">
                </div>
                <div class="form-group">
                    <label>Timeout (сек):</label>
                    <input type="number" id="gen-model-timeout" value="${model?.timeout_seconds || 60}">
                </div>
                <div class="modal-actions">
                    <button id="gen-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="gen-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
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
                    data.model_id = modal.querySelector('#gen-model-id').value;
                    data.provider = modal.querySelector('#gen-model-provider').value;
                    await this.api.createGenerationModel(data);
                }
                closeModal();
                await this.loadTab(this.currentTab);
            } catch (err) {
                alert('Ошибка: ' + err.message);
            }
        });
    }

    async showEmbeddingModelModal(modelId = null) {
        let model = null;
        if (modelId) {
            const models = await this.api.getEmbeddingModels();
            model = models.find(m => m.model_id === modelId);
            if (!model) {
                alert('Модель не найдена');
                return;
            }
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${model ? 'Редактировать embedding-модель' : 'Новая embedding-модель'}</h3>
                <div class="form-group">
                    <label>ID модели:</label>
                    <input type="text" id="emb-model-id" value="${this.escapeHtml(model?.model_id || '')}" ${model ? 'disabled' : ''}>
                </div>
                <div class="form-group">
                    <label>Отображаемое имя:</label>
                    <input type="text" id="emb-model-name" value="${this.escapeHtml(model?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Провайдер:</label>
                    <select id="emb-model-provider" ${model ? 'disabled' : ''}>
                        <option value="openai_compatible" ${model?.provider === 'openai_compatible' ? 'selected' : ''}>OpenAI</option>
                        <option value="ollama" ${model?.provider === 'ollama' ? 'selected' : ''}>Ollama</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Model name (если отличается от ID):</label>
                    <input type="text" id="emb-model-modelname" value="${this.escapeHtml(model?.model_name || '')}">
                </div>
                <div class="form-group">
                    <label>Размерность (dimensions):</label>
                    <input type="number" id="emb-model-dimensions" value="${model?.dimensions || 768}">
                </div>
                <div class="form-group">
                    <label>Base URL:</label>
                    <input type="text" id="emb-model-base-url" value="${this.escapeHtml(model?.base_url || '')}">
                </div>
                <div class="form-group">
                    <label>API Key (оставьте пустым, если не меняется):</label>
                    <input type="password" id="emb-model-api-key" placeholder="Новый ключ">
                </div>
                <div class="form-group">
                    <label>Timeout (сек):</label>
                    <input type="number" id="emb-model-timeout" value="${model?.timeout_seconds || 30}">
                </div>
                <div class="modal-actions">
                    <button id="emb-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="emb-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
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
                if (modelId) {
                    await this.api.updateEmbeddingModel(modelId, data);
                } else {
                    data.model_id = modal.querySelector('#emb-model-id').value;
                    data.provider = modal.querySelector('#emb-model-provider').value;
                    await this.api.createEmbeddingModel(data);
                }
                closeModal();
                await this.loadTab(this.currentTab);
            } catch (err) {
                alert('Ошибка: ' + err.message);
            }
        });
    }

    async showPipelineModal() {
        const resp = await this.api.getDomains();
        const domains = resp.domains || [];
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новый pipeline</h3>
                <div class="form-group">
                    <label>Название:</label>
                    <input type="text" id="pipeline-name-input">
                </div>
                <div class="form-group">
                    <label>Домен:</label>
                    <select id="pipeline-domain-select">
                        ${domains.map((d) => `<option value="${this.escapeHtml(d.domain_id)}">${this.escapeHtml(d.display_name)}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Версия:</label>
                    <input type="text" id="pipeline-version-input" value="1.0">
                </div>
                <div class="form-group">
                    <label>Шаги (JSON):</label>
                    <textarea id="pipeline-steps-input" class="json-editor" rows="5">[]</textarea>
                </div>
                <div class="modal-actions">
                    <button id="pipeline-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="pipeline-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#pipeline-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#pipeline-save-btn')?.addEventListener('click', async () => {
            try {
                const steps = JSON.parse(modal.querySelector('#pipeline-steps-input').value);
                const data = {
                    pipeline_id: `pipeline_${Date.now()}`,
                    name: modal.querySelector('#pipeline-name-input').value,
                    domain_id: modal.querySelector('#pipeline-domain-select').value,
                    version: modal.querySelector('#pipeline-version-input').value,
                    steps: steps,
                    final_composition: { system_prompt: "You are a helpful assistant." }
                };
                await this.api.createPipeline(data);
                modal.remove();
                await this.loadTab(this.currentTab);
            } catch (e) {
                alert('Ошибка в JSON шагов: ' + e.message);
            }
        });
    }

    async showWorldModal() {
        const vaults = await this.api.getSettingsVaults();
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новый мир</h3>
                <div class="form-group">
                    <label>ID мира:</label>
                    <input type="text" id="world-id-input">
                </div>
                <div class="form-group">
                    <label>Название:</label>
                    <input type="text" id="world-name-input">
                </div>
                <div class="form-group">
                    <label>Vault:</label>
                    <select id="world-vault-select">
                        ${vaults.map((v) => `<option value="${this.escapeHtml(v.vault_id)}">${this.escapeHtml(v.display_name || v.vault_id)}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Path prefix (заканчивается на /):</label>
                    <input type="text" id="world-path-input" placeholder="worlds/my_world/">
                </div>
                <div class="modal-actions">
                    <button id="world-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="world-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#world-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#world-save-btn')?.addEventListener('click', async () => {
            let pathPrefix = modal.querySelector('#world-path-input').value;
            if (pathPrefix && !pathPrefix.endsWith('/')) {
                pathPrefix += '/';
            }
            const data = {
                world_id: modal.querySelector('#world-id-input').value,
                name: modal.querySelector('#world-name-input').value,
                vault_id: modal.querySelector('#world-vault-select').value,
                path_prefix: pathPrefix,
            };
            await this.api.createWorld(data);
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
}

const SETTINGS_DEFAULTS = {
    'retrieval.enabled': true,
    'retrieval.top_k': 10,
    'retrieval.reranker_enabled': false,
    'chunking.chunk_size': 2000,
    'chunking.overlap': 64,
    'chunking.entity_aware_mode': true,
    'chat.max_clarification_turns': 3,
    'chat.stream_answers': true,
    'chat.auto_title': true,
    'reranker.enabled': false,
    'reranker.provider': null,
    'reranker.base_url': null,
    'reranker.model_name': null,
    'pdf_sidecar.url': 'http://host.docker.internal:8765',
    'pdf_sidecar.timeout_seconds': 180,
    'pdf_sidecar.fallback_to_pdfminer': true,
};

document.addEventListener('DOMContentLoaded', () => {
    if (!window.chatAPI) {
        console.error('chatAPI not available');
        return;
    }
    window.settingsManager = new SettingsManager(window.chatAPI);
});