// === DB Management UI v2 ===
// - Domain tabs (вместо select-фильтра)
// - Vault actions в меню ⋯ (три точки)
// - Прогресс индексации: компактный блок без task ID
// - Поиск: чанки свёрнуты, кнопка 🔍 для детального просмотра

class DBManager {
    constructor() {
        this.modal = document.getElementById('db-mgmt-modal');
        this.openBtn = document.getElementById('db-mgmt-btn');
        this.closeBtn = document.getElementById('db-mgmt-close-btn');

        // Tabs (manage / search)
        this.tabs = this.modal.querySelectorAll('.tab');
        this.tabContents = this.modal.querySelectorAll('.tab-content');

        // Manage tab
        this.domainTabsContainer = document.getElementById('mgmt-domain-tabs');
        this.vaultsContainer = document.getElementById('mgmt-vaults-container');

        // Прогресс
        this.progressBlock = document.getElementById('mgmt-progress-block');
        this.taskStatusSpan = document.getElementById('mgmt-task-status');
        this.filesDoneSpan = document.getElementById('mgmt-files-done');
        this.filesTotalSpan = document.getElementById('mgmt-files-total');
        this.progressPctSpan = document.getElementById('mgmt-progress-pct');
        this.filesList = document.getElementById('mgmt-files-list');
        this.cancelBtn = document.getElementById('mgmt-cancel-btn');
        this.overallBar = document.getElementById('mgmt-overall-bar');

        // Search tab
        this.searchDomainSelect = document.getElementById('search-domain-select');
        this.searchQueryInput = document.getElementById('search-query-input');
        this.searchLimitInput = document.getElementById('search-limit');
        this.searchBtn = document.getElementById('search-btn');
        this.searchResults = document.getElementById('search-results');

        // Chunk detail modal
        this.chunkModal = document.getElementById('chunk-detail-modal');
        this.chunkModalClose = document.getElementById('chunk-detail-close');
        this.chunkModalContent = document.getElementById('chunk-detail-content');

        // Состояние
        this.domains = [];
        this.allVaults = [];
        this.activeDomainTab = null;
        this.currentTaskId = null;
        this.currentWs = null;
        this.currentFiles = {};
        this.expandedVaults = new Set();
        this.vaultDocsCache = {};

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

        // Search
        this.searchBtn.addEventListener('click', () => this.doSearch());
        this.searchQueryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doSearch();
        });

        // Cancel indexing
        this.cancelBtn.addEventListener('click', () => this.cancelCurrentTask());

        // Chunk detail modal close
        if (this.chunkModal) {
            this.chunkModalClose.addEventListener('click', () => this.closeChunkModal());
            this.chunkModal.addEventListener('click', (e) => {
                if (e.target === this.chunkModal) this.closeChunkModal();
            });
        }
    }

    async open() {
        this.modal.style.display = 'flex';
        await this.loadDomains();
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

            this.renderDomainTabs();
            this.populateSearchDomainSelect();
        } catch (error) {
            console.error('Failed to load domains:', error);
        }
    }

    formatDomainName(domainId) {
        // Красивые имена для известных доменов; неизвестные отображаются как есть (id из конфига)
        const names = { 'dnd': 'D&D', 'work': 'Работа' };
        if (names[domainId]) return names[domainId];
        // Капитализация первой буквы идентификатора
        return domainId.charAt(0).toUpperCase() + domainId.slice(1);
    }

    // --- Domain tabs (Управление) ---

    renderDomainTabs() {
        this.domainTabsContainer.innerHTML = '';

        // Таб "Все"
        const allTab = this._makeDomainTab('', 'Все', this.allVaults.length);
        this.domainTabsContainer.appendChild(allTab);

        for (const domain of this.domains) {
            // Домен "default" — служебный фолбэк для промптов, не показываем в UI
            if (domain.domain_id === 'default') continue;
            const count = this.allVaults.filter(v => v.domain_id === domain.domain_id).length;
            const tab = this._makeDomainTab(domain.domain_id, this.formatDomainName(domain.domain_id), count);
            this.domainTabsContainer.appendChild(tab);
        }

        // Активируем первый таб с вaultами или "Все"
        const firstActive = this.domains.length > 0 ? this.domains[0].domain_id : '';
        this.setActiveDomainTab(firstActive);
    }

    _makeDomainTab(domainId, label, count) {
        const btn = document.createElement('button');
        btn.className = 'domain-tab';
        btn.dataset.domainId = domainId;
        btn.innerHTML = `${this.escapeHtml(label)} <span class="domain-tab-count">${count}</span>`;
        btn.addEventListener('click', () => this.setActiveDomainTab(domainId));
        return btn;
    }

    setActiveDomainTab(domainId) {
        this.activeDomainTab = domainId;
        this.domainTabsContainer.querySelectorAll('.domain-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.domainId === domainId);
        });
        this.renderManageView();
    }

    async renderManageView() {
        this.vaultsContainer.innerHTML = '<div class="empty-state">Загрузка...</div>';
        try {
            const data = await chatAPI.getVaults(this.activeDomainTab || null, null);
            const vaults = data.vaults || [];

            this.vaultsContainer.innerHTML = '';
            if (vaults.length === 0) {
                this.vaultsContainer.innerHTML = '<div class="empty-state">Нет vault\'ов</div>';
                return;
            }
            for (const vault of vaults) {
                this.vaultsContainer.appendChild(this.createVaultCard(vault));
            }
        } catch (error) {
            this.vaultsContainer.innerHTML = `<div class="empty-state">Ошибка: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    // --- Vault card с меню ⋯ ---

    createVaultCard(vault) {
        const card = document.createElement('div');
        card.className = 'vault-card2';
        card.dataset.vaultId = vault.vault_id;

        const isExpanded = this.expandedVaults.has(vault.vault_id);
        const statusDot = vault.enabled
            ? '<span class="vault-dot vault-dot-on" title="активен"></span>'
            : '<span class="vault-dot vault-dot-off" title="отключён"></span>';

        card.innerHTML = `
            <div class="vault-card2-header">
                <button class="vault-expand-btn" title="Развернуть/свернуть">
                    <span class="vault-chevron">${isExpanded ? '▾' : '▸'}</span>
                </button>
                ${statusDot}
                <span class="vault-card2-name">${this.escapeHtml(vault.vault_id)}</span>
                <span class="vault-card2-meta">${this.escapeHtml(this.formatDomainName(vault.domain_id))}</span>
                <div class="vault-menu-wrap">
                    <button class="vault-menu-btn" title="Действия">⋯</button>
                    <div class="vault-menu-dropdown" style="display:none">
                        <button data-action="index">🔄 Индексировать</button>
                        <button data-action="reindex">⚡ Переиндексировать</button>
                        <button data-action="detach" class="menu-item-danger">🗑 Detach</button>
                    </div>
                </div>
            </div>
            <div class="vault-card2-body" style="display:${isExpanded ? 'block' : 'none'}">
                <div class="vault-docs-container">
                    <div class="empty-state">Кликните ▸ для загрузки документов</div>
                </div>
            </div>
        `;

        // Expand toggle
        const expandBtn = card.querySelector('.vault-expand-btn');
        const body = card.querySelector('.vault-card2-body');
        const chevron = card.querySelector('.vault-chevron');
        expandBtn.addEventListener('click', () => {
            const expanded = this.expandedVaults.has(vault.vault_id);
            if (expanded) {
                this.expandedVaults.delete(vault.vault_id);
                body.style.display = 'none';
                chevron.textContent = '▸';
            } else {
                this.expandedVaults.add(vault.vault_id);
                body.style.display = 'block';
                chevron.textContent = '▾';
                this.loadDocumentsForVault(vault.vault_id, card);
            }
        });

        if (isExpanded) {
            this.loadDocumentsForVault(vault.vault_id, card);
        }

        // ⋯ menu
        const menuBtn = card.querySelector('.vault-menu-btn');
        const dropdown = card.querySelector('.vault-menu-dropdown');
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = dropdown.style.display !== 'none';
            // Закрыть все другие меню
            document.querySelectorAll('.vault-menu-dropdown').forEach(d => d.style.display = 'none');
            dropdown.style.display = isOpen ? 'none' : 'block';
        });
        document.addEventListener('click', () => { dropdown.style.display = 'none'; }, { once: false });

        card.querySelector('[data-action="index"]').addEventListener('click', () => {
            dropdown.style.display = 'none';
            this.startIndexing(vault.vault_id, false);
        });
        card.querySelector('[data-action="reindex"]').addEventListener('click', () => {
            dropdown.style.display = 'none';
            this.startIndexing(vault.vault_id, true);
        });
        card.querySelector('[data-action="detach"]').addEventListener('click', () => {
            dropdown.style.display = 'none';
            this.detachVault(vault.vault_id);
        });

        return card;
    }

    async loadDocumentsForVault(vaultId, card) {
        const container = card.querySelector('.vault-docs-container');
        container.innerHTML = '<div class="empty-state">Загрузка...</div>';
        try {
            const data = await chatAPI.listDocuments(vaultId, 500, 0);
            const docs = data.documents || [];
            this.vaultDocsCache[vaultId] = docs;

            if (docs.length === 0) {
                container.innerHTML = '<div class="empty-state">Нет документов. Запустите индексацию.</div>';
                return;
            }

            const table = document.createElement('table');
            table.className = 'data-table';
            table.innerHTML = `
                <thead><tr>
                    <th>Файл</th><th>Чанков</th><th></th>
                </tr></thead>
                <tbody></tbody>
            `;
            const tbody = table.querySelector('tbody');
            for (const doc of docs) {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="path-cell" title="${this.escapeHtml(doc.source_path)}">${this.escapeHtml(doc.source_path)}</td>
                    <td class="chunks-cell">${doc.chunk_count}</td>
                    <td><button class="btn-icon" data-action="delete-doc" title="Удалить">🗑</button></td>
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
            container.innerHTML = `<div class="empty-state">Ошибка: ${this.escapeHtml(error.message)}</div>`;
        }
    }

    async deleteDocument(documentId, sourcePath, vaultId) {
        if (!confirm(`Удалить документ?\n\n${sourcePath}\n\nЭто удалит все чанки из векторной БД.`)) return;
        try {
            await chatAPI.deleteDocument(documentId, vaultId);
            await this.renderManageView();
        } catch (error) {
            alert(`Ошибка удаления: ${error.message}`);
        }
    }

    // --- Индексация и прогресс ---

    async startIndexing(vaultId, forceReindex) {
        try {
            const resp = await chatAPI.reindexVault(vaultId, forceReindex);
            this.currentTaskId = resp.task_id;
            this.showProgressBlock();
            this.connectWebSocket(resp.task_id);
        } catch (error) {
            alert(`Ошибка запуска: ${error.message}`);
        }
    }

    showProgressBlock() {
        this.progressBlock.style.display = 'block';
        this.taskStatusSpan.textContent = 'запуск';
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
            alert('Не удалось подключиться к indexer.');
            return;
        }
        this.currentWs.onmessage = (event) => {
            try { this.handleWsMessage(JSON.parse(event.data)); } catch (e) {}
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
                this.updateFileRow(path, fileState.status, fileState.progress_pct,
                    fileState.chunks_total || 0, fileState.chunks_processed || 0, fileState.error || null);
            }
            this.recalcProgress();
        } else if (msg.type === 'file_chunk_progress') {
            this.updateFileRow(msg.file_path, msg.stage, null, msg.chunks_total, msg.chunks_processed, msg.error);
            this.recalcProgress();
        } else if (msg.type === 'file_status') {
            this.updateFileRow(msg.file_path, msg.status, msg.progress_pct, 0, 0, msg.error);
            this.recalcProgress();
        } else if (msg.type === 'task_complete') {
            this.taskStatusSpan.textContent = 'готово';
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
            this.taskStatusSpan.textContent = 'отменено';
            this.taskStatusSpan.className = 'status-badge status-cancelled';
            this.cancelBtn.style.display = 'none';
        } else if (msg.error) {
            this.taskStatusSpan.textContent = 'ошибка';
            this.taskStatusSpan.className = 'status-badge status-error';
        }
    }

    updateFileRow(path, stage, progressPct = null, chunksTotal = 0, chunksProcessed = 0, error = null) {
        this.currentFiles[path] = { stage, chunks_total: chunksTotal, chunks_processed: chunksProcessed, progress_pct: progressPct, error };

        let pct = chunksTotal > 0 ? Math.round(chunksProcessed / chunksTotal * 100) : (progressPct || 0);

        const stageColors = {
            error: '#e74c3c', done: '#27ae60', indexed: '#27ae60', empty: '#27ae60',
            parsing: '#f39c12', chunking: '#f39c12', indexing: '#3498db',
        };
        const barColor = stageColors[stage] || '#95a5a6';

        const stageLabels = {
            parsing: 'парсинг', chunking: 'нарезка', indexing: 'индексация',
            done: 'готово', error: 'ошибка', empty: 'пусто', pending: 'ожидание',
        };
        const stageLabel = stageLabels[stage] || (stage || '');
        const chunksLabel = chunksTotal > 0 ? `${chunksProcessed} / ${chunksTotal}` : '';

        let row = this.filesList.querySelector(`[data-path="${CSS.escape(path)}"]`);
        if (!row) {
            row = document.createElement('div');
            row.className = 'file-row2';
            row.dataset.path = path;
            row.innerHTML = `
                <div class="file-row2-top">
                    <span class="file-row2-name"></span>
                    <span class="file-row2-chunks"></span>
                    <span class="file-row2-stage stage-badge"></span>
                </div>
                <div class="file-progress"><div class="file-progress-bar"></div></div>
            `;
            this.filesList.appendChild(row);
        }

        const nameEl = row.querySelector('.file-row2-name');
        // Показываем только имя файла, полный путь в title
        const shortName = path.split('/').pop();
        nameEl.textContent = shortName;
        nameEl.title = error || path;

        row.querySelector('.file-row2-chunks').textContent = chunksLabel;

        const stageEl = row.querySelector('.file-row2-stage');
        stageEl.textContent = stageLabel;
        stageEl.className = `file-row2-stage stage-badge stage-${stage || 'pending'}`;

        const bar = row.querySelector('.file-progress-bar');
        bar.style.width = `${pct}%`;
        bar.style.backgroundColor = barColor;
    }

    recalcProgress() {
        const files = Object.values(this.currentFiles);
        const total = files.length;
        let sumTotal = 0, sumProcessed = 0;
        for (const f of files) {
            sumTotal += f.chunks_total || 0;
            sumProcessed += f.chunks_processed || 0;
        }
        const doneStages = new Set(['done', 'indexed', 'empty']);
        const done = files.filter(f => doneStages.has(f.stage)).length;
        const pct = sumTotal > 0
            ? Math.round(sumProcessed / sumTotal * 100)
            : (total > 0 ? Math.round(done / total * 100) : 0);

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
            this.expandedVaults.clear();
            this.vaultDocsCache = {};
            await this.loadDomains();
        } catch (error) {
            alert(`Ошибка: ${error.message}`);
        }
    }

    // --- Поиск ---

    populateSearchDomainSelect() {
        this.searchDomainSelect.innerHTML = '';
        for (const domain of this.domains) {
            const opt = document.createElement('option');
            opt.value = domain.domain_id;
            opt.textContent = this.formatDomainName(domain.domain_id);
            this.searchDomainSelect.appendChild(opt);
        }
    }

    async doSearch() {
        const domainId = this.searchDomainSelect.value;
        const query = this.searchQueryInput.value.trim();
        const limit = parseInt(this.searchLimitInput.value, 10) || 20;

        if (!domainId) { alert('Выберите домен'); return; }
        if (!query) { alert('Введите текст для поиска'); return; }

        this.searchBtn.disabled = true;
        this.searchResults.innerHTML = '<div class="empty-state">Поиск...</div>';
        try {
            const data = await chatAPI.textSearchByDomain(domainId, query, limit);
            this.renderSearchResults(data.results || [], query);
        } catch (error) {
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
            div.className = 'search-hit';

            // Превью: первые ~200 символов текста
            const fullText = hit.text || '';
            const previewText = fullText.length > 220
                ? fullText.slice(0, 220).trimEnd() + '…'
                : fullText;
            const isLong = fullText.length > 220;

            const source = hit.metadata?.source_path || hit.document_id || '?';
            const score = typeof hit.score === 'number' ? hit.score.toFixed(3) : '?';
            const page = hit.metadata?.page_number != null ? `стр. ${hit.metadata.page_number}` : '';
            const section = hit.metadata?.headers?.section ? `§ ${hit.metadata.headers.section}` : '';

            div.innerHTML = `
                <div class="search-hit-header">
                    <span class="search-hit-source" title="${this.escapeHtml(source)}">${this.escapeHtml(source.split('/').pop())}</span>
                    <span class="search-hit-meta">${this.escapeHtml([page, section].filter(Boolean).join(' · '))}</span>
                    <span class="search-hit-score">score ${score}</span>
                    <button class="search-hit-detail-btn" title="Все свойства чанка">🔍</button>
                </div>
                <div class="search-hit-body">
                    <div class="search-hit-preview">${this.highlightText(this.escapeHtml(previewText), query)}</div>
                    ${isLong ? `
                        <div class="search-hit-full" style="display:none">${this.highlightText(this.escapeHtml(fullText), query)}</div>
                        <button class="search-hit-expand-btn">показать полностью ▾</button>
                    ` : ''}
                </div>
            `;

            if (isLong) {
                const expandBtn = div.querySelector('.search-hit-expand-btn');
                const fullDiv = div.querySelector('.search-hit-full');
                const previewDiv = div.querySelector('.search-hit-preview');
                expandBtn.addEventListener('click', () => {
                    const isVisible = fullDiv.style.display !== 'none';
                    fullDiv.style.display = isVisible ? 'none' : 'block';
                    previewDiv.style.display = isVisible ? 'block' : 'none';
                    expandBtn.textContent = isVisible ? 'показать полностью ▾' : 'свернуть ▴';
                });
            }

            div.querySelector('.search-hit-detail-btn').addEventListener('click', () => {
                this.openChunkModal(hit);
            });

            this.searchResults.appendChild(div);
        }
    }

    openChunkModal(hit) {
        if (!this.chunkModal) return;
        const meta = hit.metadata || {};
        const rows = [
            ['chunk_id', hit.chunk_id],
            ['document_id', hit.document_id],
            ['vault_id', meta.vault_id || hit.vault_id],
            ['source_path', meta.source_path],
            ['page_number', meta.page_number],
            ['section', meta.headers?.section],
            ['content_type', meta.content_type],
            ['score', typeof hit.score === 'number' ? hit.score.toFixed(5) : hit.score],
            ['checksum', meta.checksum],
            ['extension', meta.extension],
            ['domain_id', meta.domain_id],
            ['source_hint', meta.source_hint],
            ['tags', Array.isArray(meta.tags) ? meta.tags.join(', ') : meta.tags],
        ].filter(([, v]) => v != null && v !== '' && v !== undefined);

        const tableRows = rows.map(([k, v]) =>
            `<tr><td class="chunk-prop-key">${this.escapeHtml(k)}</td><td class="chunk-prop-val">${this.escapeHtml(String(v))}</td></tr>`
        ).join('');

        this.chunkModalContent.innerHTML = `
            <h4 class="chunk-modal-title">Свойства чанка</h4>
            <table class="chunk-props-table">${tableRows}</table>
            <div class="chunk-modal-section-label">Текст</div>
            <pre class="chunk-modal-text">${this.escapeHtml(hit.text || '')}</pre>
        `;
        this.chunkModal.style.display = 'flex';
    }

    closeChunkModal() {
        if (this.chunkModal) this.chunkModal.style.display = 'none';
    }

    highlightText(escapedHtml, query) {
        if (!query) return escapedHtml;
        const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        // query уже escapeHtml не нужен здесь — ищем в уже-escaped HTML
        const regex = new RegExp(`(${escapedQuery})`, 'gi');
        return escapedHtml.replace(regex, '<mark>$1</mark>');
    }

    escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    debounce(fn, ms) {
        let t;
        return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); };
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dbManager = new DBManager();
});
