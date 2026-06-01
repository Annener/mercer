// Settings Manager
class SettingsManager {
    constructor() {
        this.api = chatAPI;
        this.currentTab = 'domains';
        this._activeVaultId = null;
        this._activeDomainId = null;
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

    async _resolveVaultId() {
        if (this._activeVaultId) return this._activeVaultId;
        try {
            const vaults = await this.api.getSettingsVaults();
            const arr = Array.isArray(vaults) ? vaults : [];
            const active = arr.find(v => v.enabled) || arr[0];
            this._activeVaultId = active?.vault_id || active?.id || null;
        } catch (e) {
            this._activeVaultId = null;
        }
        return this._activeVaultId;
    }

    /**
     * Резолвит активный domain_id для вкладок campaigns / documents / pipelines.
     * Приоритет: sidebar currentDomain → первый домен из API.
     */
    async _resolveDomainId() {
        if (this._activeDomainId) return this._activeDomainId;
        try {
            // Берём домен, выбранный в sidebar (если есть)
            const sidebarDomain = window.sidebarManager?.currentDomain || localStorage.getItem('currentDomain');
            if (sidebarDomain) {
                this._activeDomainId = sidebarDomain;
                return this._activeDomainId;
            }
            const resp = await this.api.getDomains();
            const domains = Array.isArray(resp) ? resp : (resp.domains || []);
            const active = domains.find(d => d.enabled !== false) || domains[0];
            this._activeDomainId = active?.domain_id || null;
        } catch (e) {
            this._activeDomainId = null;
        }
        return this._activeDomainId;
    }

    async loadTab(tab) {
        this.currentTab = tab;
        if (!this._tabContent) return;
        this._tabContent.innerHTML = '<div class="loading-state">Загрузка...</div>';

        // Резолвим контекст для вкладок, требующих domain_id
        if (tab === 'campaigns' || tab === 'pipelines') {
            this._activeDomainId = null;
            await this._resolveDomainId();
        }
        // Documents по-прежнему работают через vault (физическое хранилище)
        if (tab === 'documents') {
            this._activeVaultId = null;
            await this._resolveVaultId();
            // Также резолвим domain для тегов
            if (!this._activeDomainId) await this._resolveDomainId();
        }

        try {
            let html = '';
            switch (tab) {
                case 'status':      html = await this.renderStatusTab(); break;
                case 'params':      html = await this.renderParamsTab(); break;
                case 'domains':     html = await this.renderDomainsTab(); break;
                case 'vaults':      html = await this.renderVaultsTab(); break;
                case 'gen-models':  html = await this.renderGenerationModelsTab(); break;
                case 'emb-models':  html = await this.renderEmbeddingModelsTab(); break;
                case 'pipelines':   html = await this.renderPipelinesTab(); break;
                case 'campaigns':   html = await this.renderCampaignsTab(); break;
                case 'documents':   html = await this.renderDocumentsTab(); break;
                default: html = '<div class="empty-state">Неизвестная вкладка</div>';
            }
            this._tabContent.innerHTML = html;

            if (tab === 'documents') {
                await this.loadDocumentsData();
            }

            this._bindTabEvents(tab);
        } catch (e) {
            this._tabContent.innerHTML = `<div class="empty-state" style="color:var(--color-error)">Ошибка загрузки: ${this.escapeHtml(e.message)}</div>`;
        }
    }

    async renderStatusTab() {
        try {
            const status = await this.api.getSettingsStatus();
            const rows = Object.entries(status || {}).map(([k, v]) =>
                `<tr><td style="color:var(--color-text-muted);">${this.escapeHtml(k)}</td><td>${this.escapeHtml(String(v))}</td></tr>`
            ).join('');
            return `<table class="data-table"><thead><tr><th>Параметр</th><th>Значение</th></tr></thead><tbody>${rows || '<tr><td colspan="2" class="empty-state">Данных нет</td></tr>'}</tbody></table>`;
        } catch (e) {
            return `<div class="empty-state" style="color:var(--color-error)">Ошибка загрузки статуса: ${this.escapeHtml(e.message)}</div>`;
        }
    }

    _bindTabEvents(tab) {
        if (!this._tabContent) return;

        this._tabContent.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;
            const action = btn.dataset.action;

            try {
                switch (tab) {
                    case 'status':      break;
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

    /**
     * S2-B/S2-C fix: реализация вместо пустой заглушки.
     * Обрабатывает действия: save-param, default-param, reset-params.
     */
    async handleParamsAction(action, btn) {
        if (action === 'reset-params') {
            if (!confirm('Сбросить все параметры до значений по умолчанию?')) return;
            await this.api.resetSettingsParams();
            await this.loadTab('params');
            return;
        }

        const key = btn.dataset.id;
        if (!key) return;

        if (action === 'default-param') {
            const defaultVal = SETTINGS_DEFAULTS[key] ?? null;
            await this.api.updateSettingsParam(key, defaultVal);
            await this.loadTab('params');
            return;
        }

        if (action === 'save-param') {
            const row = btn.closest('.settings-param-row');
            if (!row) return;
            const input = row.querySelector('[data-param]');
            if (!input) return;
            const isBool = input.type === 'checkbox';
            // Приводим тип: bool остаётся bool, числовые строки приводимся к number если удаётся
            let value;
            if (isBool) {
                value = input.checked;
            } else {
                const raw = input.value;
                const num = Number(raw);
                value = raw !== '' && !Number.isNaN(num) ? num : raw;
            }
            btn.disabled = true;
            btn.textContent = 'Сохранение...';
            try {
                await this.api.updateSettingsParam(key, value);
                btn.textContent = '✓';
                setTimeout(() => { btn.disabled = false; btn.textContent = 'Сохранить'; }, 1200);
            } catch (e) {
                btn.disabled = false;
                btn.textContent = 'Сохранить';
                throw e;
            }
        }
    }

    /**
     * S5-C fix: реализация вместо пустой заглушки.
     * Обрабатывает: new-domain, edit-domain, edit-prompts, edit-fields, delete-domain.
     */
    async handleDomainsAction(action, id) {
        if (action === 'new-domain') {
            await this.showDomainModal();
            return;
        }
        if (action === 'edit-domain') {
            await this.showDomainModal(id);
            return;
        }
        if (action === 'edit-prompts') {
            await this.showPromptsModal(id);
            return;
        }
        if (action === 'edit-fields') {
            await this.showFieldsModal(id);
            return;
        }
        if (action === 'delete-domain') {
            if (!confirm(`Удалить домен «${id}»? Действие необратимо.`)) return;
            await this.api.deleteDomain(id);
            await this.loadTab('domains');
        }
    }

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

    const settingsBtn = document.getElementById('settings-btn');
    const settingsPage = document.getElementById('settings-page');
    const mainApp = document.querySelector('.app-container');
    const backBtn = document.getElementById('back-to-chat-btn');

    if (settingsBtn && settingsPage) {
        settingsBtn.addEventListener('click', () => {
            settingsPage.classList.remove('hidden');
            if (mainApp) mainApp.style.display = 'none';
            if (!window.settingsManager) {
                window.settingsManager = new SettingsManager();
            } else {
                window.settingsManager._tabContent = document.getElementById('settings-content');
                window.settingsManager._tabNav = document.querySelector('.settings-tabs');
                // Сбрасываем кешированный domain при каждом открытии настроек
                window.settingsManager._activeDomainId = null;
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
