// === DB Management UI v2 ===
class DBManager {
    constructor() {
        this.modal = document.getElementById('db-mgmt-modal');
        this.openBtn = document.getElementById('db-mgmt-btn');
        this.closeBtn = document.getElementById('db-mgmt-close-btn');

        // Элементы вкладки управления (опциональные — могут появиться после рендера)
        this.domainTabsContainer = null;
        this.vaultsContainer = null;
        this.progressBlock = null;
        this.taskStatusSpan = null;
        this.filesDoneSpan = null;
        this.filesTotalSpan = null;
        this.progressPctSpan = null;
        this.filesList = null;
        this.cancelBtn = null;
        this.overallBar = null;

        // Элементы вкладки поиска
        this.searchDomainSelect = document.getElementById('search-domain-select');
        this.searchQueryInput = document.getElementById('search-query-input');
        this.searchLimitInput = document.getElementById('search-limit');
        this.searchBtn = document.getElementById('search-btn');
        this.searchResults = document.getElementById('search-results');

        this.chunkModal = document.getElementById('chunk-detail-modal');
        this.chunkModalClose = document.getElementById('chunk-detail-close');
        this.chunkModalContent = document.getElementById('chunk-detail-content');

        this.domains = [];
        this.allVaults = [];
        this.activeDomainTab = null;
        this.currentTaskId = null;
        this.currentWs = null;
        this.currentFiles = {};
        this.expandedVaults = new Set();
        this.vaultDocsCache = {};
        this._activeTab = 'search';

        this.initEventListeners();
    }

    initEventListeners() {
        this.openBtn?.addEventListener('click', () => this.open());
        this.closeBtn?.addEventListener('click', () => this.close());
        this.modal?.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        this.searchBtn?.addEventListener('click', () => this.doSearch());
        this.searchQueryInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doSearch();
        });

        if (this.chunkModal) {
            this.chunkModalClose?.addEventListener('click', () => this.closeChunkModal());
            this.chunkModal.addEventListener('click', (e) => {
                if (e.target === this.chunkModal) this.closeChunkModal();
            });
        }

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.vault-menu-wrap')) {
                document.querySelectorAll('.vault-menu-dropdown').forEach(d => d.style.display = 'none');
            }
        });
    }

    async open() {
        this.modal.style.display = 'flex';
        await this.loadDomains();
        this.populateSearchDomainSelect();
    }

    close() {
        this.modal.style.display = 'none';
        this.disconnectWs();
    }

    async loadDomains() {
        try {
            const [domainsResp, vaultsResp] = await Promise.all([
                chatAPI.getDomains(),
                chatAPI.getSettingsVaults(),
            ]);
            this.domains = Array.isArray(domainsResp) ? domainsResp : (domainsResp.domains || []);
            this.allVaults = Array.isArray(vaultsResp) ? vaultsResp : [];
        } catch (error) {
            console.error('Failed to load domains:', error);
        }
    }

    formatDomainName(domainId) {
        const names = { 'dnd': 'D&D', 'work': 'Работа' };
        if (names[domainId]) return names[domainId];
        return domainId.charAt(0).toUpperCase() + domainId.slice(1);
    }

    async populateSearchDomainSelect() {
        const sel = this.searchDomainSelect;
        if (!sel) return;
        sel.innerHTML = '';
        for (const domain of this.domains) {
            const opt = document.createElement('option');
            opt.value = domain.domain_id;
            opt.textContent = this.formatDomainName(domain.domain_id);
            sel.appendChild(opt);
        }
    }

    async doSearch() {
        const domainId = this.searchDomainSelect?.value;
        const query = this.searchQueryInput?.value?.trim();
        const limit = parseInt(this.searchLimitInput?.value || '20', 10);
        if (!query) return;
        if (!this.searchResults) return;
        this.searchResults.innerHTML = '<div class="empty-state">Поиск...</div>';
        try {
            const results = await chatAPI.textSearchByDomain(domainId, query, limit);
            const items = results.results || results || [];
            if (!items.length) {
                this.searchResults.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
                return;
            }
            this.searchResults.innerHTML = '';
            for (const item of items) {
                const el = document.createElement('div');
                el.className = 'search-result-item';
                const score = item.score != null ? `<span class="result-score">${item.score.toFixed(3)}</span>` : '';
                const source = item.source_path || item.source || '';
                el.innerHTML = `
                    <div class="result-header">
                        <span class="result-source" title="${this.escapeHtml(source)}">${this.escapeHtml(source.split('/').pop())}</span>
                        ${score}
                        <button class="btn-icon result-detail-btn" title="Подробнее">🔍</button>
                    </div>
                    <div class="result-text collapsed">${this.escapeHtml((item.text || item.content || '').slice(0, 300))}</div>
                `;
                el.querySelector('.result-detail-btn').addEventListener('click', () => {
                    this.openChunkModal(item);
                });
                el.querySelector('.result-text').addEventListener('click', (e) => {
                    e.currentTarget.classList.toggle('collapsed');
                });
                this.searchResults.appendChild(el);
            }
        } catch (e) {
            this.searchResults.innerHTML = `<div class="empty-state" style="color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</div>`;
        }
    }

    openChunkModal(item) {
        if (!this.chunkModal) return;
        const content = this.chunkModalContent;
        if (!content) return;
        const source = item.source_path || item.source || '—';
        content.innerHTML = `
            <div style="margin-bottom:var(--space-3);">
                <b>Источник:</b> <span>${this.escapeHtml(source)}</span>
            </div>
            <div style="margin-bottom:var(--space-3);">
                <b>Score:</b> ${item.score != null ? item.score.toFixed(4) : '—'}
            </div>
            <div style="white-space:pre-wrap;font-size:var(--text-sm);line-height:1.6;background:var(--color-surface-offset);padding:var(--space-4);border-radius:var(--radius-md);max-height:60vh;overflow-y:auto;">${this.escapeHtml(item.text || item.content || '')}</div>
        `;
        this.chunkModal.style.display = 'flex';
    }

    closeChunkModal() {
        if (this.chunkModal) this.chunkModal.style.display = 'none';
    }

    disconnectWs() {
        if (this.currentWs) {
            try { this.currentWs.close(); } catch (e) {}
            this.currentWs = null;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dbManager = new DBManager();
});
