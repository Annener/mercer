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
        if (settingsBtn) settingsBtn.addEventListener('click', () => this.show());
        else console.warn('settings-btn not found');
        if (backBtn) backBtn.addEventListener('click', () => this.hide());
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
                'domains': () => this.renderDomainsTab(),
                'vaults': () => this.renderVaultsTab(),
                'gen-models': () => this.renderGenerationModelsTab(),
                'emb-models': () => this.renderEmbeddingModelsTab(),
                'params': () => this.renderParamsTab(),
                'pipelines': () => this.renderPipelinesTab(),
                'worlds': () => this.renderWorldsTab(),
            };
            container.innerHTML = renderers[tabId] ? await renderers[tabId]() : '<div class="placeholder"></div>';
            this.attachTabEventHandlers(tabId);
        } catch (error) {
            container.innerHTML = `<div class="error">${this.escapeHtml(error.message)}</div>`;
        }
    }

    async updateStatusBanner() {
        try {
            const status = await this.api.getSettingsStatus();
            const banner = document.getElementById('status-banner');
            if (!banner) return;
            const messages = [];
            if (!status.has_active_generation_model) messages.push('Не выбрана модель генерации. Чат недоступен.');
            if (!status.has_active_embedding_model) messages.push('Нет активной embedding-модели. RAG недоступен.');
            if (!status.has_vaults) messages.push('Нет ни одного vault. RAG недоступен.');
            if (!status.pdf_sidecar_available) messages.push('PDF Sidecar недоступен. Загрузка PDF работает через pdfminer.');
            banner.innerHTML = messages.map(message => `<div>${this.escapeHtml(message)}</div>`).join('');
            banner.classList.toggle('hidden', messages.length === 0);
            const chatInput = document.getElementById('message-input');
            if (chatInput) chatInput.disabled = !status.has_active_generation_model;
            if (!status.has_active_generation_model && chatInput) chatInput.placeholder = 'Сначала настройте модель генерации';
        } catch (error) {
            console.error('Failed to update status banner:', error);
        }
    }

    async renderDomainsTab() {
        const resp = await this.api.getDomains();
        const domains = Array.isArray(resp) ? resp : (resp.domains || []);
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-domain">+ Новый домен</button></div>`;
        if (!domains.length) return toolbar + `<div class="empty-state">Нет доменов</div>`;
        return toolbar + `<div class="settings-grid">${domains.map(domain => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(domain.display_name)}</h3>
                    <p>${this.escapeHtml(domain.domain_id)}</p>
                </div>
                <div class="settings-actions">
                    <button class="btn btn-sm btn-secondary" data-action="edit-domain" data-id="${this.escapeHtml(domain.domain_id)}">Изменить</button>
                    <button class="btn btn-sm btn-secondary" data-action="edit-prompts" data-id="${this.escapeHtml(domain.domain_id)}">Промпты</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-domain" data-id="${this.escapeHtml(domain.domain_id)}"${domain.is_system ? ' disabled' : ''}>Удалить</button>
                </div>
                <div>
                    <span class="badge ${domain.enabled ? 'ok' : 'muted'}">${domain.enabled ? 'включён' : 'выключен'}</span>
                </div>
            </article>`).join('')}</div>`;
    }

    async renderVaultsTab() {
        let vaults = await this.api.getSettingsVaults();
        if (!Array.isArray(vaults)) vaults = [];
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-vault">+ Новый vault</button></div>`;
        if (vaults.length === 0) return toolbar + `<div class="empty-state">Vault'ов нет</div>`;
        return toolbar + `<div class="settings-grid">${vaults.map(vault => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(vault.display_name || vault.vault_id)}</h3>
                    <p>/data/vaults/${this.escapeHtml(vault.vault_id)}</p>
                </div>
                <div class="settings-actions">
                    <button class="btn btn-sm btn-secondary" data-action="edit-vault" data-id="${this.escapeHtml(vault.vault_id)}">Изменить</button>
                    <button class="btn btn-sm btn-secondary" data-action="toggle-vault" data-id="${this.escapeHtml(vault.vault_id)}">${vault.enabled ? 'Выключить' : 'Включить'}</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-vault" data-id="${this.escapeHtml(vault.vault_id)}">Удалить</button>
                </div>
                <div>
                    <span class="badge ${vault.enabled ? 'ok' : 'muted'}">${this.escapeHtml(vault.binding_status)}</span>
                </div>
            </article>`).join('')}</div>`;
    }

    async renderGenerationModelsTab() {
        const models = await this.api.getGenerationModels();
        return this.renderModelList('gen', Array.isArray(models) ? models : []);
    }

    async renderEmbeddingModelsTab() {
        const [models, vaults] = await Promise.all([this.api.getEmbeddingModels(), this.api.getSettingsVaults()]);
        const modelsArr = Array.isArray(models) ? models : [];
        const vaultsArr = Array.isArray(vaults) ? vaults : [];
        const enriched = modelsArr.map(model => ({
            ...model,
            connected_vaults: vaultsArr.filter(vault => vault.embedding_model_id === model.model_id),
        }));
        return this.renderModelList('emb', enriched, 'embedding-');
    }

    renderModelList(kind, models, label = '') {
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-${kind}">+ Новая ${label}модель</button></div>`;
        if (!models || models.length === 0) return toolbar + `<div class="empty-state">Нет моделей</div>`;
        return toolbar + `<div class="settings-grid">${models.map(model => {
            let badgeClass = 'muted', badgeText = 'ready';
            if (model.is_active) { badgeClass = 'ok'; badgeText = 'active'; }
            else if (model.enabled === false) { badgeClass = 'muted'; badgeText = 'disabled'; }
            else if (kind === 'emb') { badgeClass = 'ok'; badgeText = 'ready'; }
            return `<article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(model.display_name || model.model_id)}</h3>
                    <p>${this.escapeHtml(model.provider || '')}${model.dimensions ? ` · ${model.dimensions}` : ''}</p>
                    ${model.connected_vaults ? `<p>${model.connected_vaults.length} vault'ов</p>` : ''}
                </div>
                <div class="settings-actions">
                    <button class="btn btn-sm btn-secondary" data-action="edit-${kind}" data-id="${this.escapeHtml(model.model_id)}">Изменить</button>
                    <button class="btn btn-sm btn-secondary" data-action="check-${kind}" data-id="${this.escapeHtml(model.model_id)}">Проверить</button>
                    ${kind === 'gen' ? `<button class="btn btn-sm btn-secondary" data-action="activate-gen" data-id="${this.escapeHtml(model.model_id)}"${model.is_active ? ' disabled' : ''}>Активировать</button>` : ''}
                    <button class="btn btn-sm btn-danger" data-action="delete-${kind}" data-id="${this.escapeHtml(model.model_id)}"${(kind === 'gen' && model.is_active) || (model.connected_vaults && model.connected_vaults.length) ? ' disabled' : ''}>Удалить</button>
                </div>
                <div><span class="badge ${badgeClass}">${badgeText}</span></div>
            </article>`;
        }).join('')}</div>`;
    }

    getParamType(key) {
        const boolKeys = ['retrieval.enabled', 'reranker.enabled', 'chat.stream_answers', 'chat.auto_title', 'chunking.entity_aware_mode', 'pdf_sidecar.fallback_to_pdfminer'];
        return boolKeys.includes(key) ? 'bool' : 'string';
    }

    async renderParamsTab() {
        const params = await this.api.getSettingsParams();
        const sortedKeys = Object.keys(params).sort();
        const descriptions = {
            'retrieval.enabled':              { label: 'RAG включён', desc: 'Включает поиск по базе знаний при ответе. Если выключить — ИИ отвечает только из своей памяти.' },
            'retrieval.top_k':                { label: 'Top-K результатов', desc: 'Сколько фрагментов документов передавать ИИ при каждом запросе. Рекомендуется 5–15.' },
            'retrieval.reranker_enabled':     { label: 'Reranker включён', desc: 'Включает дополнительную модель переранжирования результатов поиска.' },
            'chunking.chunk_size':            { label: 'Размер чанка', desc: 'Максимальное количество символов в одном фрагменте документа при индексации. Рекомендуется 1000–3000.' },
            'chunking.overlap':               { label: 'Перекрытие чанков', desc: 'Сколько символов повторяется между соседними чанками. Рекомендуется 32–128.' },
            'chunking.entity_aware_mode':     { label: 'Режим осведомлённости об объектах', desc: 'При нарезке учитывает границы сущностей (персонажи, места). Улучшает качество для D&D текстов.' },
            'chat.max_clarification_turns':   { label: 'Макс. уточняющих вопросов', desc: 'Сколько раз ИИ может переспросить перед ответом. 0 — отвечает сразу.' },
            'chat.stream_answers':            { label: 'Стриминг ответов', desc: 'Ответ появляется постепенно, слово за словом. Если выключить — появится весь сразу.' },
            'chat.auto_title':                { label: 'Авто-название чата', desc: 'Автоматически придумывает название для нового чата.' },
            'reranker.enabled':               { label: 'Reranker активен', desc: 'Глобальный переключатель reranker-модели.' },
            'reranker.provider':              { label: 'Провайдер reranker', desc: 'Тип сервиса reranker. Поддерживается: openai_compatible.' },
            'reranker.base_url':              { label: 'URL reranker API', desc: 'Адрес сервера reranker. Например: http://localhost:8080.' },
            'reranker.model_name':            { label: 'Модель reranker', desc: 'Название модели reranker на сервере.' },
            'pdf_sidecar.url':                { label: 'URL PDF-Sidecar', desc: 'Адрес вспомогательного сервиса для извлечения текста из PDF. Например: http://host.docker.internal:8765.' },
            'pdf_sidecar.timeout_seconds':    { label: 'Таймаут PDF-Sidecar (сек)', desc: 'Сколько секунд ждать ответа от PDF-Sidecar.' },
            'pdf_sidecar.fallback_to_pdfminer': { label: 'Fallback на PDF-miner', desc: 'Если PDF-Sidecar недоступен — использовать встроенный pdfminer.' },
        };
        return `
            <div class="settings-toolbar">
                <button class="btn btn-secondary" data-action="reset-params">Сбросить все параметры</button>
            </div>
            <div class="settings-params-fullwidth">
                ${sortedKeys.map(key => {
                    const isBool = this.getParamType(key) === 'bool';
                    const currentValue = params[key];
                    const info = descriptions[key] || { label: key, desc: '' };
                    const inputHtml = isBool
                        ? `<input type="checkbox" data-param="${this.escapeHtml(key)}" ${(currentValue === true || currentValue === 'true') ? 'checked' : ''}>`
                        : `<input data-param="${this.escapeHtml(key)}" value="${this.escapeHtml(currentValue ?? '')}" style="width:100%; max-width:340px; box-sizing:border-box;">`;
                    return `
                        <div class="settings-param-row">
                            <div class="settings-param-info">
                                <strong>${this.escapeHtml(info.label)}</strong>
                                <span class="settings-param-desc">${this.escapeHtml(info.desc)}</span>
                                <span class="settings-param-key">${this.escapeHtml(key)}</span>
                            </div>
                            <div class="settings-param-control">
                                ${inputHtml}
                                <button class="btn btn-sm btn-secondary" data-action="default-param" data-id="${this.escapeHtml(key)}">По умолчанию</button>
                            </div>
                        </div>`;
                }).join('')}
            </div>`;
    }

    async renderPipelinesTab() {
        let pipelines = await this.api.getPipelines();
        if (!Array.isArray(pipelines)) pipelines = [];
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-pipeline">+ Новый pipeline</button></div>`;
        if (pipelines.length === 0) return toolbar + `<div class="empty-state">Pipeline'ов нет</div>`;
        return toolbar + `<div class="settings-grid">${pipelines.map(pipeline => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(pipeline.name)}</h3>
                    <p>${this.escapeHtml(pipeline.pipeline_id)} · ${this.escapeHtml(pipeline.version)} · ${pipeline.steps?.length || 0} шаг.</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(pipeline.id)}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-pipeline" data-id="${this.escapeHtml(pipeline.id)}">
                            ✏️ Редактировать
                        </button>
                        <button class="card-menu-item" data-action="activate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">
                            ▶️ Активировать
                        </button>
                        <button class="card-menu-item" data-action="deactivate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">
                            ⏸️ Деактивировать
                        </button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-pipeline" data-id="${this.escapeHtml(pipeline.id)}">
                            🗑️ Удалить
                        </button>
                    </div>
                </div>
                <div><span class="badge ${pipeline.is_active ? 'ok' : 'muted'}">${pipeline.is_active ? 'active' : 'inactive'}</span></div>
            </article>`).join('')}</div>`;
    }

    async renderWorldsTab() {
        const [vaults, worlds] = await Promise.all([this.api.getSettingsVaults(), this.api.getWorlds()]);
        const vaultsArr = Array.isArray(vaults) ? vaults : [];
        const worldsArr = Array.isArray(worlds) ? worlds : [];
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-world">+ Новый мир</button></div>`;
        if (worldsArr.length === 0) return toolbar + `<div class="empty-state">Миров нет</div>`;
        return toolbar + `<div class="settings-grid">${worldsArr.map(world => `
            <article class="settings-card world-card">
                <div>
                    <h3>${this.escapeHtml(world.name)}</h3>
                    <p>${this.escapeHtml(world.world_id)} · ${this.escapeHtml(world.path_prefix)}</p>
                    <p>${this.escapeHtml((vaultsArr.find(vault => vault.vault_id === world.vault_id) || {}).display_name || world.vault_id)}</p>
                </div>
                <div class="settings-actions">
                    <button class="btn btn-sm btn-secondary" data-action="toggle-world" data-id="${this.escapeHtml(world.world_id)}" data-active="${world.is_active ? '1' : '0'}">${world.is_active ? 'Выключить' : 'Включить'}</button>
                    <button class="btn btn-sm btn-secondary" data-action="edit-world" data-id="${world.world_id}">Редактировать</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-world" data-id="${world.world_id}" data-name="${world.name}">Удалить</button>
                </div>
                <div><span class="badge ${world.is_active ? 'ok' : 'muted'}">${world.is_active ? 'active' : 'off'}</span></div>
            </article>`).join('')}</div>`;
    }

    attachTabEventHandlers(tabId) {
        const content = document.getElementById('settings-content');
    
        // --- Dropdown меню ---
        content?.querySelectorAll('.card-menu-toggle').forEach((button) => {
            button.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault(); // ← добавить
                const menu = button.nextElementSibling;
                const isOpen = menu.classList.contains('open');
                content.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
                if (!isOpen) menu.classList.add('open');
            });
        });
    
        content?.querySelectorAll('.card-menu').forEach((menu) => {
            menu.addEventListener('click', (e) => e.stopPropagation());
        });
    
        if (this._closeMenusHandler) {
            document.removeEventListener('click', this._closeMenusHandler);
        }
        this._closeMenusHandler = () => {
            content?.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
        };
        document.addEventListener('click', this._closeMenusHandler);
    
        // --- Обычные action-обработчики (ИСКЛЮЧАЕМ card-menu-item) ---
        content?.querySelectorAll('[data-action]:not(.card-menu-item)').forEach((button) => {
            button.addEventListener('click', () => this.handleAction(button.dataset.action, button.dataset.id, button));
        });
    
        // --- card-menu-item обрабатываются отдельно ---
        content?.querySelectorAll('.card-menu-item[data-action]').forEach((button) => {
            button.addEventListener('click', (e) => {
                e.stopPropagation();
                content.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
                this.handleAction(button.dataset.action, button.dataset.id, button);
            });
        });
    
        content?.querySelectorAll('[data-param]').forEach((input) => {
            const saveParam = async () => {
                let value = input.type === 'checkbox' ? input.checked : input.value;
                await this.api.updateSettingsParam(input.dataset.param, value);
                if (input.dataset.param === 'pdf_sidecar.url') await this.updateStatusBanner();
            };
            if (input.type === 'checkbox') input.addEventListener('change', saveParam);
            else input.addEventListener('blur', saveParam);
        });
    }

    async handleAction(action, id, button) {
        try {
            if (action === 'new-domain') await this.showDomainModal();
            if (action === 'edit-domain') await this.showDomainModal(id);
            if (action === 'edit-prompts') await this.showPromptsModal(id);
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
            if (action === 'edit-pipeline') await this.showPipelineEditModal(id);
            if (action === 'default-param') await this.api.updateSettingsParam(id, SETTINGS_DEFAULTS[id] ?? '');
            if (action === 'new-pipeline') await this.showPipelineModal();
            if (action === 'activate-pipeline') await this.api.activatePipeline(id);
            if (action === 'deactivate-pipeline') await this.api.deactivatePipeline(id);
            if (action === 'delete-pipeline' && confirm('Удалить pipeline? Это действие необратимо.')) {
                await this.api.deletePipeline(id);
            }
            if (action === 'new-world') await this.showWorldModal();
            if (action === 'toggle-world') await this.api.updateWorld(id, { is_active: button.dataset.active !== '1' });
            if (action === 'edit-world') await this.showWorldModal(id);
            if (action === 'delete-world' && confirm(`Удалить мир «${button.dataset.name}»? Это также удалит все связанные кампании.`)) await this.api.deleteWorld(id);
            await this.loadTab(this.currentTab);
            await this.updateStatusBanner();
        } catch (error) {
            alert(error.message);
        }
    }

    async showPipelineEditModal(pipelineUuid) {
        const all = await this.api.getPipelines();
        const list = Array.isArray(all) ? all : (all.pipelines || []);
        const pipeline = list.find(p => p.id === pipelineUuid);
        if (!pipeline) { alert('Pipeline не найден'); return; }
        await window.PipelineBuilder.openEdit(this.api, pipeline, () => this.loadTab(this.currentTab));
    }

    async showDomainModal(domainId = null) {
        let domain = null;
        if (domainId) {
            const resp = await this.api.getDomains();
            const domains = Array.isArray(resp) ? resp : (resp.domains || []);
            domain = domains.find(d => d.domain_id === domainId) || null;
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${domain ? 'Редактировать домен' : 'Новый домен'}</h3>
                <div class="form-group">
                    <label>ID домена</label>
                    <input type="text" id="domain-id-input" value="${this.escapeHtml(domain?.domain_id || '')}"
                        ${domain ? 'disabled' : ''} pattern="[a-z0-9_]{3,32}"
                        title="3-32 символа, только a-z, 0-9 и _">
                </div>
                <div class="form-group">
                    <label>Отображаемое название</label>
                    <input type="text" id="domain-name-input" value="${this.escapeHtml(domain?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Описание</label>
                    <textarea id="domain-desc-input">${this.escapeHtml(domain?.description || '')}</textarea>
                </div>
                <div class="domain-enabled-row">
                    <div class="domain-enabled-label">
                        <span class="domain-enabled-title">Домен активен</span>
                        <span class="domain-enabled-hint">Если выключить — домен не будет отображаться в списке при создании чата.</span>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" id="domain-enabled-input" ${domain?.enabled !== false ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
                <div class="modal-actions">
                    <button id="domain-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="domain-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
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
                enabled: modal.querySelector('#domain-enabled-input').checked
            };
            if (domainId) await this.api.updateDomain(domainId, data);
            else { data.domain_id = domainIdValue; await this.api.createDomain(data); }
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    }

    async showPromptsModal(domainId) {
        const PROMPT_DESCRIPTIONS = {
            system: {
                title: 'Системный промпт',
                desc: 'Главная инструкция для ИИ — задаёт роль, стиль ответов и правила поведения.',
                vars: '{{domain_id}}, {{domain_name}}',
            },
            clarification: {
                title: 'Промпт уточнения',
                desc: 'Используется когда ИИ решает задать уточняющий вопрос перед ответом.',
                vars: '{{question}}, {{clarification_fields}}',
            },
            planner: {
                title: 'Промпт планировщика',
                desc: 'Инструкция для этапа планирования — ИИ решает какие источники знаний использовать.',
                vars: '{{question}}, {{available_vaults}}, {{domain_name}}',
            },
            pipeline_router: {
                title: 'Роутер пайплайна',
                desc: 'Определяет какой пайплайн обработки выбрать для входящего запроса.',
                vars: '{{question}}, {{pipelines}}',
            },
        };
        try {
            const prompts = await this.api.getDomainPrompts(domainId);
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content" style="max-width:min(95vw,1200px); max-height:90vh; overflow-y:auto;">
                    <h3>Промпты домена: ${this.escapeHtml(domainId)}</h3>
                    ${Object.entries(prompts).map(([type, content]) => {
                        const info = PROMPT_DESCRIPTIONS[type] || { title: type, desc: '', vars: '' };
                        return `
                            <div class="prompt-block" style="margin-bottom:24px;">
                                <div style="margin-bottom:8px;">
                                    <strong style="font-size:1.05em;">${this.escapeHtml(info.title)}</strong>
                                    <p style="font-size:0.9em;color:#666;margin:4px 0 2px;">${this.escapeHtml(info.desc)}</p>
                                    ${info.vars ? `<p style="font-size:0.8em;color:#999;font-family:monospace;">Переменные: ${this.escapeHtml(info.vars)}</p>` : ''}
                                </div>
                                <textarea class="prompt-editor" data-type="${this.escapeHtml(type)}" rows="10"
                                    style="width:100%;box-sizing:border-box;font-size:13px;">${this.escapeHtml(content)}</textarea>
                            </div>`;
                    }).join('')}
                    <div class="modal-actions">
                        <button id="prompts-save-btn" class="btn btn-primary">Сохранить все промпты</button>
                        <button id="prompts-cancel-btn" class="btn btn-secondary">Отмена</button>
                    </div>
                </div>`;
            document.body.appendChild(modal);
            modal.querySelector('#prompts-cancel-btn').addEventListener('click', () => modal.remove());
            modal.querySelector('#prompts-save-btn').addEventListener('click', async () => {
                const textareas = modal.querySelectorAll('.prompt-editor');
                for (const ta of textareas) {
                    await this.api.updateDomainPrompt(domainId, ta.dataset.type, ta.value);
                }
                alert('Промпты успешно сохранены!');
                modal.remove();
            });
        } catch (err) {
            alert('Ошибка загрузки промптов: ' + err.message);
        }
    }

    async showVaultModal(vaultId = null) {
        try {
            let vault = null;
            if (vaultId) {
                const vaultsList = await this.api.getSettingsVaults();
                vault = (Array.isArray(vaultsList) ? vaultsList : []).find(v => v.vault_id === vaultId);
            }
            const resp = await this.api.getDomains();
            const allDomains = Array.isArray(resp) ? resp : (resp.domains || []);
            const domains = allDomains.filter(d => d.enabled !== false);
            const embModels = await this.api.getEmbeddingModels();
            const embModelsArr = Array.isArray(embModels) ? embModels : [];
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <h3>${vault ? 'Редактировать vault' : 'Новый vault'}</h3>
                    <div class="form-group">
                        <label>ID vault</label>
                        <input type="text" id="vault-id-input" value="${this.escapeHtml(vault?.vault_id || '')}" ${vault ? 'disabled' : ''}>
                    </div>
                    <div class="form-group">
                        <label>Название</label>
                        <input type="text" id="vault-name-input" value="${this.escapeHtml(vault?.display_name || '')}">
                    </div>
                    <div class="form-group">
                        <label>Домен</label>
                        <select id="vault-domain-select">
                            ${domains.map(d => `<option value="${this.escapeHtml(d.domain_id)}" ${vault?.domain_id === d.domain_id ? 'selected' : ''}>${this.escapeHtml(d.display_name || d.domain_id)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Embedding-модель</label>
                        <select id="vault-emb-model">
                            <option value="">— не выбрана —</option>
                            ${embModelsArr.map(m => `<option value="${this.escapeHtml(m.model_id)}" ${vault?.embedding_model_id === m.model_id ? 'selected' : ''}>${this.escapeHtml(m.display_name || m.model_id)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="modal-actions">
                        <button id="vault-save-btn" class="btn btn-primary">Сохранить</button>
                        <button id="vault-cancel-btn" class="btn btn-secondary">Отмена</button>
                    </div>
                </div>`;
            document.body.appendChild(modal);
            modal.querySelector('#vault-cancel-btn')?.addEventListener('click', () => modal.remove());
            modal.querySelector('#vault-save-btn')?.addEventListener('click', async () => {
                const data = {
                    display_name: modal.querySelector('#vault-name-input').value,
                    domain_id: modal.querySelector('#vault-domain-select').value,
                    embedding_model_id: modal.querySelector('#vault-emb-model').value || null,
                };
                if (vaultId) await this.api.updateVault(vaultId, data);
                else { data.vault_id = modal.querySelector('#vault-id-input').value; await this.api.createVault(data); }
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
    }

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
                await this.loadTab(this.currentTab);
            } catch (err) { alert('Ошибка: ' + err.message); }
        });
    }

    async showPipelineModal() {
        await window.PipelineBuilder.openCreate(this.api, () => this.loadTab(this.currentTab));
    }

    async showWorldModal(worldId = null) {
        const vaults = await this.api.getSettingsVaults();
        const vaultsArr = Array.isArray(vaults) ? vaults : [];
    
        // Если редактирование — подгружаем текущие данные
        let existing = null;
        if (worldId) {
            const worlds = await this.api.getWorlds();
            existing = (Array.isArray(worlds) ? worlds : []).find(w => w.world_id === worldId) || null;
        }
    
        const isEdit = existing !== null;
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${isEdit ? 'Редактировать мир' : 'Новый мир'}</h3>
                ${!isEdit ? `
                <div class="form-group">
                    <label>ID мира</label>
                    <input type="text" id="world-id-input" value="">
                </div>` : ''}
                <div class="form-group">
                    <label>Название</label>
                    <input type="text" id="world-name-input" value="${this.escapeHtml(existing?.name || '')}">
                </div>
                ${!isEdit ? `
                <div class="form-group">
                    <label>Vault</label>
                    <select id="world-vault-select">
                        ${vaultsArr.map(v => `<option value="${this.escapeHtml(v.vault_id)}">${this.escapeHtml(v.display_name || v.vault_id)}</option>`).join('')}
                    </select>
                </div>` : ''}
                <div class="form-group">
                    <label>Path prefix</label>
                    <input type="text" id="world-path-input" placeholder="worlds/myworld/" value="${this.escapeHtml(existing?.path_prefix || '')}">
                </div>
                <div class="form-group">
                    <label>Описание</label>
                    <input type="text" id="world-desc-input" value="${this.escapeHtml(existing?.description || '')}">
                </div>
                <div class="modal-actions">
                    <button id="world-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="world-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.querySelector('#world-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#world-save-btn')?.addEventListener('click', async () => {
            let pathPrefix = modal.querySelector('#world-path-input').value;
            if (pathPrefix && !pathPrefix.endsWith('/')) pathPrefix += '/';
    
            if (isEdit) {
                const data = {
                    name: modal.querySelector('#world-name-input').value,
                    path_prefix: pathPrefix,
                    description: modal.querySelector('#world-desc-input').value || null,
                };
                await this.api.updateWorld(worldId, data);
            } else {
                const data = {
                    world_id: modal.querySelector('#world-id-input').value,
                    name: modal.querySelector('#world-name-input').value,
                    vault_id: modal.querySelector('#world-vault-select').value,
                    path_prefix: pathPrefix,
                    description: modal.querySelector('#world-desc-input').value || null,
                };
                await this.api.createWorld(data);
            }
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
    if (!window.chatAPI) { console.error('chatAPI not available'); return; }
    window.settingsManager = new SettingsManager(window.chatAPI);
});