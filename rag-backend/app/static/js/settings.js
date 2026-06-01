// Settings Manager
class SettingsManager {
    constructor() {
        this.api = chatAPI;
        this.currentTab = 'domains';
        this._activeVaultId = null;
        this._activeDomainId = null;
        this._tabContent = document.getElementById('settings-content');
        this._tabNav = document.getElementById('settings-tab-nav');
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
                case 'domains':    html = await this.renderDomainsTab(); break;
                case 'params':     html = await this.renderParamsTab(); break;
                case 'gen-models': html = await this.renderGenerationModelsTab(); break;
                case 'emb-models': html = await this.renderEmbeddingModelsTab(); break;
                case 'vaults':     html = await this.renderVaultsTab(); break;
                case 'pipelines':  html = await this.renderPipelinesTab(); break;
                case 'documents':  html = await this.renderDocumentsTab(); break;
                default: html = '<div>Вкладка не найдена</div>';
            }
            this._tabContent.innerHTML = html;
            this._attachTabListeners(tab);
        } catch (e) {
            this._tabContent.innerHTML = `<div class="error">Ошибка загрузки: ${this.escapeHtml(e.message)}</div>`;
        }
    }

    // ─── Tab listeners ──────────────────────────────────────────────────────────────────

    _attachTabListeners(tab) {
        if (!this._tabContent) return;

        // card-menu toggle
        this._tabContent.querySelectorAll('.card-menu-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                document.querySelectorAll('.card-menu').forEach(m => {
                    if (m !== btn.nextElementSibling) m.classList.remove('open');
                });
                btn.nextElementSibling?.classList.toggle('open');
            });
        });
        document.addEventListener('click', () => {
            document.querySelectorAll('.card-menu').forEach(m => m.classList.remove('open'));
        }, { capture: true, once: false });

        // action buttons
        this._tabContent.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const action = btn.dataset.action;
                const id = btn.dataset.id || null;
                try {
                    await this._dispatch(tab, action, id, btn);
                } catch (err) {
                    console.error('Action error:', action, err);
                }
            });
        });
    }

    async _dispatch(tab, action, id, btn) {
        switch (tab) {
            case 'domains':    await this.handleDomainsAction(action, id, btn); break;
            case 'params':     await this.handleParamsAction(action, id, btn); break;
            case 'gen-models': await this.handleGenModelsAction(action, id, btn); break;
            case 'emb-models': await this.handleEmbModelsAction(action, id, btn); break;
            case 'vaults':     await this.handleVaultsAction(action, id, btn); break;
            case 'pipelines':  await this.handlePipelinesAction(action, id, btn); break;
            case 'documents':  await this.handleDocumentsAction(action, btn); break;
        }
    }

    // ─── Domains ───────────────────────────────────────────────────────────────────────────

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

    // ─── Params ────────────────────────────────────────────────────────────────────────────

    async handleParamsAction(action, id, btn) {
        if (action === 'save-params') {
            const form = this._tabContent.querySelector('#params-form');
            if (!form) return;
            const inputs = form.querySelectorAll('[data-key]');
            const updates = [];
            inputs.forEach(input => updates.push({ key: input.dataset.key, value: input.value }));
            try {
                for (const u of updates) {
                    await this.api.updatePlatformSetting(u.key, { value: u.value });
                }
                alert('Параметры сохранены');
            } catch (e) { alert('Ошибка: ' + e.message); }
        }
    }

    // ─── Generation Models ──────────────────────────────────────────────────────────────

    async handleGenModelsAction(action, id, btn) {
        if (action === 'new-gen') {
            await this.showGenerationModelModal();
        } else if (action === 'edit-gen') {
            await this.showGenerationModelModal(id);
        } else if (action === 'delete-gen') {
            if (!confirm('Удалить модель?')) return;
            try {
                await this.api.deleteGenerationModel(id);
                await this.loadTab('gen-models');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'activate-gen') {
            try {
                await this.api.setActiveGenerationModel(id);
                await this.loadTab('gen-models');
            } catch (e) { alert('Ошибка активации: ' + e.message); }
        } else if (action === 'toggle-gen') {
            try {
                await this.api.toggleGenerationModel(id);
                await this.loadTab('gen-models');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'check-gen') {
            try {
                // C20 fix: бэк возвращает {ok, latency_ms, error} — не {status}
                const result = await this.api.checkGenerationModel(id);
                if (result?.ok) {
                    alert(`✅ Модель доступна (${result.latency_ms} мс)`);
                } else {
                    alert('❌ ' + (result?.error || 'Недоступна'));
                }
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

    // ─── Embedding Models ─────────────────────────────────────────────────────────────────

    async handleEmbModelsAction(action, id, btn) {
        if (action === 'new-emb') {
            await this.showEmbeddingModelModal();
        } else if (action === 'edit-emb') {
            await this.showEmbeddingModelModal(id);
        } else if (action === 'delete-emb') {
            if (!confirm('Удалить embedding-модель?')) return;
            try {
                await this.api.deleteEmbeddingModel(id);
                await this.loadTab('emb-models');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'check-emb') {
            try {
                // бэк возвращает {ok, latency_ms, error}
                const result = await this.api.checkEmbeddingModel(id);
                if (result?.ok) {
                    alert(`✅ Модель доступна (${result.latency_ms} мс)`);
                } else {
                    alert('❌ ' + (result?.error || 'Недоступна'));
                }
            } catch (e) { alert('Ошибка проверки: ' + e.message); }
        }
    }

    // ─── Vaults ────────────────────────────────────────────────────────────────────────────

    async handleVaultsAction(action, id, btn) {
        if (action === 'new-vault') {
            await this.showVaultModal();
        } else if (action === 'edit-vault') {
            await this.showVaultModal(id);
        } else if (action === 'delete-vault') {
            if (!confirm('Удалить vault?')) return;
            try {
                await this.api.deleteVault(id);
                await this.loadTab('vaults');
            } catch (e) { alert('Ошибка: ' + e.message); }
        } else if (action === 'toggle-vault') {
            try {
                await this.api.toggleVault(id);
                await this.loadTab('vaults');
            } catch (e) { alert('Ошибка: ' + e.message); }
        }
    }

    // ─── Pipelines ──────────────────────────────────────────────────────────────────────────

    async handlePipelinesAction(action, id, btn) {
        if (action === 'new-pipeline') {
            await this.showPipelineModal();
        } else if (action === 'edit-pipeline') {
            // C21-A fix: раньше вызывалось showPipelineModal(id), который игнорирует аргумент и открывал форму создания
            await this.showPipelineEditModal(id);
        } else if (action === 'delete-pipeline') {
            if (!confirm('Удалить pipeline?')) return;
            try {
                await this.api.deletePipeline(id);
                await this.loadTab('pipelines');
            } catch (e) { alert('Ошибка: ' + e.message); }
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
        }
    }

    // ─── Utils ─────────────────────────────────────────────────────────────────────────────

    escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
}

window.settingsManager = new SettingsManager();

document.addEventListener('DOMContentLoaded', async () => {
    const openBtn     = document.getElementById('open-settings-btn');
    const backBtn     = document.getElementById('settings-back-btn');
    const settingsPage = document.getElementById('settings-page');
    const mainApp     = document.getElementById('main-app');

    if (openBtn && settingsPage) {
        openBtn.addEventListener('click', async () => {
            settingsPage.classList.remove('hidden');
            if (mainApp) mainApp.style.display = 'none';
            await window.settingsManager.init();
        });
    }

    const tabNav = document.getElementById('settings-tab-nav');
    if (tabNav) {
        tabNav.querySelectorAll('[data-tab]').forEach(btn => {
            btn.addEventListener('click', async () => {
                tabNav.querySelectorAll('[data-tab]').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                await window.settingsManager.loadTab(btn.dataset.tab);
            });
        });
    }

    if (backBtn && settingsPage) {
        backBtn.addEventListener('click', () => {
            settingsPage.classList.add('hidden');
            if (mainApp) mainApp.style.display = '';
        });
    }
});
