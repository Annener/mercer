// Settings Manager
class SettingsManager {
    constructor() {
        this.api = chatAPI;
        this.currentTab = 'status';
        this._activeVaultId = null;
        // Используем правильные ID из index.html
        this._tabContent = document.getElementById('settings-content');
        this._tabNav = document.querySelector('.settings-tabs');
        this.initNav();
        this.loadTab('domains');
    }

    initNav() {
        if (!this._tabNav) return;
        this._tabNav.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-tab]');
            if (!btn) return;
            this._tabNav.querySelectorAll('[data-tab]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            this.loadTab(btn.dataset.tab);
        });
    }

    async loadTab(tab) {
        this.currentTab = tab;
        if (!this._tabContent) return;
        this._tabContent.innerHTML = '<div class="loading-state">Загрузка...</div>';

        if (tab === 'documents' || tab === 'campaigns') {
            this._activeVaultId = null;
        }

        try {
            if (tab === 'documents' || tab === 'campaigns') {
                await this._resolveVaultId();
            }

            let html = '';
            switch (tab) {
                case 'status':      html = await this.renderStatusTab(); break;
                case 'params':      html = await this.renderParamsTab(); break;
                case 'domains':     html = await this.renderDomainsTab(); break;
                case 'vaults':      html = await this.renderVaultsTab(); break;
                case 'gen-models':  html = await this.renderGenModelsTab(); break;
                case 'emb-models':  html = await this.renderEmbModelsTab(); break;
                case 'pipelines':   html = await this.renderPipelinesTab(); break;
                case 'campaigns':   html = await this.renderCampaignsTab(); break;
                case 'documents':   html = await this.renderDocumentsTab(); break;
                default: html = '<div class="empty-state">Неизвестная вкладка</div>';
            }
            this._tabContent.innerHTML = html;

            if (tab === 'documents') {
                await this.loadDocumentsData();
            }

            this.bindTabEvents(tab);
        } catch (e) {
            this._tabContent.innerHTML = `<div class="empty-state" style="color:var(--color-error)">Ошибка загрузки: ${this.escapeHtml(e.message)}</div>`;
        }
    }

    bindTabEvents(tab) {
        if (!this._tabContent) return;

        this._tabContent.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;
            const action = btn.dataset.action;
            if (action === undefined) return;

            try {
                switch (tab) {
                    case 'status':      await this.handleStatusAction(action, btn); break;
                    case 'params':      await this.handleParamsAction(action, btn); break;
                    case 'domains':     await this.handleDomainsAction(action, btn.dataset.id || null); break;
                    case 'vaults':      await this.handleVaultsAction(action, btn.dataset.id || null); break;
                    case 'gen-models':  await this.handleGenModelsAction(action, btn.dataset.id || null); break;
                    case 'emb-models':  await this.handleEmbModelsAction(action, btn.dataset.id || null); break;
                    case 'pipelines':   await this.handlePipelinesAction(action, btn.dataset.id || null); break;
                    case 'campaigns':   await this.handleCampaignsAction(action, btn.dataset.id || null); break;
                    case 'documents':   await this.handleDocumentsAction(action, btn); break;
                }
            } catch (err) {
                console.error('Tab action error:', err);
                alert('Ошибка: ' + err.message);
            }
        });

        this._tabContent.addEventListener('click', (e) => {
            const toggle = e.target.closest('.card-menu-toggle');
            if (!toggle) return;
            e.stopPropagation();
            const container = toggle.closest('.card-menu-container');
            if (!container) return;
            const menu = container.querySelector('.card-menu');
            if (!menu) return;
            const isOpen = menu.classList.contains('open');
            document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
            if (!isOpen) menu.classList.add('open');
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.card-menu-container')) {
                document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
            }
        }, { once: true });
    }

    async handleStatusAction(action, btn) {}
    async handleParamsAction(action, btn) {}
    async handleDomainsAction(action, id) {}
    async handleVaultsAction(action, id) {}
    async handleGenModelsAction(action, id) {}
    async handleEmbModelsAction(action, id) {}
    async handlePipelinesAction(action, id) {
        if (action === 'new-pipeline') { await this.showPipelineModal(); return; }
        if (action === 'edit-pipeline') { await this.showPipelineEditModal(id); return; }
        if (action === 'activate-pipeline') {
            try { await this.api.activatePipeline(id); this.loadTab('pipelines'); } catch(e) { alert(e.message); }
            return;
        }
        if (action === 'deactivate-pipeline') {
            try { await this.api.deactivatePipeline(id); this.loadTab('pipelines'); } catch(e) { alert(e.message); }
            return;
        }
        if (action === 'delete-pipeline') {
            if (!confirm('Удалить pipeline?')) return;
            try { await this.api.deletePipeline(id); this.loadTab('pipelines'); } catch(e) { alert(e.message); }
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (!window.chatAPI) {
        console.error('chatAPI not available — SettingsManager will not initialize');
        return;
    }

    // Кнопка «Настройки платформы» — показываем/скрываем settings-page
    const settingsBtn = document.getElementById('settings-btn');
    const settingsPage = document.getElementById('settings-page');
    const mainApp = document.querySelector('.app-container');
    const backBtn = document.getElementById('back-to-chat-btn');

    if (settingsBtn && settingsPage) {
        settingsBtn.addEventListener('click', () => {
            settingsPage.classList.remove('hidden');
            if (mainApp) mainApp.style.display = 'none';
            // Инициализируем менеджер если ещё не создан
            if (!window.settingsManager) {
                window.settingsManager = new SettingsManager();
            } else {
                // Обновляем ссылки на DOM (на случай если они изменились)
                window.settingsManager._tabContent = document.getElementById('settings-content');
                window.settingsManager._tabNav = document.querySelector('.settings-tabs');
                window.settingsManager.loadTab(window.settingsManager.currentTab || 'domains');
            }
        });
    }

    if (backBtn && settingsPage) {
        backBtn.addEventListener('click', () => {
            settingsPage.classList.add('hidden');
            if (mainApp) mainApp.style.display = '';
        });
    }
});
