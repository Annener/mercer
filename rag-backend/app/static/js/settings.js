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
     * S36-new2 fix: используем getSettingsDomains() вместо getDomains()
     * (полный список, включая системные домены).
     */
    async _resolveDomainId() {
        if (this._activeDomainId) return this._activeDomainId;
        try {
            const sidebarDomain = window.sidebarManager?.currentDomain || localStorage.getItem('currentDomain');
            if (sidebarDomain) {
                this._activeDomainId = sidebarDomain;
                return this._activeDomainId;
            }
            const resp = await this.api.getSettingsDomains();
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

        if (tab === 'campaigns' || tab === 'pipelines') {
            this._activeDomainId = null;
            await this._resolveDomainId();
        }
        if (tab === 'documents') {
            this._activeVaultId = null;
            await this._resolveVaultId();
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

    // ─── Params ──────────────────────────────────────────────────────────────

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

    // ─── Domains ─────────────────────────────────────────────────────────────

    async handleDomainsAction(action, id) {
        if (action === 'new-domain')    { await this.showDomainModal(); return; }
        if (action === 'edit-domain')   { await this.showDomainModal(id); return; }
        if (action === 'edit-prompts')  { await this.showPromptsModal(id); return; }
        if (action === 'edit-fields')   { await this.showFieldsModal(id); return; }
        if (action === 'delete-domain') {
            if (!confirm(`Удалить домен «${id}»? Действие необратимо.`)) return;
            await this.api.deleteDomain(id);
            await this.loadTab('domains');
        }
    }

    // ─── Vaults ──────────────────────────────────────────────────────────────

    async handleVaultsAction(action, id) {
        if (action === 'new-vault') {
            await this.showVaultModal();
            return;
        }
        if (action === 'edit-vault') {
            await this.showVaultModal(id);
            return;
        }
        // S17-B fix: был updateVault({enabled: !vault.enabled}) — лишний GET + PUT;
        // теперь toggleVault() → POST /vaults/{id}/toggle (атомарная операция на бэке)
        if (action === 'toggle-vault') {
            await this.api.toggleVault(id);
            await this.loadTab('vaults');
            return;
        }
        if (action === 'delete-vault') {
            if (!confirm(`Удалить vault «${id}»? Действие необратимо.`)) return;
            await this.api.deleteVault(id);
            this._activeVaultId = null;
            await this.loadTab('vaults');
        }
    }

    // ─── Generation models ────────────────────────────────────────────────────

    async handleGenModelsAction(action, id) {
        if (action === 'new-gen') {
            await this.showGenModelModal();
            return;
        }
        if (action === 'edit-gen') {
            await this.showGenModelModal(id);
            return;
        }
        // C16 fix: data-action в tab-gen-models.js = "activate-gen", не "set-active-gen-model"
        if (action === 'activate-gen') {
            await this.api.setActiveGenerationModel(id);
            await this.loadTab('gen-models');
            return;
        }
        // C16 fix: добавлена обработка check-gen
        if (action === 'check-gen') {
            const result = await this.api.checkGenerationModel(id);
            const msg = result.ok
                ? `✅ OK — latency ${result.latency_ms}ms`
                : `❌ Ошибка: ${result.error}`;
            alert(msg);
            return;
        }
        if (action === 'toggle-gen') {
            const models = await this.api.getGenerationModels();
            const arr = Array.isArray(models) ? models : [];
            const model = arr.find(m => m.model_id === id);
            if (!model) return;
            await this.api.updateGenerationModel(id, { enabled: !model.enabled });
            await this.loadTab('gen-models');
            return;
        }
        if (action === 'delete-gen') {
            if (!confirm(`Удалить модель «${id}»?`)) return;
            await this.api.deleteGenerationModel(id);
            await this.loadTab('gen-models');
        }
    }

    // ─── Embedding models ─────────────────────────────────────────────────────

    async handleEmbModelsAction(action, id) {
        if (action === 'new-emb') {
            await this.showEmbModelModal();
            return;
        }
        if (action === 'edit-emb') {
            await this.showEmbModelModal(id);
            return;
        }
        // S19-A: блок set-active-emb-model удалён — метода нет, концепция неприменима
        // C16 fix: добавлена обработка check-emb
        if (action === 'check-emb') {
            const result = await this.api.checkEmbeddingModel(id);
            const msg = result.ok
                ? `✅ OK — latency ${result.latency_ms}ms, dims ${result.dimensions}`
                : `❌ Ошибка: ${result.error}`;
            alert(msg);
            return;
        }
        if (action === 'toggle-emb') {
            const models = await this.api.getEmbeddingModels();
            const arr = Array.isArray(models) ? models : [];
            const model = arr.find(m => m.model_id === id);
            if (!model) return;
            await this.api.updateEmbeddingModel(id, { enabled: !model.enabled });
            await this.loadTab('emb-models');
            return;
        }
        if (action === 'delete-emb') {
            if (!confirm(`Удалить модель «${id}»?`)) return;
            await this.api.deleteEmbeddingModel(id);
            await this.loadTab('emb-models');
        }
    }

    // ─── Pipelines ────────────────────────────────────────────────────────────

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
