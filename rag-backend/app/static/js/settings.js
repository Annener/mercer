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
                        </div>
                        <span class="badge ${vault.enabled ? 'ok' : 'muted'}">${this.escapeHtml(vault.binding_status || 'unbound')} · ${vault.chunk_count || 0}</span>
                    </article>
                `).join('')}
            </div>`;
    }

    attachTabEventHandlers(_tabId) {}

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.settingsManager = new SettingsManager(window.chatAPI);
});
