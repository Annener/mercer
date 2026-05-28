class SettingsManager {
    constructor(api) {
        this.api = api;
        this.currentTab = 'domains';
        this.init();
    }

    async init() {
        this.attachEventListeners();
        await this.loadTab(this.currentTab);
        await this.updateStatusBanner();
    }

    attachEventListeners() {
        document.getElementById('settings-btn')?.addEventListener('click', () => this.show());
        document.getElementById('back-to-chat-btn')?.addEventListener('click', () => this.hide());
        document.querySelectorAll('.settings-tabs button').forEach((button) => {
            button.addEventListener('click', () => this.loadTab(button.dataset.tab));
        });
    }

    show() {
        document.querySelector('.app-container')?.classList.add('hidden');
        document.getElementById('settings-page')?.classList.remove('hidden');
        this.loadTab(this.currentTab);
    }

    hide() {
        document.getElementById('settings-page')?.classList.add('hidden');
        document.querySelector('.app-container')?.classList.remove('hidden');
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
        const domains = await this.api._request('/settings/domains');
        if (!domains.length) return '<div class="empty-state">Домены не найдены</div>';
        return `
            <div class="settings-toolbar"><button class="btn btn-primary" data-action="new-domain">+ Новый домен</button></div>
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
        const vaults = await this.api.getSettingsVaults();
        if (!vaults.length) return '<div class="empty-state">Vault’ы не найдены</div>';
        return `
            <div class="settings-toolbar"><button class="btn btn-primary" data-action="new-vault">+ Новый vault</button></div>
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
        return this.renderModelList('emb', models.map((model) => ({
            ...model,
            connected_vaults: vaults.filter((vault) => vault.embedding_model_id === model.model_id),
        })), '+ Новая embedding-модель');
    }

    renderModelList(kind, models, label) {
        return `
            <div class="settings-toolbar"><button class="btn btn-primary" data-action="new-${kind}">${label}</button></div>
            <div class="settings-grid">
                ${models.map((model) => `
                    <article class="settings-card">
                        <div>
                            <h3>${this.escapeHtml(model.display_name || model.model_id)}</h3>
                            <p>${this.escapeHtml(model.provider || '')} ${model.dimensions ? `· ${model.dimensions}` : ''}</p>
                            ${model.connected_vaults ? `<p>${model.connected_vaults.length} vault'ов</p>` : ''}
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="check-${kind}" data-id="${this.escapeHtml(model.model_id)}">Проверить</button>
                                ${kind === 'gen' ? `<button class="btn btn-sm btn-secondary" data-action="activate-gen" data-id="${this.escapeHtml(model.model_id)}" ${model.is_active ? 'disabled' : ''}>Активировать</button>` : ''}
                                <button class="btn btn-sm btn-danger" data-action="delete-${kind}" data-id="${this.escapeHtml(model.model_id)}" ${(kind === 'gen' && model.is_active) || (model.connected_vaults && model.connected_vaults.length) ? 'disabled' : ''}>Удалить</button>
                            </div>
                        </div>
                        <span class="badge ${model.is_active ? 'ok' : 'muted'}">${model.is_active ? 'активна' : (model.enabled === false ? 'disabled' : 'ready')}</span>
                    </article>
                `).join('') || '<div class="empty-state">Нет записей</div>'}
            </div>`;
    }

    async renderParamsTab() {
        const params = await this.api.getSettingsParams();
        const sortedKeys = Object.keys(params).sort();
        return `
            <div class="settings-toolbar"><button class="btn btn-secondary" data-action="reset-params">Сбросить все к дефолтам</button></div>
            <div class="settings-param-list">
                ${sortedKeys.map((key) => `
                    <label class="settings-param-row">
                        <span>${this.escapeHtml(key)}</span>
                        <input data-param="${this.escapeHtml(key)}" value="${this.escapeHtml(params[key] ?? '')}">
                        <button class="btn btn-sm btn-secondary" data-action="default-param" data-id="${this.escapeHtml(key)}">Дефолт</button>
                    </label>
                `).join('')}
            </div>`;
    }

    async renderPipelinesTab() {
        const pipelines = await this.api.getPipelines();
        return `
            <div class="settings-toolbar"><button class="btn btn-primary" data-action="new-pipeline">+ Новый pipeline</button></div>
            <div class="settings-grid">
                ${pipelines.map((pipeline) => `
                    <article class="settings-card">
                        <div>
                            <h3>${this.escapeHtml(pipeline.name)}</h3>
                            <p>${this.escapeHtml(pipeline.pipeline_id)} · ${this.escapeHtml(pipeline.version)} · ${pipeline.steps?.length || 0} шаг.</p>
                            <div class="settings-actions">
                                <button class="btn btn-sm btn-secondary" data-action="activate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">Активировать</button>
                                <button class="btn btn-sm btn-danger" data-action="delete-pipeline" data-id="${this.escapeHtml(pipeline.id)}">Деактивировать</button>
                            </div>
                        </div>
                        <span class="badge ${pipeline.is_active ? 'ok' : 'muted'}">${pipeline.is_active ? 'активен' : 'архив'}</span>
                    </article>
                `).join('') || '<div class="empty-state">Pipeline’ы не найдены</div>'}
            </div>`;
    }

    async renderWorldsTab() {
        const [vaults, worlds] = await Promise.all([this.api.getSettingsVaults(), this.api.getWorlds()]);
        return `
            <div class="settings-toolbar"><button class="btn btn-primary" data-action="new-world">+ Новый мир</button></div>
            <p class="settings-note">Удаление миров и кампаний выполняется в файловой системе и через управление хранилищем.</p>
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
                `).join('') || '<div class="empty-state">Миры не найдены</div>'}
            </div>`;
    }

    attachTabEventHandlers(tabId) {
        const content = document.getElementById('settings-content');
        content?.querySelectorAll('[data-action]').forEach((button) => {
            button.addEventListener('click', () => this.handleAction(button.dataset.action, button.dataset.id, button));
        });
        content?.querySelectorAll('[data-param]').forEach((input) => {
            input.addEventListener('blur', async () => {
                await this.api.updateSettingsParam(input.dataset.param, input.value);
                if (input.dataset.param === 'pdf_sidecar.url') await this.updateStatusBanner();
            });
        });
    }

    async handleAction(action, id, button) {
        try {
            // Domain actions
            if (action === 'new-domain') await this.showDomainModal();
            if (action === 'edit-domain') await this.showDomainModal(id);
            if (action === 'delete-domain' && confirm('Удалить домен?')) await this.api.deleteDomain(id);
            
            // Vault actions
            if (action === 'new-vault') await this.showVaultModal();
            if (action === 'edit-vault') await this.showVaultModal(id);
            if (action === 'toggle-vault') await this.api.toggleVault(id);
            if (action === 'delete-vault' && confirm('Удалить vault и его векторы?')) await this.api.deleteVault(id);
            
            // Generation model actions
            if (action === 'new-gen') await this.showGenerationModelModal();
            if (action === 'check-gen') alert(JSON.stringify(await this.api.checkGenerationModel(id), null, 2));
            if (action === 'activate-gen') await this.api.activateGenerationModel(id);
            if (action === 'delete-gen' && confirm('Удалить модель?')) await this.api.deleteGenerationModel(id);
            
            // Embedding model actions
            if (action === 'new-emb') await this.showEmbeddingModelModal();
            if (action === 'check-emb') alert(JSON.stringify(await this.api.checkEmbeddingModel(id), null, 2));
            if (action === 'delete-emb' && confirm('Удалить embedding-модель?')) await this.api.deleteEmbeddingModel(id);
            
            // Params actions
            if (action === 'reset-params' && confirm('Сбросить все параметры?')) {
                await this.api.resetSettingsParams();
                await this.loadTab(this.currentTab);
                await this.updateStatusBanner();
                return;
            }
            if (action === 'default-param') await this.api.updateSettingsParam(id, SETTINGS_DEFAULTS[id] ?? '');
            
            // Pipeline actions
            if (action === 'new-pipeline') await this.showPipelineModal();
            if (action === 'activate-pipeline') await this.api.activatePipeline(id);
            if (action === 'delete-pipeline') await this.api.deletePipeline(id);
            
            // World actions
            if (action === 'new-world') await this.showWorldModal();
            if (action === 'toggle-world') await this.api.updateWorld(id, { is_active: button.dataset.active !== '1' });
            
            await this.loadTab(this.currentTab);
            await this.updateStatusBanner();
        } catch (error) {
            alert(error.message);
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    async showDomainModal(domainId = null) {
        const domain = domainId ? await this.api._request(`/settings/domains/${encodeURIComponent(domainId)}`) : null;
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${domain ? 'Редактировать домен' : 'Новый домен'}</h3>
                <div class="form-group">
                    <label for="domain-id-desc">ID домена:</label>
                    <span class="field-desc" id="domain-id-desc">Уникальный идентификатор домена (3-32 символа, только a-z, 0-9 и _). При редактировании изменение невозможно.</span>
                    <input type="text" id="domain-id-input" value="${this.escapeHtml(domain?.domain_id || '')}" ${domain ? 'disabled' : ''} pattern="[a-z0-9_]{3,32}" title="3-32 символа, только a-z, 0-9, _">
                </div>
                <div class="form-group">
                    <label for="domain-name-desc">Отображаемое имя:</label>
                    <span class="field-desc" id="domain-name-desc">Человекочитаемое название домена для отображения в интерфейсе.</span>
                    <input type="text" id="domain-name-input" value="${this.escapeHtml(domain?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label for="domain-desc-desc">Описание:</label>
                    <span class="field-desc" id="domain-desc-desc">Краткое описание назначения домена (опционально).</span>
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
            const domainIdInput = modal.querySelector('#domain-id-input');
            const domainIdValue = domainIdInput.value.trim();
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
        const vault = vaultId ? await this.api._request(`/settings/vaults/${encodeURIComponent(vaultId)}`) : null;
        const domains = await this.api.getDomains();
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${vault ? 'Редактировать vault' : 'Новый vault'}</h3>
                <div class="form-group">
                    <label for="vault-id-desc">ID vault:</label>
                    <span class="field-desc" id="vault-id-desc">Уникальный идентификатор хранилища документов. При редактировании изменение невозможно.</span>
                    <input type="text" id="vault-id-input" value="${this.escapeHtml(vault?.vault_id || '')}" ${vault ? 'disabled' : ''}>
                </div>
                <div class="form-group">
                    <label for="vault-name-desc">Отображаемое имя:</label>
                    <span class="field-desc" id="vault-name-desc">Человекочитаемое название vault для отображения в интерфейсе (опционально).</span>
                    <input type="text" id="vault-name-input" value="${this.escapeHtml(vault?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label for="vault-domain-desc">Домен:</label>
                    <span class="field-desc" id="vault-domain-desc">Домен, к которому привязывается данный vault.</span>
                    <select id="vault-domain-select">
                        ${domains.map((d) => `<option value="${this.escapeHtml(d.domain_id)}" ${vault?.domain_id === d.domain_id ? 'selected' : ''}>${this.escapeHtml(d.display_name)}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label for="vault-path-desc">Путь к данным:</label>
                    <span class="field-desc" id="vault-path-desc">Путь к папке с документами в файловой системе (например, /data/vaults/my_vault).</span>
                    <input type="text" id="vault-path-input" value="${this.escapeHtml(vault?.data_path || '')}">
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
                data_path: modal.querySelector('#vault-path-input').value,
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
    }

    async showGenerationModelModal() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новая генеративная модель</h3>
                <div class="form-group">
                    <label for="gen-model-id-desc">ID модели:</label>
                    <span class="field-desc" id="gen-model-id-desc">Уникальный идентификатор модели (например, gpt-4, llama3).</span>
                    <input type="text" id="gen-model-id-input">
                </div>
                <div class="form-group">
                    <label for="gen-model-name-desc">Отображаемое имя:</label>
                    <span class="field-desc" id="gen-model-name-desc">Человекочитаемое название модели для отображения в интерфейсе.</span>
                    <input type="text" id="gen-model-name-input">
                </div>
                <div class="form-group">
                    <label for="gen-model-provider-desc">Провайдер:</label>
                    <span class="field-desc" id="gen-model-provider-desc">Поставщик модели: OpenAI, Ollama (локально), Anthropic.</span>
                    <select id="gen-model-provider">
                        <option value="openai">OpenAI</option>
                        <option value="ollama">Ollama</option>
                        <option value="anthropic">Anthropic</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="gen-model-api-key-desc">API Key:</label>
                    <span class="field-desc" id="gen-model-api-key-desc">Ключ доступа к API провайдера. Для Ollama можно оставить пустым.</span>
                    <input type="password" id="gen-model-api-key-input">
                </div>
                <div class="form-group">
                    <label for="gen-model-base-url-desc">Base URL (опционально):</label>
                    <span class="field-desc" id="gen-model-base-url-desc">Адрес сервера API. Оставьте пустым для использования адреса по умолчанию.</span>
                    <input type="text" id="gen-model-base-url-input">
                </div>
                <div class="modal-actions">
                    <button id="gen-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="gen-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#gen-model-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#gen-model-save-btn')?.addEventListener('click', async () => {
            const data = {
                model_id: modal.querySelector('#gen-model-id-input').value,
                display_name: modal.querySelector('#gen-model-name-input').value,
                provider: modal.querySelector('#gen-model-provider').value,
                api_key: modal.querySelector('#gen-model-api-key-input').value,
            };
            const baseUrl = modal.querySelector('#gen-model-base-url-input').value;
            if (baseUrl) data.base_url = baseUrl;
            await this.api.createGenerationModel(data);
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    }

    async showEmbeddingModelModal() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новая embedding-модель</h3>
                <div class="form-group">
                    <label for="emb-model-id-desc">ID модели:</label>
                    <span class="field-desc" id="emb-model-id-desc">Уникальный идентификатор embedding-модели (например, text-embedding-3-small).</span>
                    <input type="text" id="emb-model-id-input">
                </div>
                <div class="form-group">
                    <label for="emb-model-name-desc">Отображаемое имя:</label>
                    <span class="field-desc" id="emb-model-name-desc">Человекочитаемое название модели для отображения в интерфейсе.</span>
                    <input type="text" id="emb-model-name-input">
                </div>
                <div class="form-group">
                    <label for="emb-model-provider-desc">Провайдер:</label>
                    <span class="field-desc" id="emb-model-provider-desc">Поставщик модели: OpenAI или Ollama (локально).</span>
                    <select id="emb-model-provider">
                        <option value="openai_compatible">OpenAI</option>
                        <option value="ollama">Ollama</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="emb-model-api-key-desc">API Key (опционально):</label>
                    <span class="field-desc" id="emb-model-api-key-desc">Ключ доступа к API провайдера. Для Ollama можно оставить пустым.</span>
                    <input type="password" id="emb-model-api-key-input">
                </div>
                <div class="form-group">
                    <label for="emb-model-dimensions-desc">Размерность:</label>
                    <span class="field-desc" id="emb-model-dimensions-desc">Количество измерений вектора (например, 768, 1536). Уточните в документации модели.</span>
                    <input type="number" id="emb-model-dimensions-input" value="768">
                </div>
                <div class="form-group">
                    <label for="emb-model-base-url-desc">Base URL (опционально):</label>
                    <span class="field-desc" id="emb-model-base-url-desc">Адрес сервера API. Оставьте пустым для использования адреса по умолчанию.</span>
                    <input type="text" id="emb-model-base-url-input">
                </div>
                <div class="modal-actions">
                    <button id="emb-model-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="emb-model-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#emb-model-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#emb-model-save-btn')?.addEventListener('click', async () => {
            const data = {
                model_id: modal.querySelector('#emb-model-id-input').value,
                display_name: modal.querySelector('#emb-model-name-input').value,
                provider: modal.querySelector('#emb-model-provider').value,
                model_name: modal.querySelector('#emb-model-id-input').value,
                api_key: modal.querySelector('#emb-model-api-key-input').value || null,
                dimensions: parseInt(modal.querySelector('#emb-model-dimensions-input').value, 10),
                base_url: modal.querySelector('#emb-model-base-url-input').value || '',
            };
            await this.api.createEmbeddingModel(data);
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    }

    async showPipelineModal() {
        const domains = await this.api.getDomains();
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>Новый pipeline</h3>
                <div class="form-group">
                    <label for="pipeline-name-desc">Название:</label>
                    <span class="field-desc" id="pipeline-name-desc">Человекочитаемое название pipeline для отображения в интерфейсе.</span>
                    <input type="text" id="pipeline-name-input">
                </div>
                <div class="form-group">
                    <label for="pipeline-domain-desc">Домен:</label>
                    <span class="field-desc" id="pipeline-domain-desc">Домен, к которому будет привязан данный pipeline.</span>
                    <select id="pipeline-domain-select">
                        ${domains.map((d) => `<option value="${this.escapeHtml(d.domain_id)}">${this.escapeHtml(d.display_name)}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label for="pipeline-version-desc">Версия:</label>
                    <span class="field-desc" id="pipeline-version-desc">Версия pipeline в формате semver (например, 1.0, 2.1.0).</span>
                    <input type="text" id="pipeline-version-input" value="1.0">
                </div>
                <div class="form-group">
                    <label for="pipeline-steps-desc">Шаги (JSON):</label>
                    <span class="field-desc" id="pipeline-steps-desc">Массив шагов обработки запроса в формате JSON. Каждый шаг должен содержать type и параметры.</span>
                    <textarea id="pipeline-steps-input" class="json-editor">[]</textarea>
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
                    name: modal.querySelector('#pipeline-name-input').value,
                    domain_id: modal.querySelector('#pipeline-domain-select').value,
                    version: modal.querySelector('#pipeline-version-input').value,
                    steps: steps,
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
                    <label for="world-id-desc">ID мира:</label>
                    <span class="field-desc" id="world-id-desc">Уникальный идентификатор мира (например, dragonlance, forgotten_realms).</span>
                    <input type="text" id="world-id-input">
                </div>
                <div class="form-group">
                    <label for="world-name-desc">Название:</label>
                    <span class="field-desc" id="world-name-desc">Человекочитаемое название мира для отображения в интерфейсе.</span>
                    <input type="text" id="world-name-input">
                </div>
                <div class="form-group">
                    <label for="world-vault-desc">Vault:</label>
                    <span class="field-desc" id="world-vault-desc">Хранилище документов (vault), к которому привязывается данный мир.</span>
                    <select id="world-vault-select">
                        ${vaults.map((v) => `<option value="${this.escapeHtml(v.vault_id)}">${this.escapeHtml(v.display_name || v.vault_id)}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label for="world-path-desc">Path prefix:</label>
                    <span class="field-desc" id="world-path-desc">Префикс пути к папке с документами мира. Должен заканчиваться на '/' (например, worlds/dragonlance/).</span>
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
            // Автоматически добавляем завершающий слэш если его нет
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
    window.settingsManager = new SettingsManager(window.chatAPI);
});
