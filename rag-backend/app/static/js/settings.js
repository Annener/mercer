// Settings Manager
class SettingsManager {
    constructor() {
        this.api = chatAPI;
        this.currentTab = 'status';
        this._activeVaultId = null;
        this._tabContent = document.getElementById('settings-tab-content');
        this._tabNav = document.getElementById('settings-tab-nav');
        this.initNav();
        this.loadTab('status');
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

        // Сбрасываем _activeVaultId при смене вкладки на documents/campaigns, чтобы перезагрузить
        if (tab === 'documents' || tab === 'campaigns') {
            this._activeVaultId = null;
        }

        try {
            // Получаем активный vault заранее для вкладок, которые от него зависят
            if (tab === 'documents' || tab === 'campaigns') {
                await this._resolveVaultId();
            }

            let html = '';
            switch (tab) {
                case 'status':    html = await this.renderStatusTab(); break;
                case 'params':    html = await this.renderParamsTab(); break;
                case 'domains':   html = await this.renderDomainsTab(); break;
                case 'vaults':    html = await this.renderVaultsTab(); break;
                case 'gen-models':    html = await this.renderGenModelsTab(); break;
                case 'emb-models':    html = await this.renderEmbModelsTab(); break;
                case 'pipelines': html = await this.renderPipelinesTab(); break;
                case 'campaigns': html = await this.renderCampaignsTab(); break;
                case 'documents': html = await this.renderDocumentsTab(); break;
                default: html = '<div class="empty-state">Неизвестная вкладка</div>';
            }
            this._tabContent.innerHTML = html;

            // После рендера — загружаем данные для documents
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

        // Универсальный делегат кликов
        this._tabContent.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;
            const action = btn.dataset.action;
            const id = btn.dataset.id || null;

            // Меню-тоглы
            if (action === undefined) return;

            try {
                switch (tab) {
                    case 'status':    await this.handleStatusAction(action, id); break;
                    case 'params':    await this.handleParamsAction(action, btn); break;
                    case 'domains':   await this.handleDomainsAction(action, id); break;
                    case 'vaults':    await this.handleVaultsAction(action, id); break;
                    case 'gen-models':    await this.handleGenModelsAction(action, id); break;
                    case 'emb-models':    await this.handleEmbModelsAction(action, id); break;
                    case 'pipelines': await this.handlePipelinesAction(action, id); break;
                    case 'campaigns': await this.handleCampaignsAction(action, id); break;
                    case 'documents': await this.handleDocumentsAction(action, btn); break;
                }
            } catch (err) {
                console.error('Tab action error:', err);
                alert('Ошибка: ' + err.message);
            }
        });

        // Меню-тоглы (⋮)
        this._tabContent.addEventListener('click', (e) => {
            const toggle = e.target.closest('.card-menu-toggle');
            if (!toggle) return;
            e.stopPropagation();
            const container = toggle.closest('.card-menu-container');
            if (!container) return;
            const menu = container.querySelector('.card-menu');
            if (!menu) return;
            const isOpen = menu.classList.contains('open');
            // Закрываем все
            document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
            if (!isOpen) menu.classList.add('open');
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.card-menu-container')) {
                document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
            }
        }, { once: true });
    }

    // Стаб — переопределяется в миксинах по необходимости
    async handleStatusAction(action, id) {}
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
    window.settingsManager = new SettingsManager();
});
