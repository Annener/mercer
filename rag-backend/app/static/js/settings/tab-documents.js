const DocumentsTabMixin = {
    _docsCurrentDoc: null,
    _docsAllTags: [],
    _docsCurrentTags: [],
    _docsAllDocs: [],
    _docsFilterStatus: '',
    _docsFilterTagId: '',
    _docsIndexTaskId: null,
    _docsIndexPollTimer: null,
    _docsIndexWs: null,
    _docsOpenDirs: null,

    async renderDocumentsTab() {
        return `
        <div class="docs-toolbar">
            <div class="docs-toolbar-left">
                <button class="btn btn-primary docs-toolbar-btn" data-action="run-indexer">▶ Запустить индексацию</button>
                <input type="text" id="docs-search-input" placeholder="🔍 поиск по имени..." class="input-field docs-toolbar-input">
                <select id="docs-status-filter" class="input-field docs-toolbar-select">
                    <option value="">Все статусы</option>
                    <option value="indexed">indexed</option>
                    <option value="pending">pending</option>
                    <option value="error">error</option>
                </select>
                <select id="docs-tag-filter" class="input-field docs-toolbar-select">
                    <option value="">Все теги</option>
                </select>
            </div>
        </div>
        <div id="docs-index-progress-panel" class="docs-index-progress-panel" style="display:none;"></div>
        <div class="docs-layout">
            <div class="docs-table-wrap">
                <table class="data-table" id="docs-table">
                    <tbody id="docs-tbody">
                        <tr><td colspan="1" class="empty-state">Загрузка...</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="docs-tags-panel" id="docs-tags-panel">
                <div class="docs-tags-panel-header">Теги домена</div>
                <div id="docs-tags-panel-list" class="docs-tags-panel-list">Загрузка...</div>
                <div class="docs-tags-panel-create">
                    <div class="docs-tag-create-row">
                        <input type="text" id="new-tag-name" placeholder="Название" class="input-field docs-tag-name-input">
                        <input type="color" id="new-tag-color" value="#01696f" class="docs-tag-color-input" title="Цвет">
                        <button class="btn btn-primary docs-tag-add-btn" data-action="create-tag">➕</button>
                    </div>
                </div>
            </div>
        </div>`;
    },

    async loadDocumentsData() {
        const vaultId  = await this._resolveVaultId();
        const domainId = this._activeDomainId || await this._resolveDomainId();
        const tbody = document.getElementById('docs-tbody');

        if (!vaultId && !domainId) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="1" class="empty-state">Vault не найден. Добавьте vault в настройках.</td></tr>';
            return;
        }

        try {
            const docs = await this.api.getSettingsDocuments({
                vaultId:  vaultId  || null,
                domainId: vaultId  ? null : domainId,
                status:   this._docsFilterStatus  || null,
                tagId:    this._docsFilterTagId   || null,
            });

            this._docsAllDocs = Array.isArray(docs) ? docs : (docs.documents || []);
            this._renderDocsRows(this._docsAllDocs);

            const inp = document.getElementById('docs-search-input');
            if (inp) inp.oninput = () => this._filterDocsTable(inp.value);

            const statusSel = document.getElementById('docs-status-filter');
            if (statusSel) {
                statusSel.value = this._docsFilterStatus || '';
                statusSel.onchange = () => { this._docsFilterStatus = statusSel.value; this.loadDocumentsData(); };
            }

            if (domainId) {
                await this._loadTagFilterOptions(domainId);
                await this._refreshTagsPanel(domainId);
            }
        } catch (e) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="1" class="empty-state" style="color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</td></tr>`;
        }
    },

    async _loadTagFilterOptions(domainId) {
        const sel = document.getElementById('docs-tag-filter');
        if (!sel) return;
        try {
            const resp = await this.api.getTags(domainId);
            const allTags = [
                ...(Array.isArray(resp) ? resp : (resp.global_tags || [])),
                ...Object.values((resp && resp.by_campaign) || {}).flat(),
            ];
            const currentVal = this._docsFilterTagId || '';
            sel.innerHTML = '<option value="">Все теги</option>' +
                allTags.map(t => `<option value="${this.escapeHtml(String(t.id))}" ${String(t.id) === currentVal ? 'selected' : ''}>${this.escapeHtml(t.name)}</option>`).join('');
            sel.onchange = () => { this._docsFilterTagId = sel.value; this.loadDocumentsData(); };
        } catch (_) {}
    },

    // ─── Панель тегов домена ────────────────────────────────────────────────

    async _refreshTagsPanel(domainId) {
        const listEl = document.getElementById('docs-tags-panel-list');
        if (!listEl) return;
        try {
            const resp = await this.api.getTags(domainId);
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);

            if (!globalTags.length) {
                listEl.innerHTML = '<span class="docs-tags-empty">Тегов нет</span>';
            } else {
                listEl.innerHTML = globalTags.map(t => `
                    <div class="docs-tag-row">
                        <span class="badge" style="background:${t.color || 'var(--color-primary)'};color:white;flex:1;overflow:hidden;text-overflow:ellipsis;">${this.escapeHtml(t.name)}</span>
                        <input type="color" value="${t.color || '#01696f'}" data-tag-edit-color="${String(t.id)}" class="docs-tag-color-input" title="Цвет тега">
                        <button class="btn btn-xs" data-action="edit-tag-name" data-tag-id="${String(t.id)}" data-tag-name="${this.escapeHtml(t.name)}" title="Переименовать">✏️</button>
                        <button class="btn btn-xs" style="color:var(--color-error);" data-action="delete-tag" data-tag-id="${String(t.id)}" data-tag-name="${this.escapeHtml(t.name)}" title="Удалить">🗑</button>
                    </div>`).join('');
            }

            listEl.querySelectorAll('[data-tag-edit-color]').forEach(inp => {
                inp.addEventListener('change', async () => {
                    try { await this.api.updateTag(inp.dataset.tagEditColor, { color: inp.value }); await this._refreshTagsPanel(domainId); await this.loadDocumentsData(); }
                    catch (e) { alert('Ошибка цвета: ' + e.message); }
                });
            });

            listEl.querySelectorAll('[data-action="edit-tag-name"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const newName = prompt('Новое название:', btn.dataset.tagName);
                    if (!newName || !newName.trim()) return;
                    try { await this.api.updateTag(btn.dataset.tagId, { name: newName.trim() }); await this._refreshTagsPanel(domainId); }
                    catch (e) { alert('Ошибка: ' + e.message); }
                });
            });

            listEl.querySelectorAll('[data-action="delete-tag"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm(`Удалить тег «${btn.dataset.tagName}»?`)) return;
                    try { await this.api.deleteTag(btn.dataset.tagId); await this._refreshTagsPanel(domainId); await this.loadDocumentsData(); }
                    catch (e) { alert('Ошибка удаления: ' + e.message); }
                });
            });

            const createBtn = document.querySelector('[data-action="create-tag"]');
            if (createBtn && !createBtn._bound) {
                createBtn._bound = true;
                createBtn.addEventListener('click', async () => {
                    const nameInp  = document.getElementById('new-tag-name');
                    const colorInp = document.getElementById('new-tag-color');
                    const name = nameInp?.value?.trim();
                    if (!name) return;
                    try {
                        await this.api.createTag({ name, color: colorInp?.value || '#01696f', domain_id: domainId });
                        if (nameInp) nameInp.value = '';
                        await this._refreshTagsPanel(domainId);
                        await this._loadTagFilterOptions(domainId);
                    } catch (e) { alert('Ошибка создания: ' + e.message); }
                });
            }
        } catch (e) {
            if (listEl) listEl.innerHTML = `<span style="color:var(--color-error);font-size:var(--text-xs);">Ошибка: ${this.escapeHtml(e.message)}</span>`;
        }
    },

    // ─── Дерево документов ──────────────────────────────────────────────────

    _buildDocsTree(docs) {
        const root = { _isDir: true, children: {} };
        for (const doc of docs) {
            const fullPath = doc.source_path || doc.path || String(doc.id);
            const parts = fullPath.split('/').filter(Boolean);
            let node = root;
            for (let i = 0; i < parts.length - 1; i++) {
                const seg = parts[i];
                if (!node.children[seg]) node.children[seg] = { _isDir: true, children: {} };
                node = node.children[seg];
            }
            const fileName = parts[parts.length - 1] || String(doc.id);
            node.children[fileName] = { _isDir: false, doc };
        }
        return root;
    },

    _matchedAncestors(docs) {
        const set = new Set();
        for (const doc of docs) {
            const parts = (doc.source_path || doc.path || '').split('/').filter(Boolean);
            let prefix = '';
            for (let i = 0; i < parts.length - 1; i++) {
                prefix = prefix ? prefix + '/' + parts[i] : parts[i];
                set.add(prefix);
            }
        }
        return set;
    },

    _renderDocsTree(node, container, depth, openDirs) {
        const entries = Object.entries(node.children || {}).sort(([aName, aNode], [bName, bNode]) => {
            if (aNode._isDir !== bNode._isDir) return aNode._isDir ? -1 : 1;
            return aName.localeCompare(bName, 'ru');
        });

        for (const [name, child] of entries) {
            if (child._isDir) {
                const parentPrefix = container._pathPrefix || '';
                const dirKey = parentPrefix ? parentPrefix + '/' + name : name;
                const isOpen = openDirs.has(dirKey);

                const countFiles = (n) => Object.values(n.children || {})
                    .reduce((s, c) => s + (c._isDir ? countFiles(c) : 1), 0);

                const dirRow = document.createElement('tr');
                dirRow.className = 'docs-dir-row';
                dirRow.dataset.dirKey = dirKey;
                dirRow.innerHTML = `
                    <td colspan="1" class="docs-dir-cell" style="padding-left:${8 + depth * 18}px;">
                        <span class="docs-dir-toggle">${isOpen ? '▾' : '▸'}</span>
                        <span class="docs-dir-icon">📁</span>
                        <span class="docs-dir-name">${this.escapeHtml(name)}</span>
                        <span class="docs-dir-count">(${countFiles(child)})</span>
                    </td>`;
                container.appendChild(dirRow);

                const childGroup = document.createElement('tbody');
                childGroup.className = 'docs-dir-children';
                childGroup.dataset.parent = dirKey;
                childGroup._pathPrefix = dirKey;
                childGroup.style.display = isOpen ? '' : 'none';

                dirRow.addEventListener('click', () => {
                    const nowOpen = childGroup.style.display !== 'none';
                    childGroup.style.display = nowOpen ? 'none' : '';
                    dirRow.querySelector('.docs-dir-toggle').textContent = nowOpen ? '▸' : '▾';
                    if (nowOpen) openDirs.delete(dirKey); else openDirs.add(dirKey);
                });

                dirRow.after(childGroup);
                this._renderDocsTree(child, childGroup, depth + 1, openDirs);

            } else {
                const doc = child.doc;
                const tags = (doc.tags || []).map(t =>
                    `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:var(--color-text);">${this.escapeHtml(t.name)}</span>`
                ).join('');

                const row = document.createElement('tr');
                row.className = 'docs-row';
                row.dataset.id   = String(doc.id);
                row.dataset.path = doc.source_path || String(doc.id);
                row.style.cursor = 'pointer';
                row.title = 'Нажмите для редактирования тегов';
                row.innerHTML = `
                    <td style="padding-left:${8 + depth * 18}px;" title="${this.escapeHtml(doc.source_path || String(doc.id))}">
                        <div class="docs-file-row">
                            <span class="docs-file-name">
                                <span class="docs-file-icon">📄</span>${this.escapeHtml(name)}
                            </span>
                            <span class="docs-file-tags">
                                ${tags || '<span style="color:var(--color-text-faint)">—</span>'}
                            </span>
                        </div>
                    </td>`;

                row.addEventListener('click', () => {
                    this._openDocModal(doc);
                });
                container.appendChild(row);
            }
        }
    },

    _renderDocsRows(docs) {
        const tableEl = document.getElementById('docs-table');
        if (!tableEl) return;

        tableEl.querySelectorAll('tbody').forEach(b => b.remove());

        if (!docs || !docs.length) {
            const empty = document.createElement('tbody');
            empty.innerHTML = '<tr><td colspan="1" class="empty-state">Документов нет</td></tr>';
            tableEl.appendChild(empty);
            return;
        }

        const tree = this._buildDocsTree(docs);

        const isFiltered = docs !== this._docsAllDocs;
        if (!this._docsOpenDirs) this._docsOpenDirs = new Set();
        const openDirs = isFiltered ? this._matchedAncestors(docs) : this._docsOpenDirs;

        const rootBody = document.createElement('tbody');
        rootBody._pathPrefix = '';
        tableEl.appendChild(rootBody);
        this._renderDocsTree(tree, rootBody, 0, openDirs);
    },

    _docStatusBadge(status) {
        const map = {
            indexed: { bg: '#e6f5ee', color: '#206a43', label: 'indexed' },
            pending: { bg: '#fff7e0', color: '#7a5700', label: 'pending' },
            error:   { bg: '#fdecea', color: '#a12c7b', label: 'error' },
            indexing:{ bg: '#e8f0fd', color: '#1a4fa3', label: 'indexing' },
        };
        const s = map[status] || { bg: '#eef2f6', color: '#657789', label: status || '—' };
        return `<span class="doc-status-badge" style="background:${s.bg};color:${s.color};">${this.escapeHtml(s.label)}</span>`;
    },

    _filterDocsTable(query) {
        const q = (query || '').toLowerCase();
        const filtered = q
            ? (this._docsAllDocs || []).filter(d => (d.source_path || d.path || '').toLowerCase().includes(q))
            : this._docsAllDocs;
        this._renderDocsRows(filtered);
    },

    // ─── Вспомогательная: разбор списка файлов из TaskStateResponse ──────────

    _parseTaskStateFiles(resp) {
        const s = resp?.state || resp || {};
        const filesInState = s.files || {};
        const fileList = Array.isArray(filesInState)
            ? filesInState
            : Object.entries(filesInState).map(([path, info]) => ({ path, ...info }));
        const files = {};
        let doneCount = 0;
        for (const f of fileList) {
            const path = f.path || f.file_path || '';
            if (!path) continue;
            files[path] = {
                status:       f.status || 'pending',
                chunks_done:  f.chunks_sent || f.chunks_done || 0,
                chunks_total: f.chunks_total || 0,
                name:         path.split('/').pop(),
            };
            if (f.status === 'indexed' || f.status === 'done') doneCount++;
        }
        return { files, total: fileList.length, done: doneCount, status: s.status };
    },

    // ─── Прогресс-панель индексации ──────────────────────────────────────────

    _renderIndexProgress(state) {
        const panel = document.getElementById('docs-index-progress-panel');
        if (!panel) return;
        if (!state) { panel.style.display = 'none'; return; }

        panel.style.display = 'block';

        const total = state.total || 0;
        const done  = state.done  || 0;
        const pct   = total > 0 ? Math.round((done / total) * 100) : 0;
        const isActive = state.status === 'running' || state.status === 'queued';

        const statusLabel = {
            running:   '⚙️ Индексация…',
            queued:    '⏳ Очередь…',
            completed: '✅ Готово',
            failed:    '❌ Ошибка',
            cancelled: '⛔ Отменено',
        }[state.status] || state.status;

        const filesHtml = Object.entries(state.files || {}).map(([path, f]) => {
            const name = f.name || path.split('/').pop();
            const ct = f.chunks_total || 0;
            const cd = f.chunks_done  || 0;
            const fp = ct > 0 ? Math.round((cd / ct) * 100) : 0;
            const fIsActive = f.status === 'indexing';
            return `
            <div class="idx-file-row">
                <div class="idx-file-header">
                    <span class="idx-file-name" title="${this.escapeHtml(path)}">${this.escapeHtml(name)}</span>
                    ${this._docStatusBadge(f.status)}
                    ${ct > 0 ? `<span class="idx-file-chunks">${cd}/${ct} чанков</span>` : ''}
                </div>
                ${(fIsActive || ct > 0) ? `
                <div class="idx-file-bar-wrap">
                    <div class="idx-bar idx-bar-file ${fIsActive ? 'idx-bar-anim' : ''}" style="width:${fp}%;"></div>
                </div>` : ''}
            </div>`;
        }).join('');

        panel.innerHTML = `
        <div class="idx-panel-inner">
            <div class="idx-global-header">
                <span class="idx-status-label">${statusLabel}</span>
                ${total > 0 ? `<span class="idx-global-count">${done} / ${total} файлов</span>` : ''}
                ${total > 0 ? `<span class="idx-pct">${pct}%</span>` : ''}
                ${isActive ? `<button class="btn btn-sm idx-cancel-btn" data-action="cancel-indexer" style="margin-left:auto;">✕ Отмена</button>` : ''}
            </div>
            ${total > 0 ? `
            <div class="idx-global-bar-wrap">
                <div class="idx-bar ${isActive ? 'idx-bar-anim' : ''}" style="width:${pct}%;"></div>
            </div>` : ''}
            ${filesHtml ? `<div class="idx-files-list">${filesHtml}</div>` : ''}
            ${state.error ? `<div style="color:var(--color-error);font-size:var(--text-xs);margin-top:8px;">${this.escapeHtml(state.error)}</div>` : ''}
        </div>`;

        const cancelBtn = panel.querySelector('[data-action="cancel-indexer"]');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', async () => {
                try {
                    if (this._docsIndexTaskId) await this.api.cancelIndexTask(this._docsIndexTaskId);
                    if (this._docsIndexWs) { this._docsIndexWs.close(); this._docsIndexWs = null; }
                    if (this._docsIndexPollTimer) { clearInterval(this._docsIndexPollTimer); this._docsIndexPollTimer = null; }
                    this._renderIndexProgress({ status: 'cancelled', total, done, files: state.files || {} });
                } catch (e) { alert('Ошибка отмены: ' + e.message); }
            });
        }
    },

    // ─── WebSocket + polling для индексатора ────────────────────────────────

    _startIndexerWs(taskId) {
        const state = { status: 'running', total: 0, done: 0, files: {} };
        this._renderIndexProgress(state);

        const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl   = `${wsProto}://${location.host}/api/v1/indexer/tasks/${taskId}/ws`;

        let ws;
        try { ws = new WebSocket(wsUrl); } catch (_) { this._pollIndexerStatus(taskId, state); return; }
        this._docsIndexWs = ws;

        ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                const parsed = this._parseTaskStateFiles(msg);
                if (parsed.total > 0) {
                    state.files = parsed.files;
                    state.total = parsed.total;
                    state.done  = parsed.done;
                    state.status = parsed.status || state.status;
                } else {
                    state.status = msg?.status || msg?.state?.status || state.status;
                }
            } catch (_) {}
            this._renderIndexProgress(state);
        };

        ws.onerror = () => {
            this._docsIndexWs = null;
            this._pollIndexerStatus(taskId, state);
        };

        ws.onclose = () => {
            this._docsIndexWs = null;
            if (state.status !== 'completed' && state.status !== 'failed' && state.status !== 'cancelled') {
                this.loadDocumentsData();
            }
        };
    },

    _pollIndexerStatus(taskId, state) {
        if (this._docsIndexPollTimer) clearInterval(this._docsIndexPollTimer);
        let attempts = 0;
        this._docsIndexPollTimer = setInterval(async () => {
            attempts++;
            try {
                const resp = await this.api.getIndexTaskState(taskId);
                const parsed = this._parseTaskStateFiles(resp);
                if (parsed.total > 0) {
                    if (state) {
                        state.files = parsed.files;
                        state.total = parsed.total;
                        state.done  = parsed.done;
                        state.status = parsed.status || state.status;
                    }
                } else if (state) {
                    const st = resp?.status || resp?.state?.status || 'unknown';
                    state.status = st;
                }
                if (state) this._renderIndexProgress(state);
                const st = state?.status || 'unknown';
                if (['completed', 'failed', 'cancelled', 'done', 'error', 'SUCCESS', 'FAILURE'].includes(st) || attempts > 120) {
                    clearInterval(this._docsIndexPollTimer);
                    this._docsIndexPollTimer = null;
                    await this.loadDocumentsData();
                }
            } catch (_) {
                if (attempts > 20) { clearInterval(this._docsIndexPollTimer); this._docsIndexPollTimer = null; }
            }
        }, 3000);
    },

    // ─── Модальное окно документа ───────────────────────────────────────────

    async _openDocModal(doc) {
        this._docsCurrentDoc = doc;
        const domainId = this._activeDomainId || await this._resolveDomainId();

        document.getElementById('docs-modal-backdrop')?.remove();

        const backdrop = document.createElement('div');
        backdrop.id = 'docs-modal-backdrop';
        backdrop.className = 'docs-modal-backdrop';

        const fileName = (doc.source_path || doc.path || String(doc.id)).split('/').pop();
        const fullPath = doc.source_path || doc.path || '—';

        const metaRows = [
            ['ID',          doc.id           || '—'],
            ['Vault',       doc.vault_id     || '—'],
            ['Путь',       fullPath],
            ['Статус',     doc.status       || '—'],
            ['Мим-тип',   doc.mime_type    || '—'],
            ['Размер',     doc.file_size != null ? `${(doc.file_size / 1024).toFixed(1)} KB` : '—'],
            ['Страниц',  doc.page_count   != null ? doc.page_count : '—'],
            ['Чанков',   doc.chunk_count  != null ? doc.chunk_count : '—'],
            ['Добавлен', doc.created_at ? new Date(doc.created_at).toLocaleString('ru') : '—'],
            ['Изменён',  doc.updated_at ? new Date(doc.updated_at).toLocaleString('ru') : '—'],
        ].filter(([, v]) => v && v !== '—');

        backdrop.innerHTML = `
        <div class="docs-modal" role="dialog" aria-modal="true" aria-label="Информация о документе">
            <div class="docs-modal-header">
                <div class="docs-modal-title">
                    <span class="docs-modal-filename">${this.escapeHtml(fileName)}</span>
                </div>
                <button class="docs-modal-close" data-action="close-modal" aria-label="Закрыть">✕</button>
            </div>
            <div class="docs-modal-body">
                <div class="docs-modal-left">
                    <div class="docs-modal-section-title">Информация</div>
                    <table class="docs-modal-meta">
                        ${metaRows.map(([k, v]) => `<tr><td class="docs-modal-meta-key">${this.escapeHtml(String(k))}</td><td class="docs-modal-meta-val">${this.escapeHtml(String(v))}</td></tr>`).join('')}
                    </table>
                </div>
                <div class="docs-modal-right">
                    <div class="docs-modal-section-title">Теги</div>
                    <div id="docs-modal-tags-loading" style="color:var(--color-text-muted);font-size:13px;">Загрузка...</div>
                    <div id="docs-modal-tags-wrap" style="display:none;">
                        <div id="docs-modal-tag-badges" class="docs-modal-tag-badges"></div>
                        <div class="docs-modal-footer-btns">
                            <button class="btn btn-primary docs-modal-save-btn" data-action="save-doc-tags">Сохранить теги</button>
                            <button class="btn docs-modal-delete-btn" data-action="delete-doc-modal"
                                data-id="${this.escapeHtml(String(doc.id))}"
                                data-vault="${this.escapeHtml(doc.vault_id || '')}"
                                data-path="${this.escapeHtml(doc.source_path || String(doc.id))}">🗑 Удалить</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;

        document.body.appendChild(backdrop);
        document.body.style.overflow = 'hidden';

        const closeModal = () => {
            backdrop.remove();
            document.body.style.overflow = '';
        };
        backdrop.addEventListener('click', e => { if (e.target === backdrop) closeModal(); });
        backdrop.querySelector('[data-action="close-modal"]').addEventListener('click', closeModal);
        const deleteModalBtn = backdrop.querySelector('[data-action="delete-doc-modal"]');
        if (deleteModalBtn) {
            deleteModalBtn.addEventListener('click', async () => {
                const docId   = deleteModalBtn.dataset.id;
                const vaultId = deleteModalBtn.dataset.vault;
                const path    = deleteModalBtn.dataset.path;
                if (!confirm(`Удалить документ «${path || docId}»?`)) return;
                try {
                    await this.api.deleteDocumentById(docId, vaultId || null);
                    closeModal();
                    await this.loadDocumentsData();
                } catch (e) { alert('Ошибка удаления: ' + e.message); }
            });
        }
        const escHandler = e => { if (e.key === 'Escape') { closeModal(); document.removeEventListener('keydown', escHandler); } };
        document.addEventListener('keydown', escHandler);

        try {
            const resp = domainId ? await this.api.getTags(domainId) : [];
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);
            const byCampaign = (resp?.by_campaign) ? Object.values(resp.by_campaign).flat() : [];
            this._docsAllTags = [...globalTags, ...byCampaign];
            this._docsCurrentTags = (doc.tags || []).map(t => String(typeof t === 'object' ? t.id : t));

            document.getElementById('docs-modal-tags-loading').style.display = 'none';
            const wrap = document.getElementById('docs-modal-tags-wrap');
            wrap.style.display = 'block';

            const badgesEl = document.getElementById('docs-modal-tag-badges');
            this._renderModalTagBadges(badgesEl);

            wrap.querySelector('[data-action="save-doc-tags"]').addEventListener('click', async () => {
                try {
                    await this.api.updateDocumentLabels(String(doc.id), this._docsCurrentTags);
                    await this.loadDocumentsData();
                    closeModal();
                } catch (err) {
                    alert('Ошибка сохранения тегов: ' + err.message);
                }
            });
        } catch (e) {
            const loadEl = document.getElementById('docs-modal-tags-loading');
            if (loadEl) loadEl.textContent = 'Ошибка загрузки тегов: ' + e.message;
        }
    },

    _renderModalTagBadges(container) {
        if (!container) return;
        if (!this._docsAllTags.length) {
            container.innerHTML = '<span style="color:var(--color-text-faint);font-size:13px;">Тегов нет. Создайте тег в панели справа.</span>';
            return;
        }
        container.innerHTML = this._docsAllTags.map(t => {
            const tid = String(t.id);
            const on  = this._docsCurrentTags.includes(tid);
            return `<span class="badge docs-modal-tag-toggle ${on ? 'is-active' : ''}" data-tag-id="${tid}"
                style="background:${on ? (t.color || 'var(--color-primary)') : 'var(--color-surface-offset)'};
                       color:${on ? 'white' : 'var(--color-text)'};
                       border:1px solid ${on ? (t.color || 'var(--color-primary)') : 'var(--color-border)'};
                       cursor:pointer;margin:2px;"
                data-color="${t.color || ''}"
            >${this.escapeHtml(t.name)}</span>`;
        }).join('');

        container.querySelectorAll('.docs-modal-tag-toggle').forEach(el => {
            el.addEventListener('click', () => {
                const tid = String(el.dataset.tagId);
                const on  = this._docsCurrentTags.includes(tid);
                if (on) {
                    this._docsCurrentTags = this._docsCurrentTags.filter(x => x !== tid);
                    el.style.background = 'var(--color-surface-offset)';
                    el.style.color      = 'var(--color-text)';
                    el.style.border     = '1px solid var(--color-border)';
                } else {
                    this._docsCurrentTags.push(tid);
                    const color = el.dataset.color || 'var(--color-primary)';
                    el.style.background = color;
                    el.style.color      = 'white';
                    el.style.border     = `1px solid ${color}`;
                }
            });
        });
    },

    // ─── Actions ─────────────────────────────────────────────────────────

    async handleDocumentsAction(action, btn) {
        if (action === 'run-indexer') {
            const runBtn = document.querySelector('[data-action="run-indexer"]');
            if (runBtn) { runBtn.disabled = true; runBtn.textContent = '⏳ Запуск…'; }
            try {
                const result = await this.api.runIndexer();
                const taskId = result?.task_id || result?.id || null;
                this._docsIndexTaskId = taskId;
                if (runBtn) { runBtn.disabled = false; runBtn.textContent = '▶ Запустить индексацию'; }
                if (taskId) {
                    this._startIndexerWs(taskId);
                } else {
                    this._renderIndexProgress({ status: 'completed', total: 0, done: 0, files: {} });
                    await this.loadDocumentsData();
                }
            } catch (e) {
                if (runBtn) { runBtn.disabled = false; runBtn.textContent = '▶ Запустить индексацию'; }
                this._renderIndexProgress({ status: 'failed', total: 0, done: 0, files: {}, error: e.message });
            }
            return;
        }
    },

    async _resolveVaultId() {
        if (this._activeVaultId) return this._activeVaultId;
        try {
            const vaults = await this.api.getSettingsVaults();
            const list = Array.isArray(vaults) ? vaults : [];
            const active = list.find(v => v.is_active) || list[0];
            return active ? (active.vault_id || active.id || null) : null;
        } catch (_) { return null; }
    },

    async _resolveDomainId() {
        if (this._activeDomainId) return this._activeDomainId;
        try {
            const resp = await this.api.getDomains();
            const list = Array.isArray(resp) ? resp : (resp.domains || []);
            const first = list.find(d => d.enabled !== false) || list[0];
            return first ? (first.domain_id || first.id || null) : null;
        } catch (_) { return null; }
    },
};

Object.assign(SettingsManager.prototype, DocumentsTabMixin);
