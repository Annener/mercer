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
        return `
            <div class="settings-toolbar"><button class="btn btn-secondary" data-action="reset-params">Сбросить все к дефолтам</button></div>
            <div class="settings-param-list">
                ${Object.entries(params).map(([key, value]) => `
                    <label class="settings-param-row">
                        <span>${this.escapeHtml(key)}</span>
                        <input data-param="${this.escapeHtml(key)}" value="${this.escapeHtml(value ?? '')}">
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
            if (action === 'delete-domain' && confirm('Удалить домен?')) await this.api.deleteDomain(id);
            if (action === 'toggle-vault') await this.api.toggleVault(id);
            if (action === 'delete-vault' && confirm('Удалить vault и его векторы?')) await this.api.deleteVault(id);
            if (action === 'check-gen') alert(JSON.stringify(await this.api.checkGenerationModel(id), null, 2));
            if (action === 'activate-gen') await this.api.activateGenerationModel(id);
            if (action === 'delete-gen' && confirm('Удалить модель?')) await this.api.deleteGenerationModel(id);
            if (action === 'check-emb') alert(JSON.stringify(await this.api.checkEmbeddingModel(id), null, 2));
            if (action === 'delete-emb' && confirm('Удалить embedding-модель?')) await this.api.deleteEmbeddingModel(id);
            if (action === 'reset-params' && confirm('Сбросить все параметры?')) await this.api.resetSettingsParams();
            if (action === 'activate-pipeline') await this.api.activatePipeline(id);
            if (action === 'delete-pipeline') await this.api.deletePipeline(id);
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
}

document.addEventListener('DOMContentLoaded', () => {
    window.settingsManager = new SettingsManager(window.chatAPI);
});
