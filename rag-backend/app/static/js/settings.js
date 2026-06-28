class SettingsManager {
    constructor() {
        this.api = window.chatAPI;
        this.currentTab = 'domains';
        this._tabContent = null;
        this._bound = false;
    }

    // setup() вызывается ОДИН раз — навешивает обработчики
    setup() {
        if (this._bound) return;
        this._bound = true;
        this._tabContent = document.getElementById('settings-content');
        this._bindTabNav();
        this._bindActions();
    }

    // init() вызывается при каждом открытии — только загружает активный таб
    async init() {
        this._tabContent = document.getElementById('settings-content');
        await this.loadTab(this.currentTab);
    }

    _bindTabNav() {
        const nav = document.querySelector('.settings-tabs');
        if (!nav) return;
        nav.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-tab]');
            if (!btn) return;
            nav.querySelectorAll('[data-tab]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            this.currentTab = btn.dataset.tab;
            await this.loadTab(this.currentTab);
        });
    }

    async loadTab(tab) {
        if (!this._tabContent) return;
        this._tabContent.innerHTML = '<div class="settings-loading">Загрузка…</div>';
        try {
            let html = '';
            switch (tab) {
                case 'gen-models':    html = await this.renderGenerationModelsTab(); break;
                case 'emb-models':    html = await this.renderEmbeddingModelsTab(); break;
                case 'rerank-models': html = await this.renderRerankModelsTab(); break;
                case 'models':        html = await this.renderModelsTab(); break;
                case 'vaults':        html = await this.renderVaultsTab(); break;
                case 'domains':       html = await this.renderDomainsTab(); break;
                case 'campaigns':     html = await this.renderCampaignsTab(); break;
                case 'pipelines':     html = await this.renderPipelinesTab(); break;
                case 'params':        html = await this.renderParamsTab(); break;
                case 'documents':     html = await this.renderDocumentsTab(); break;
                default:              html = '<p>Вкладка не найдена</p>';
            }
            this._tabContent.innerHTML = html;
            this._afterTabRender(tab);
        } catch (err) {
            console.error('loadTab error:', err);
            this._tabContent.innerHTML = `<div class="settings-error">Ошибка загрузки: ${err.message}</div>`;
        }
    }

    _afterTabRender(tab) {
        if (tab === 'documents') {
            this._initDocumentsTab();
        }
    }

    _bindActions() {
        if (!this._tabContent) return;
        this._tabContent.addEventListener('click', async (e) => {
            // ── Card menu toggle ──────────────────────────────────────────────
            const menuToggle = e.target.closest('.card-menu-toggle');
            if (menuToggle) {
                e.stopPropagation();
                const container = menuToggle.closest('.card-menu-container');
                const menu = container?.querySelector('.card-menu');
                if (menu) {
                    const isOpen = menu.classList.contains('open');
                    this._tabContent.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
                    if (!isOpen) menu.classList.add('open');
                }
                return;
            }

            // ── Action buttons ────────────────────────────────────────────────
            const btn = e.target.closest('[data-action]');
            if (!btn) return;

            const action = btn.dataset.action;
            const id = btn.dataset.id || null;

            this._tabContent.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));

            const tab = this.currentTab;
            try {
                switch (tab) {
                    case 'gen-models':    await this.handleGenModelsAction(action, id, btn); break;
                    case 'emb-models':    await this.handleEmbModelsAction(action, id, btn); break;
                    case 'rerank-models': await this.handleRerankModelsAction(action, id, btn); break;
                    case 'models':        await this.handleModelsAction(action, id, btn); break;
                    case 'vaults':        await this.handleVaultsAction(action, id, btn); break;
                    case 'domains':       await this.handleDomainsAction(action, id, btn); break;
                    case 'campaigns':     await this.handleCampaignsAction(action, id, btn); break;
                    case 'pipelines':     await this.handlePipelinesAction(action, id, btn); break;
                    case 'params':        await this.handleParamsAction(action, id, btn); break;
                    case 'documents':     await this.handleDocumentsAction(action, btn); break;
                }
            } catch (err) {
                console.error('Action error:', err);
            }
        });

        document.addEventListener('click', () => {
            if (this._tabContent) {
                this._tabContent.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
            }
        });
    }

    // ─── Params ────────────────────────────────────────────────────────────────────────────

    async handleParamsAction(action, id, btn) {
        if (action === 'save-params') {
            const inputs = this._tabContent.querySelectorAll('[data-key]');
            const updates = {};
            inputs.forEach(input => {
                const key = input.dataset.key;
                updates[key] = input.type === 'checkbox' ? input.checked : input.value;
            });
            try {
                await this.api.updateConfig(updates);
                await this.loadTab('params');
            } catch (e) { alert('Ошибка сохранения: ' + e.message); }
        }
    }

    // ─── Domains ────────────────────────────────────────────────────────────────────────────

    async handleDomainsAction(action, id, btn) {
        if (action === 'new-domain') {
            await this.showDomainModal();
        } else if (action === 'edit-domain') {
            await this.showDomainModal(id);
        } else if (action === 'delete-domain') {
            if (!confirm('Удалить домен?')) return;
            try {
                await this.api.deleteDomain(id);
                await this.loadTab('domains');
            } catch (e) { alert('Ошибка: ' + e.message); }
        }
    }

    // ─── Campaigns ───────────────────────────────────────────────────────────────────────

    async handleCampaignsAction(action, id, btn) {
        if (action === 'new-campaign') {
            await this.showCampaignModal();
        } else if (action === 'edit-campaign') {
            await this.showCampaignModal(id);
        } else if (action === 'delete-campaign') {
            if (!confirm('Удалить кампанию?')) return;
            try {
                await this.api.deleteCampaign(id);
                await this.loadTab('campaigns');
            } catch (e) { alert('Ошибка: ' + e.message); }
        }
    }

    // ─── Pipelines ────────────────────────────────────────────────────────────────────────

    async handlePipelinesAction(action, id, btn) {
        if (action === 'new-pipeline') {
            await this.showPipelineModal();
        } else if (action === 'edit-pipeline') {
            await this.showPipelineModal(id);
        } else if (action === 'activate-pipeline') {
            try {
                await this.api.activatePipeline(id);
                await this.loadTab('pipelines');
            } catch (e) { alert('Ошибка активации: ' + e.message); }
        } else if (action === 'deactivate-pipeline') {
            try {
                await this.api.deactivatePipeline(id);
                await this.loadTab('pipelines');
            } catch (e) { alert('Ошибка деактивации: ' + e.message); }
        } else if (action === 'delete-pipeline') {
            if (!confirm('Удалить пайплайн?')) return;
            try {
                await this.api.deletePipeline(id);
                await this.loadTab('pipelines');
            } catch (e) { alert('Ошибка: ' + e.message); }
        }
    }

    // ─── Generation Models ──────────────────────────────────────────────────────────────────

    async handleGenModelsAction(action, id, btn) {
        if (action === 'new-gen') {
            await this.showGenerationModelModal();
        } else if (action === 'edit-gen') {
            await this.showGenerationModelModal(id);
        } else if (action === 'delete-gen') {
            if (!confirm('Удалить модель?')) return;
            try {
                await this.api.deleteGenerationModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'activate-gen') {
            try {
                await this.api.setActiveGenerationModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка активации: ' + e.message); }
        } else if (action === 'deactivate-gen') {
            try {
                await this.api.deactivateGenerationModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка деактивации: ' + e.message); }
        } else if (action === 'toggle-gen') {
            try {
                await this.api.toggleGenerationModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка переключения: ' + e.message); }
        } else if (action === 'check-gen') {
            try {
                const result = await this.api.checkGenerationModel(id);
                alert(result.ok
                    ? `✅ Модель доступна (${result.latency_ms} мс)`
                    : `❌ Ошибка: ${result.error}`);
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

    // ─── Embedding Models ──────────────────────────────────────────────────────────────────

    async handleEmbModelsAction(action, id, btn) {
        if (action === 'new-emb') {
            await this.showEmbeddingModelModal();
        } else if (action === 'edit-emb') {
            await this.showEmbeddingModelModal(id);
        } else if (action === 'delete-emb') {
            if (!confirm('Удалить модель?')) return;
            try {
                await this.api.deleteEmbeddingModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'check-emb') {
            try {
                const result = await this.api.checkEmbeddingModel(id);
                alert(result.ok
                    ? `✅ Модель доступна, размерность: ${result.dimensions} (${result.latency_ms} мс)`
                    : `❌ Ошибка: ${result.error}`);
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

    // ─── Rerank Models ──────────────────────────────────────────────────────────────────────

    async handleRerankModelsAction(action, id, btn) {
        if (action === 'new-rerank') {
            await this.showRerankModelModal();
        } else if (action === 'edit-rerank') {
            await this.showRerankModelModal(id);
        } else if (action === 'delete-rerank') {
            if (!confirm('Удалить модель?')) return;
            try {
                await this.api.deleteRerankModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'activate-rerank') {
            try {
                await this.api.setActiveRerankModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка активации: ' + e.message); }
        } else if (action === 'deactivate-rerank') {
            try {
                await this.api.deactivateRerankModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка деактивации: ' + e.message); }
        } else if (action === 'toggle-rerank') {
            try {
                await this.api.toggleRerankModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка переключения: ' + e.message); }
        } else if (action === 'check-rerank') {
            try {
                const result = await this.api.checkRerankModel(id);
                alert(result.ok
                    ? `✅ Reranker доступен (${result.latency_ms} мс)`
                    : `❌ Ошибка: ${result.error}`);
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

    // ─── Combined Models tab ───────────────────────────────────────────────────────────────

    async handleModelsAction(action, id, btn) {
        const type = btn?.dataset.modelType;
        if (!type) return;
        if (type === 'gen')    return this.handleGenModelsAction(action, id, btn);
        if (type === 'emb')    return this.handleEmbModelsAction(action, id, btn);
        if (type === 'rerank') return this.handleRerankModelsAction(action, id, btn);
    }

    // ─── Vaults ────────────────────────────────────────────────────────────────────────────

    async handleVaultsAction(action, id, btn) {
        if (action === 'new-vault') {
            await this.showVaultModal();
        } else if (action === 'edit-vault') {
            await this.showVaultModal(id);
        } else if (action === 'delete-vault') {
            if (!confirm('Удалить хранилище?')) return;
            try {
                await this.api.deleteVault(id);
                await this.loadTab('vaults');
            } catch (e) { alert('Ошибка: ' + e.message); }
        }
    }

    // ─── Documents ────────────────────────────────────────────────────────────────────────

    /**
     * Вызывается из _afterTabRender() сразу после того, как renderDocumentsTab()
     * вставил HTML-скелет в DOM. Делегирует загрузку данных в DocumentsTabMixin.
     */
    _initDocumentsTab() {
        if (typeof this.loadDocumentsData !== 'function') {
            console.error('_initDocumentsTab: loadDocumentsData не найдена — DocumentsTabMixin не подмешан?');
            if (this._tabContent) {
                this._tabContent.innerHTML =
                    '<div class="settings-error">Ошибка инициализации вкладки Documents: миксин не подключён.</div>';
            }
            return;
        }
        this.loadDocumentsData().catch(e => {
            console.error('Documents tab init error:', e);
            if (this._tabContent) {
                this._tabContent.innerHTML =
                    `<div class="settings-error">Ошибка загрузки: ${this.escapeHtml(e.message)}</div>`;
            }
        });
    }

    async handleDocumentsAction(action, btn) {
        if (action === 'delete-document') {
            const id = btn?.dataset.id;
            if (!id || !confirm('Удалить документ?')) return;
            try {
                await this.api.deleteDocument(id);
                await this.loadDocumentsData();
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'reindex-document') {
            const id = btn?.dataset.id;
            if (!id) return;
            try {
                await this.api.reindexDocument(id);
                await this.loadDocumentsData();
            } catch (e) { alert('Ошибка переиндексации: ' + e.message); }
        } else if (action === 'run-indexer') {
            try {
                await this._runIndexer();
            } catch (e) { alert('Ошибка запуска индексации: ' + e.message); }
        }
    }

    // ─── Utility ───────────────────────────────────────────────────────────────────────────

    escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}

const settingsManager = new SettingsManager();

// ─── Bootstrap ────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const openBtn      = document.getElementById('settings-btn');
    const backBtn      = document.getElementById('back-to-chat-btn');
    const settingsPage = document.getElementById('settings-page');
    const mainApp      = document.querySelector('.app-container');

    // Инициализируем обработчики один раз сразу после загрузки DOM
    settingsManager.setup();

    if (openBtn && settingsPage) {
        openBtn.addEventListener('click', async () => {
            settingsPage.classList.remove('hidden');
            if (mainApp) mainApp.style.display = 'none';
            // Сброс вкладки на domains при каждом открытии
            settingsManager.currentTab = 'domains';
            const nav = document.querySelector('.settings-tabs');
            if (nav) {
                nav.querySelectorAll('[data-tab]').forEach(b => {
                    b.classList.toggle('active', b.dataset.tab === 'domains');
                });
            }
            await settingsManager.init();
        });
    }

    if (backBtn && settingsPage) {
        backBtn.addEventListener('click', () => {
            settingsPage.classList.add('hidden');
            if (mainApp) mainApp.style.display = '';
        });
    }
});
