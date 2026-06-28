// Settings Manager
class SettingsManager {
    constructor() {
        this.api = chatAPI;
        this.currentTab = 'domains';
        this._activeVaultId = null;
        this._activeDomainId = null;
        this._tabContent = document.getElementById('settings-content');
        this._tabNav = document.querySelector('.settings-tabs');
    }

    async init() {
        this._setupTabNav();
        await this.loadTab(this.currentTab);
    }

    _setupTabNav() {
        if (!this._tabNav) return;
        this._tabNav.querySelectorAll('[data-tab]').forEach(btn => {
            btn.addEventListener('click', async () => {
                this.currentTab = btn.dataset.tab;
                this._tabNav.querySelectorAll('[data-tab]').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                await this.loadTab(this.currentTab);
            });
        });
    }

    async loadTab(tab) {
        if (!this._tabContent) return;
        this._tabContent.innerHTML = '<div class="loading">Загрузка...</div>';
        try {
            let html = '';
            switch (tab) {
                case 'domains':       html = await this.renderDomainsTab(); break;
                case 'params':        html = await this.renderParamsTab(); break;
                case 'gen-models':    html = await this.renderGenerationModelsTab(); break;
                case 'emb-models':    html = await this.renderEmbeddingModelsTab(); break;
                case 'rerank-models': html = await this.renderRerankModelsTab(); break;
                case 'models':        html = await this.renderModelsTab(); break;
                case 'vaults':        html = await this.renderVaultsTab(); break;
                case 'pipelines':     html = await this.renderPipelinesTab(); break;
                case 'campaigns':     html = await this.renderCampaignsTab(); break;
                case 'documents':     html = await this.renderDocumentsTab(); break;
                default:              html = '<div class="settings-empty">Неизвестная вкладка</div>';
            }
            this._tabContent.innerHTML = html;
            this._bindActions();
        } catch (e) {
            this._tabContent.innerHTML = `<div class="error">Ошибка загрузки: ${this.escapeHtml(e.message)}</div>`;
        }
    }

    _bindActions() {
        if (!this._tabContent) return;
        this._tabContent.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const action = btn.dataset.action;
                const id = btn.dataset.id || null;
                await this._dispatch(this.currentTab, action, id, btn);
            });
        });
    }

    async _dispatch(tab, action, id, btn) {
        switch (tab) {
            case 'domains':       await this.handleDomainsAction(action, id, btn); break;
            case 'params':        await this.handleParamsAction(action, id, btn); break;
            case 'gen-models':    await this.handleGenModelsAction(action, id, btn); break;
            case 'emb-models':    await this.handleEmbModelsAction(action, id, btn); break;
            case 'rerank-models': await this.handleRerankModelsAction(action, id, btn); break;
            case 'models':        await this.handleModelsAction(action, id, btn); break;
            case 'vaults':        await this.handleVaultsAction(action, id, btn); break;
            case 'pipelines':     await this.handlePipelinesAction(action, id, btn); break;
            case 'campaigns':     await this.handleCampaignsAction(action, id, btn); break;
            case 'documents':     await this.handleDocumentsAction(action, btn); break;
        }
    }

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
        } else if (action === 'manage-prompts') {
            await this.showPromptsModal(id);
        } else if (action === 'manage-fields') {
            await this.showFieldsModal(id);
        }
    }

    async handleParamsAction(action, id, btn) {
        if (action === 'save-params') {
            const form = this._tabContent.querySelector('#params-form');
            if (!form) return;
            const inputs = form.querySelectorAll('[data-key]');
            const updates = [];
            inputs.forEach(input => {
                const key = input.dataset.key;
                const value = input.type === 'checkbox'
                    ? (input.checked ? 'true' : 'false')
                    : input.value;
                updates.push({ key, value });
            });
            try {
                for (const u of updates) {
                    await this.api.updateSettingsParam(u.key, u.value);
                }
                const checkedExts = [...this._tabContent.querySelectorAll('#watchdog-ext-list [data-ext]')]
                    .filter(cb => cb.checked)
                    .map(cb => cb.dataset.ext);
                const intervalInput = this._tabContent.querySelector('#watchdog-interval');
                const intervalSec = Math.max(10, parseInt(intervalInput?.value ?? '60', 10) || 60);
                await this.api.saveWatchdogSettings(checkedExts, intervalSec);
                alert('Параметры сохранены');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'reset-params') {
            if (!confirm('Сбросить все параметры к значениям по умолчанию?')) return;
            try {
                await this.api.resetSettingsParams();
                await this.loadTab('params');
            } catch (e) { alert('Ошибка сброса: ' + e.message); }
        } else if (action === 'add-watchdog-ext') {
            const input = this._tabContent.querySelector('#watchdog-custom-ext');
            const msgEl = this._tabContent.querySelector('#watchdog-message');
            const ext = (input?.value || '').trim();
            if (!ext.startsWith('.')) {
                if (msgEl) { msgEl.textContent = 'Расширение должно начинаться с "."'; msgEl.className = 'error'; }
                return;
            }
            const existing = this._tabContent.querySelector(`#watchdog-ext-list [data-ext="${CSS.escape(ext)}"]`);
            if (existing) {
                if (msgEl) { msgEl.textContent = `Расширение ${ext} уже есть в списке`; msgEl.className = ''; }
                return;
            }
            const list = this._tabContent.querySelector('#watchdog-ext-list');
            if (list) {
                const label = document.createElement('label');
                label.className = 'settings-param-row indexing-ext-row';
                label.innerHTML = `
                    <input type="checkbox" data-ext="${this.escapeHtml(ext)}" checked>
                    <span>${this.escapeHtml(ext)}</span>
                `;
                list.appendChild(label);
            }
            if (input) input.value = '';
            if (msgEl) { msgEl.textContent = ''; msgEl.className = ''; }
        } else if (action === 'sidecar-install') {
            this._openInstallModal();
        } else if (action === 'sidecar-start') {
            if (btn.disabled) return;
            await this._sidecarAction('start');
        } else if (action === 'sidecar-stop') {
            if (btn.disabled) return;
            await this._sidecarAction('stop');
        } else if (action === 'sidecar-restart') {
            if (btn.disabled) return;
            await this._sidecarAction('restart');
        }
    }

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
                const res = await this.api.checkGenerationModel(id);
                alert(res.ok ? `Проверка успешна (${res.latency_ms} ms)` : `Ошибка проверки: ${res.error || 'unknown error'}`);
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

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
        } else if (action === 'toggle-emb') {
            try {
                await this.api.toggleEmbeddingModel(id);
                await this.loadTab('models');
            } catch (e) { alert('Ошибка переключения: ' + e.message); }
        } else if (action === 'check-emb') {
            try {
                const res = await this.api.checkEmbeddingModel(id);
                alert(res.ok ? `Проверка успешна (${res.latency_ms} ms)` : `Ошибка проверки: ${res.error || 'unknown error'}`);
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

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
                const res = await this.api.checkRerankModel(id);
                alert(res.ok ? `Проверка успешна (${res.latency_ms} ms)` : `Ошибка проверки: ${res.error || 'unknown error'}`);
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

    async handleModelsAction(action, id, btn) {
        const type = btn?.dataset.modelType || btn?.closest('[data-model-type]')?.dataset.modelType;
        if (!type) return;
        if (type === 'gen') return this.handleGenModelsAction(action, id, btn);
        if (type === 'emb') return this.handleEmbModelsAction(action, id, btn);
        if (type === 'rerank') return this.handleRerankModelsAction(action, id, btn);
    }

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

    async handleDocumentsAction(action, btn) {
        if (action === 'delete-document') {
            const id = btn?.dataset.id;
            if (!id) return;
            if (!confirm('Удалить документ? Это действие необратимо.')) return;
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
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'filter-documents') {
            await this.loadDocumentsData();
        } else if (action === 'clear-filter') {
            const vaultSel = this._tabContent.querySelector('#filter-vault');
            const domainSel = this._tabContent.querySelector('#filter-domain');
            const statusSel = this._tabContent.querySelector('#filter-status');
            if (vaultSel) vaultSel.value = '';
            if (domainSel) domainSel.value = '';
            if (statusSel) statusSel.value = '';
            await this.loadDocumentsData();
        }
    }

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

document.addEventListener('DOMContentLoaded', () => {
    const openBtn = document.getElementById('settings-btn');
    const backBtn = document.getElementById('back-to-chat-btn');
    const settingsPage = document.getElementById('settings-page');
    const mainApp = document.querySelector('.app-container');

    if (openBtn && settingsPage) {
        openBtn.addEventListener('click', async () => {
            settingsPage.classList.remove('hidden');
            if (mainApp) mainApp.style.display = 'none';
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
