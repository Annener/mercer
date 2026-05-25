// === DB Management UI (domain-based) ===
class DBManager {
    constructor() {
        this.modal = document.getElementById('db-mgmt-modal');
        this.openBtn = document.getElementById('db-mgmt-btn');
        this.closeBtn = document.getElementById('db-mgmt-close-btn');
        
        // Вкладки
        this.tabs = this.modal.querySelectorAll('.tab');
        this.tabContents = this.modal.querySelectorAll('.tab-content');
        
        // Вкладка "Управление"
        this.mgmtDomainSelect = document.getElementById('mgmt-domain-select');
        this.mgmtSearchInput = document.getElementById('mgmt-search-input');
        this.vaultsContainer = document.getElementById('mgmt-vaults-container');
        
        // Прогресс
        this.progressBlock = document.getElementById('mgmt-progress-block');
        this.taskIdSpan = document.getElementById('mgmt-task-id');
        this.taskStatusSpan = document.getElementById('mgmt-task-status');
        this.filesDoneSpan = document.getElementById('mgmt-files-done');
        this.filesTotalSpan = document.getElementById('mgmt-files-total');
        this.progressPctSpan = document.getElementById('mgmt-progress-pct');
        this.filesList = document.getElementById('mgmt-files-list');
        this.cancelBtn = document.getElementById('mgmt-cancel-btn');
        this.overallBar = document.getElementById('mgmt-overall-bar');  // новый элемент в HTML
        
        // Вкладка "Поиск"
        this.searchDomainSelect = document.getElementById('search-domain-select');
        this.searchQueryInput = document.getElementById('search-query-input');
        this.searchLimitInput = document.getElementById('search-limit');
        this.searchBtn = document.getElementById('search-btn');
        this.searchResults = document.getElementById('search-results');
        
        // Состояние
        this.domains = [];
        this.currentTaskId = null;
        this.currentWs = null;
        this.currentFiles = {};
        this.expandedVaults = new Set();
        this.vaultDocsCache = {};  // vaultId -> documents
        
        this.initEventListeners();
    }

    initEventListeners() {
        this.openBtn.addEventListener('click', () => this.open());
        this.closeBtn.addEventListener('click', () => this.close());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });
        
        this.tabs.forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });
        
        // Фильтры управления
        this.mgmtDomainSelect.addEventListener('change', () => this.renderManageView());
        this.mgmtSearchInput.addEventListener('input', this.debounce(() => this.renderManageView(), 250));
        
        // Поиск
        this.searchBtn.addEventListener('click', () => this.doSearch());
        this.searchQueryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doSearch();
        });
        
        // Отмена индексации
        this.cancelBtn.addEventListener('click', () => this.cancelCurrentTask());
    }

    async open() {
        this.modal.style.display = 'flex';
        await this.loadDomains();
        await this.renderManageView();
    }

    close() {
        this.modal.style.display = 'none';
        this.disconnectWs();
    }

    switchTab(tabName) {
        this.tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));
        this.tabContents.forEach(c => c.classList.toggle('active', c.dataset.tab === tabName));
    }

    async loadDomains() {
        try {
            const [domainsResp, vaultsResp] = await Promise.all([
                chatAPI.getDomains(),
                chatAPI.getVaults(),
            ]);
            this.domains = domainsResp.domains || [];
            this.allVaults = vaultsResp.vaults || [];
            
            // Заполнить селекторы доменов
            this.populateDomainSelect(this.mgmtDomainSelect, true);
            this.populateDomainSelect(this.searchDomainSelect, false);
        } catch (error) {
            console.error('Failed to load domains:', error);
        }
    }

    populateDomainSelect(select, includeAll) {
        select.innerHTML = '';
        if (includeAll) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'Все домены';
            select.appendChild(opt);
        }
        for (const domain of this.domains) {
            const opt = document.createElement('option');
            opt.value = domain.domain_id;
            opt.textContent = this.formatDomainName(domain.domain_id);
            select.appendChild(opt);
        }
    }

    formatDomainName(domainId) {
        const names = { 'dnd': 'D&D', 'work': 'Работа' };
        return names[domainId] || domainId.toUpperCase();
    }

    async renderManageView() {
        const domainFilter = this.mgmtDomainSelect.value;
        const searchFilter = this.mgmtSearchInput.value.trim().toLowerCase();
        
        this.vaultsContainer.innerHTML = '<div class="empty-state">Загрузка...</div>';
        
        try {
            const data = await chatAPI.getVaults(domainFilter || null, null);
            let vaults = data.vaults || [];
            
            // Применяем поиск (по имени vault)
            if (searchFilter) {
                vaults = vaults.filter(v => v.vault_id.toLowerCase().includes(searchFilter));
            }
            
            // Группировка по доменам
            const byDomain = {};
            for (const vault of vaults) {
                if (!byDomain[vault.domain_id]) byDomain[vault.domain_id] = [];
                byDomain[vault.domain_id].push(vault);
            }
            
            this.vaultsContainer.innerHTML = '';
            const domainIds = Object.keys(byDomain).sort();
            
            if (domainIds.length === 0) {
                this.vaultsContainer.innerHTML = '<div class="empty-state">Нет vault\'ов по заданным фильтрам</div>';
                return;
            }
            
            for (const domainId of domainIds) {
                const section = document.createElement('div');
                section.className = 'domain-section';
                section.innerHTML = `
                    <div class="domain-section-header">
                        <h4>${this.escapeHtml(this.formatDomainName(domainId))}</h4>
                        <span class="domain-section-count">${byDomain[domainId].length} vault(ов)</span>
                    </div>
                    <div class="domain-section-body"></div>
                `;
                const body = section.querySelector('.domain-section-body');
                
                for (const vault of byDomain[domainId]) {
                    body.appendChild(this.createVaultCard(vault, searchFilter));
                }
                
                this.vaultsContainer.appendChild(section);
            }
        } catch (error) {
            console.error('Failed to render manage view:', error);
            this.vaultsContainer.innerHTML = `<div class="empty-state">Ошибка: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    createVaultCard(vault, fileSearchFilter) {
        const card = document.createElement('div');
        card.className = 'vault-card';
        card.dataset.vaultId = vault.vault_id;
        
        const isExpanded = this.expandedVaults.has(vault.vault_id);
        const statusClass = vault.enabled ? 'enabled' : 'disabled';
        const statusText = vault.enabled ? 'активен' : 'отключён';
        
        card.innerHTML = `
            <div class="vault-card-header">
                <div class="vault-card-title">
                    <button class="vault-toggle-btn" title="Развернуть/свернуть">
                        <span class="vault-toggle-icon">${isExpanded ? '▼' : '▶'}</span>
                    </button>
                    <strong>${this.escapeHtml(vault.vault_id)}</strong>
                    <span class="vault-status ${statusClass}">${statusText}</span>
                </div>
                <div class="vault-card-actions">
                    <button class="btn btn-sm btn-primary" data-action="index">🔄 Индексация</button>
                    <button class="btn btn-sm btn-secondary" data-action="reindex">⚡ Reindex</button>
                    <button class="btn btn-sm btn-danger" data-action="detach">🗑️ Detach</button>
                </div>
            </div>
            <div class="vault-card-body" style="display: ${isExpanded ? 'block' : 'none'}">
                <div class="vault-docs-container">
                    <div class="empty-state">Кликните для загрузки документов</div>
                </div>
            </div>
        `;
        
        // Toggle expand
        const toggleBtn = card.querySelector('.vault-toggle-btn');
        const body = card.querySelector('.vault-card-body');
        toggleBtn.addEventListener('click', () => {
            const expanded = this.expandedVaults.has(vault.vault_id);
            if (expanded) {
                this.expandedVaults.delete(vault.vault_id);
                body.style.display = 'none';
                toggleBtn.querySelector('.vault-toggle-icon').textContent = '▶';
            } else {
                this.expandedVaults.add(vault.vault_id);
                body.style.display = 'block';
                toggleBtn.querySelector('.vault-toggle-icon').textContent = '▼';
                this.loadDocumentsForVault(vault.vault_id, card, fileSearchFilter);
            }
        });
        
        // Если был развёрнут — загрузить документы
        if (isExpanded) {
            this.loadDocumentsForVault(vault.vault_id, card, fileSearchFilter);
        }
        
        // Actions
        card.querySelector('[data-action="index"]').addEventListener('click', () => this.startIndexing(vault.vault_id, false));
        card.querySelector('[data-action="reindex"]').addEventListener('click', () => this.startIndexing(vault.vault_id, true));
        card.querySelector('[data-action="detach"]').addEventListener('click', () => this.detachVault(vault.vault_id));
        
        return card;
    }

    async loadDocumentsForVault(vaultId, card, fileSearchFilter) {
        const container = card.querySelector('.vault-docs-container');
        container.innerHTML = '<div class="empty-state">Загрузка документов...</div>';
        
        try {
            const data = await chatAPI.listDocuments(vaultId, 500, 0);
            let docs = data.documents || [];
            
            // Фильтр по имени файла
            if (fileSearchFilter) {
                docs = docs.filter(d => d.source_path.toLowerCase().includes(fileSearchFilter));
            }
            
            this.vaultDocsCache[vaultId] = docs;
            
            if (docs.length === 0) {
                container.innerHTML = '<div class="empty-state">Документов нет. Запустите индексацию.</div>';
                return;
            }
            
            const table = document.createElement('table');
            table.className = 'data-table';
            table.innerHTML = `
                <thead>
                    <tr>
                        <th>source_path</th>
                        <th>chunks</th>
                        <th>actions</th>
                    </tr>
                </thead>
                <tbody></tbody>
            `;
            const tbody = table.querySelector('tbody');
            
            for (const doc of docs) {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="path-cell" title="${this.escapeHtml(doc.source_path)}">${this.escapeHtml(doc.source_path)}</td>
                    <td>${doc.chunk_count}</td>
                    <td>
                        <button class="btn btn-sm btn-danger" data-action="delete-doc">🗑️</button>
                    </td>
                `;
                tr.querySelector('[data-action="delete-doc"]').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteDocument(doc.document_id, doc.source_path, vaultId);
                });
                tbody.appendChild(tr);
            }
            
            container.innerHTML = '';
            container.appendChild(table);
        } catch (error) {
            console.error('Failed to load documents:', error);
            container.innerHTML = `<div class="empty-state">Ошибка: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    async deleteDocument(documentId, sourcePath, vaultId) {
        if (!confirm(`Удалить документ?\n\n${sourcePath}\n\nЭто удалит все чанки из векторной БД.`)) return;
        
        try {
            await chatAPI.deleteDocument(documentId, vaultId);
            // Перерисовать
            await this.renderManageView();
        } catch (error) {
            console.error('Failed to delete document:', error);
            alert(`Ошибка удаления: ${error.message}`);
        }
    }

    async startIndexing(vaultId, forceReindex) {
        try {
            const resp = await chatAPI.reindexVault(vaultId, forceReindex);
            this.currentTaskId = resp.task_id;
            this.showProgressBlock(resp.task_id);
            this.connectWebSocket(resp.task_id);
        } catch (error) {
            console.error('Failed to start indexing:', error);
            alert(`Ошибка запуска: ${error.message}`);
        }
    }

    showProgressBlock(taskId) {
        this.progressBlock.style.display = 'block';
        this.taskIdSpan.textContent = taskId.slice(0, 12) + '…';
        this.taskStatusSpan.textContent = 'running';
        this.taskStatusSpan.className = 'status-badge status-running';
        this.filesDoneSpan.textContent = '0';
        this.filesTotalSpan.textContent = '0';
        this.progressPctSpan.textContent = '0';
        this.filesList.innerHTML = '';
        this.currentFiles = {};
        this.cancelBtn.style.display = '';
        if (this.overallBar) this.overallBar.style.width = '0%';
    }

    connectWebSocket(taskId) {
        this.disconnectWs();
        try {
            this.currentWs = chatAPI.connectToTaskStream(taskId);
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            alert('Не удалось подключиться к indexer.');
            return;
        }
        this.currentWs.onmessage = (event) => {
            try {
                this.handleWsMessage(JSON.parse(event.data));
            } catch (e) { console.warn('Failed to parse WS:', e); }
        };
        this.currentWs.onerror = (e) => console.error('WS error:', e);
        this.currentWs.onclose = () => { this.currentWs = null; };
    }

    disconnectWs() {
        if (this.currentWs) {
            try { this.currentWs.close(); } catch (e) {}
            this.currentWs = null;
        }
    }

    handleWsMessage(msg) {
        if (msg.type === 'snapshot' && msg.state) {
            const state = msg.state;
            this.filesTotalSpan.textContent = String(Object.keys(state.files || {}).length);
            for (const [path, fileState] of Object.entries(state.files || {})) {
                this.updateFileRow(
                    path,
                    fileState.status,
                    fileState.progress_pct,
                    fileState.chunks_total || 0,
                    fileState.chunks_processed || 0,
                    fileState.error || null
                );
            }
            this.recalcProgress();
        } else if (msg.type === 'file_chunk_progress') {
            this.updateFileRow(msg.file_path, msg.stage, null, msg.chunks_total, msg.chunks_processed, msg.error);
            this.recalcProgress();
        } else if (msg.type === 'file_status') {
            // back-compat: V2.1 deprecated event
            this.updateFileRow(msg.file_path, msg.status, msg.progress_pct, 0, 0, msg.error);
            this.recalcProgress();
        } else if (msg.type === 'task_complete') {
            this.taskStatusSpan.textContent = 'done';
            this.taskStatusSpan.className = 'status-badge status-done';
            this.filesDoneSpan.textContent = String(msg.files_indexed);
            this.filesTotalSpan.textContent = String(msg.files_total);
            this.progressPctSpan.textContent = '100';
            if (this.overallBar) this.overallBar.style.width = '100%';
            this.cancelBtn.style.display = 'none';
            this.expandedVaults.clear();
            this.vaultDocsCache = {};
            this.renderManageView();
        } else if (msg.type === 'task_cancelled') {
            this.taskStatusSpan.textContent = 'cancelled';
            this.taskStatusSpan.className = 'status-badge status-cancelled';
            this.cancelBtn.style.display = 'none';
        } else if (msg.error) {
            this.taskStatusSpan.textContent = 'error';
            this.taskStatusSpan.className = 'status-badge status-error';
        }
    }

    updateFileRow(path, stage, progressPct = null, chunksTotal = 0, chunksProcessed = 0, error = null) {
        this.currentFiles[path] = {
            stage,
            chunks_total: chunksTotal,
            chunks_processed: chunksProcessed,
            progress_pct: progressPct,
            error
        };

        // Вычисляем процент прогресса для бара
        let pct = 0;
        if (chunksTotal > 0) {
            pct = Math.round(chunksProcessed / chunksTotal * 100);
        } else {
            pct = progressPct || 0;
        }

        // Цвет бара
        let barColor;
        if (stage === 'error') {
            barColor = '#e74c3c';
        } else if (stage === 'done' || stage === 'indexed' || stage === 'empty') {
            barColor = '#27ae60';
        } else if (stage === 'parsing' || stage === 'chunking') {
            barColor = '#f39c12';
        } else if (stage === 'indexing') {
            barColor = '#3498db';
        } else {
            barColor = '#95a5a6';
        }

        // Счётчик чанков
        const chunksLabel = chunksTotal > 0
            ? `${chunksProcessed} / ${chunksTotal} чанков`
            : '—';

        let row = this.filesList.querySelector(`[data-path="${CSS.escape(path)}"]`);
        if (!row) {
            row = document.createElement('div');
            row.className = 'file-row';
            row.dataset.path = path;
            row.innerHTML = `
                <span class="file-path"></span>
                <span class="file-chunks"></span>
                <span class="file-stage stage-badge"></span>
                <div class="file-progress"><div class="file-progress-bar"></div></div>
            `;
            this.filesList.appendChild(row);
        }

        const pathEl = row.querySelector('.file-path');
        pathEl.textContent = path;
        pathEl.title = error || path;

        row.querySelector('.file-chunks').textContent = chunksLabel;

        const stageEl = row.querySelector('.file-stage');
        stageEl.textContent = stage || '';
        stageEl.className = `file-stage stage-badge stage-${stage || 'pending'}`;

        const bar = row.querySelector('.file-progress-bar');
        bar.style.width = `${pct}%`;
        bar.style.backgroundColor = barColor;
    }

    recalcProgress() {
        const files = Object.values(this.currentFiles);
        const total = files.length;

        // Суммируем чанки
        let sumTotal = 0;
        let sumProcessed = 0;
        for (const f of files) {
            sumTotal += f.chunks_total || 0;
            sumProcessed += f.chunks_processed || 0;
        }

        // done-файлы: stage === 'done' || 'indexed' || 'empty'
        const doneStages = new Set(['done', 'indexed', 'empty']);
        const done = files.filter(f => doneStages.has(f.stage)).length;

        let pct;
        if (sumTotal > 0) {
            pct = Math.round(sumProcessed / sumTotal * 100);
        } else {
            // fallback для back-compat (file_status без чанков)
            pct = total > 0 ? Math.round((done / total) * 100) : 0;
        }

        this.filesDoneSpan.textContent = String(done);
        this.filesTotalSpan.textContent = String(total);
        this.progressPctSpan.textContent = String(pct);
        if (this.overallBar) this.overallBar.style.width = pct + '%';
    }

    async cancelCurrentTask() {
        if (!this.currentTaskId) return;
        if (!confirm('Отменить задачу индексации?')) return;
        try {
            await chatAPI.cancelIndexTask(this.currentTaskId);
        } catch (error) {
            alert(`Ошибка отмены: ${error.message}`);
        }
    }

    async detachVault(vaultId) {
        if (!confirm(`Detach vault "${vaultId}"?\n\nУдалит binding и все данные из векторной БД.`)) return;
        try {
            await chatAPI.detachVault(vaultId);
            alert(`Vault "${vaultId}" отключён.`);
            this.expandedVaults.clear();
            this.vaultDocsCache = {};
            await this.renderManageView();
        } catch (error) {
            alert(`Ошибка: ${error.message}`);
        }
    }

    async doSearch() {
        const domainId = this.searchDomainSelect.value;
        const query = this.searchQueryInput.value.trim();
        const limit = parseInt(this.searchLimitInput.value, 10) || 20;
        
        if (!domainId) {
            alert('Выберите домен');
            return;
        }
        if (!query) {
            alert('Введите текст для поиска');
            return;
        }
        
        this.searchBtn.disabled = true;
        this.searchResults.innerHTML = '<div class="empty-state">Поиск...</div>';
        
        try {
            const data = await chatAPI.textSearchByDomain(domainId, query, limit);
            this.renderSearchResults(data.results || [], query);
        } catch (error) {
            console.error('Search failed:', error);
            this.searchResults.innerHTML = `<div class="empty-state">Ошибка: ${this.escapeHtml(error.message)}</div>`;
        } finally {
            this.searchBtn.disabled = false;
        }
    }

    renderSearchResults(results, query) {
        if (results.length === 0) {
            this.searchResults.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
            return;
        }
        
        this.searchResults.innerHTML = '';
        for (const hit of results) {
            const div = document.createElement('div');
            div.className = 'search-result';
            div.innerHTML = `
                <div class="search-result-header">
                    <span>vault: ${this.escapeHtml(hit.metadata?.vault_id || '?')} | chunk: ${this.escapeHtml(hit.chunk_id)}</span>
                    <span>score: ${hit.score.toFixed(3)}</span>
                </div>
                <div class="search-result-text">${this.highlightText(hit.text, query)}</div>
            `;
            this.searchResults.appendChild(div);
        }
    }

    highlightText(text, query) {
        const escaped = this.escapeHtml(text);
        const escapedQuery = this.escapeHtml(query);
        if (!escapedQuery) return escaped;
        const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        return escaped.replace(regex, '<mark>$1</mark>');
    }

    escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    debounce(fn, ms) {
        let t;
        return (...args) => {
            clearTimeout(t);
            t = setTimeout(() => fn.apply(this, args), ms);
        };
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dbManager = new DBManager();
});
