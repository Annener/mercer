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

    /** Shorthand: contrast text color for a given bg hex/css-var */
    _tc(color) {
        return typeof _textColor === 'function' ? _textColor(color) : 'white';
    },

    async renderDocumentsTab() {
        // Загружаем домены для domain-selector
        let domains = [];
        try {
            const dr = await this.api.getSettingsDomains();
            domains = Array.isArray(dr) ? dr : (dr.domains || []);
        } catch (_) {}

        const domainId = this._activeDomainId || null;

        const domainSelector = `
            <select id="docs-domain-select" class="input-field" style="max-width:200px;height:36px;">
                <option value="">Все домены</option>
                ${domains.map(d => {
                    const did = this.escapeHtml(d.domain_id || d.id || '');
                    const dname = this.escapeHtml(d.display_name || d.domain_id || d.id || '');
                    const sel = (d.domain_id || d.id) === domainId ? ' selected' : '';
                    return `<option value="${did}"${sel}>${dname}</option>`;
                }).join('')}
            </select>`;

        return `
        <div class="docs-toolbar">
            <div class="docs-toolbar-left">
                <button class="btn btn-primary docs-toolbar-btn" data-action="run-indexer">▶ Запустить индексацию</button>
                ${domainSelector}
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

    _attachDocumentsTabListeners(container) {
        const sel = container.querySelector('#docs-domain-select');
        if (sel) {
            sel.addEventListener('change', () => {
                this._activeDomainId = sel.value || null;
                // Сбрасываем фильтр тегов при смене домена — теги домен-зависимы
                this._docsFilterTagId = '';
                this.loadDocumentsData();
            });
        }
    },

    async loadDocumentsData() {
        const tbody = document.getElementById('docs-tbody');

        // --- Приоритеты фильтрации ---
        // 1. Явно выбранный домен (_activeDomainId) → передаём только domain_id,
        //    vault не резолвим вообще, чтобы не «перебить» фильтр.
        // 2. Явно выбранный vault (_activeVaultId) → передаём vault_id.
        // 3. Ни то ни другое → резолвим vault как fallback (старое поведение).

        let requestVaultId  = null;
        let requestDomainId = null;

        if (this._activeDomainId) {
            // Домен выбран явно — фильтруем по нему
            requestDomainId = this._activeDomainId;
        } else if (this._activeVaultId) {
            // Vault выбран явно
            requestVaultId = this._activeVaultId;
        } else {
            // Fallback: резолвим vault (старое поведение для первой загрузки)
            requestVaultId = await this._resolveVaultId();
            if (!requestVaultId) {
                // Vault не нашли — пробуем domain
                requestDomainId = await this._resolveDomainId();
            }
        }

        if (!requestVaultId && !requestDomainId) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="1" class="empty-state">Vault не найден. Добавьте vault в настройках.</td></tr>';
            return;
        }

        try {
            const docs = await this.api.getSettingsDocuments({
                vaultId:  requestVaultId  || null,
                domainId: requestDomainId || null,
                status:   this._docsFilterStatus || null,
                tagId:    this._docsFilterTagId  || null,
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

            // Теги панель и фильтр — только если знаем домен
            const effectiveDomainId = requestDomainId || await this._resolveDomainIdForVault(requestVaultId);
            if (effectiveDomainId) {
                await this._loadTagFilterOptions(effectiveDomainId);
                await this._refreshTagsPanel(effectiveDomainId);
            }
        } catch (e) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="1" class="empty-state" style="color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</td></tr>`;
        }
    },

    /** Резолвит domain_id по известному vault_id (для тегов-панели при fallback). */
    async _resolveDomainIdForVault(vaultId) {
        if (!vaultId) return null;
        try {
            const resp = await this.api.getSettingsVaults();
            const list = Array.isArray(resp) ? resp : [];
            const vault = list.find(v => (v.vault_id || v.id) === vaultId);
            return vault?.domain_id || null;
        } catch (_) { return null; }
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

    async _refreshTagsPanel(domainId) {
        const listEl = document.getElementById('docs-tags-panel-list');
        const panelEl = document.getElementById('docs-tags-panel');
        if (!listEl) return;
        try {
            const resp = await this.api.getTags(domainId);
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);

            if (!globalTags.length) {
                listEl.innerHTML = '<span class="docs-tags-empty">Тегов нет</span>';
                if (panelEl) panelEl.style.width = '';
            } else {
                listEl.innerHTML = globalTags.map(t => {
                    const color = t.color || '#01696f';
                    return `
                    <div class="docs-tag-row">
                        <button class="badge badge--panel badge--active docs-domain-tag-trigger"
                                type="button"
                                data-tag-id="${String(t.id)}"
                                data-tag-name="${this.escapeHtml(t.name)}"
                                data-tag-color="${color}"
                                title="Редактировать тег"
                                style="background:${color};color:${this._tc(color)};border-color:${color};"
                        >${this.escapeHtml(t.name)}</button>
                    </div>`;
                }).join('');

                requestAnimationFrame(() => {
                    const widest = Array.from(listEl.querySelectorAll('.docs-domain-tag-trigger'))
                        .reduce((max, el) => Math.max(max, Math.ceil(el.getBoundingClientRect().width)), 0);
                    if (panelEl && widest > 0) {
                        const targetWidth = Math.min(Math.max(widest + 96, 260), 520);
                        panelEl.style.width = `${targetWidth}px`;
                    }
                });
            }

            listEl.querySelectorAll('.docs-domain-tag-trigger').forEach(btn => {
                btn.addEventListener('click', () => {
                    this._openDomainTagModal({
                        id: btn.dataset.tagId,
                        name: btn.dataset.tagName,
                        color: btn.dataset.tagColor,
                        domainId,
                    });
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
                        await this.loadDocumentsData();
                    } catch (e) { alert('Ошибка создания: ' + e.message); }
                });
            }
        } catch (e) {
            if (listEl) listEl.innerHTML = `<span style="color:var(--color-error);font-size:var(--text-xs);">Ошибка: ${this.escapeHtml(e.message)}</span>`;
        }
    },

    _openDomainTagModal(tag) {
        document.getElementById('docs-domain-tag-modal-backdrop')?.remove();

        const initialColor = tag.color || '#01696f';

        const backdrop = document.createElement('div');
        backdrop.id = 'docs-domain-tag-modal-backdrop';
        backdrop.className = 'docs-modal-backdrop';
        backdrop.innerHTML = `
        <div class="docs-modal docs-domain-tag-modal" role="dialog" aria-modal="true" aria-label="Редактирование тега домена">
            <div class="docs-modal-header">
                <div class="docs-modal-title">
                    <span class="docs-modal-filename">Тег домена</span>
                </div>
                <button class="docs-modal-close" data-action="close-domain-tag-modal" aria-label="Закрыть">✕</button>
            </div>
            <div class="docs-domain-tag-modal-body">
                <label class="docs-domain-tag-field">
                    <span class="docs-domain-tag-label">Название</span>
                    <input type="text" id="docs-domain-tag-name" class="input-field docs-domain-tag-name" value="${this.escapeHtml(tag.name || '')}">
                </label>
                <label class="docs-domain-tag-field docs-domain-tag-field--color">
                    <span class="docs-domain-tag-label">Цвет</span>
                    <div class="docs-domain-tag-color-row">
                        <input type="color" id="docs-domain-tag-color" class="docs-tag-color-input" value="${this.escapeHtml(initialColor)}" title="Цвет тега">
                        <span class="badge badge--modal" id="docs-domain-tag-preview"
                              style="background:${initialColor};color:${this._tc(initialColor)};border-color:${initialColor};"
                        >${this.escapeHtml(tag.name || 'Тег')}</span>
                    </div>
                </label>
                <div class="docs-domain-tag-actions">
                    <button class="btn btn-primary" data-action="save-domain-tag">Сохранить</button>
                    <button class="btn docs-domain-tag-delete-btn" data-action="delete-domain-tag">Удалить</button>
                </div>
            </div>
        </div>`;

        document.body.appendChild(backdrop);
        document.body.style.overflow = 'hidden';

        const closeModal = () => {
            backdrop.remove();
            document.body.style.overflow = '';
        };

        const nameInput  = backdrop.querySelector('#docs-domain-tag-name');
        const colorInput = backdrop.querySelector('#docs-domain-tag-color');
        const previewEl  = backdrop.querySelector('#docs-domain-tag-preview');

        const syncPreview = () => {
            const name  = nameInput?.value?.trim() || 'Тег';
            const color = colorInput?.value || '#01696f';
            if (previewEl) {
                previewEl.textContent  = name;
                previewEl.style.background  = color;
                previewEl.style.borderColor = color;
                previewEl.style.color       = this._tc(color);
            }
        };

        nameInput?.addEventListener('input', syncPreview);
        colorInput?.addEventListener('input', syncPreview);

        backdrop.addEventListener('click', e => { if (e.target === backdrop) closeModal(); });
        backdrop.querySelector('[data-action="close-domain-tag-modal"]').addEventListener('click', closeModal);

        const escHandler = e => {
            if (e.key === 'Escape') {
                closeModal();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        backdrop.querySelector('[data-action="save-domain-tag"]').addEventListener('click', async () => {
            const newName  = nameInput?.value?.trim();
            const newColor = colorInput?.value || '#01696f';
            if (!newName) {
                alert('Название тега не может быть пустым');
                nameInput?.focus();
                return;
            }
            try {
                await this.api.updateTag(tag.id, { name: newName, color: newColor });
                closeModal();
                await this._refreshTagsPanel(tag.domainId);
                await this._loadTagFilterOptions(tag.domainId);
                await this.loadDocumentsData();
            } catch (e) {
                alert('Ошибка сохранения: ' + e.message);
            }
        });

        backdrop.querySelector('[data-action="delete-domain-tag"]').addEventListener('click', async () => {
            if (!confirm(`Удалить тег «${tag.name}»?`)) return;
            try {
                await this.api.deleteTag(tag.id);
                closeModal();
                await this._refreshTagsPanel(tag.domainId);
                await this._loadTagFilterOptions(tag.domainId);
                await this.loadDocumentsData();
            } catch (e) {
                alert('Ошибка удаления: ' + e.message);
            }
        });
    },

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

    _collectDirDocs(node) {
        const result = [];
        for (const child of Object.values(node.children || {})) {
            if (child._isDir) {
                result.push(...this._collectDirDocs(child));
            } else {
                result.push(child.doc);
            }
        }
        return result;
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
                        <span class="docs-dir-toggle" title="Раскрыть / свернуть">${isOpen ? '▾' : '▸'}</span>
                        <span class="docs-dir-label" title="Управление тегами каталога">
                            <span class="docs-dir-icon">📁</span>
                            <span class="docs-dir-name">${this.escapeHtml(name)}</span>
                        </span>
                        <span class="docs-dir-count">(${countFiles(child)})</span>
                    </td>`;
                container.appendChild(dirRow);

                const childGroup = document.createElement('tbody');
                childGroup.className = 'docs-dir-children';
                childGroup.dataset.parent = dirKey;
                childGroup._pathPrefix = dirKey;
                childGroup.style.display = isOpen ? '' : 'none';

                dirRow.querySelector('.docs-dir-toggle').addEventListener('click', (e) => {
                    e.stopPropagation();
                    const nowOpen = childGroup.style.display !== 'none';
                    childGroup.style.display = nowOpen ? 'none' : '';
                    dirRow.querySelector('.docs-dir-toggle').textContent = nowOpen ? '▸' : '▾';
                    if (nowOpen) openDirs.delete(dirKey); else openDirs.add(dirKey);
                });

                dirRow.querySelector('.docs-dir-label').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this._openDirModal(name, child);
                });

                dirRow.after(childGroup);
                this._renderDocsTree(child, childGroup, depth + 1, openDirs);

            } else {
                const doc = child.doc;
                const tags = (doc.tags || []).map(t => {
                    const color = t.color || 'var(--color-primary)';
                    return `<span class="badge badge--file"
                               style="background:${color};color:${this._tc(color)};border-color:${color};"
                           >${this.escapeHtml(t.name)}</span>`;
                }).join('');

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

    async _openDirModal(dirName, dirNode) {
        const domainId = this._activeDomainId || await this._resolveDomainId();
        const allDocs = this._collectDirDocs(dirNode);

        document.getElementById('docs-dir-modal-backdrop')?.remove();

        const backdrop = document.createElement('div');
        backdrop.id = 'docs-dir-modal-backdrop';
        backdrop.className = 'docs-modal-backdrop';

        backdrop.innerHTML = `
        <div class="docs-modal docs-dir-modal" role="dialog" aria-modal="true" aria-label="Теги каталога">
            <div class="docs-modal-header">
                <div class="docs-modal-title">
                    <span class="docs-modal-filename">📁 ${this.escapeHtml(dirName)}</span>
                    <span class="docs-dir-modal-count">${allDocs.length} файл(ов)</span>
                </div>
                <button class="docs-modal-close" data-action="close-dir-modal" aria-label="Закрыть">✕</button>
            </div>
            <div class="docs-modal-body docs-dir-modal-body">
                <div id="docs-dir-modal-inner">
                    <div style="color:var(--color-text-muted);font-size:13px;">Загрузка тегов…</div>
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
        backdrop.querySelector('[data-action="close-dir-modal"]').addEventListener('click', closeModal);
        const escHandler = e => { if (e.key === 'Escape') { closeModal(); document.removeEventListener('keydown', escHandler); } };
        document.addEventListener('keydown', escHandler);

        try {
            const resp = domainId ? await this.api.getTags(domainId) : [];
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);
            const byCampaign = resp?.by_campaign ? Object.values(resp.by_campaign).flat() : [];
            const allTags = [...globalTags, ...byCampaign];

            this._renderDirModalInner(
                backdrop.querySelector('#docs-dir-modal-inner'),
                allTags,
                allDocs,
                closeModal
            );
        } catch (e) {
            const inner = backdrop.querySelector('#docs-dir-modal-inner');
            if (inner) inner.innerHTML = `<div style="color:var(--color-error);">Ошибка загрузки тегов: ${this.escapeHtml(e.message)}</div>`;
        }
    },

    _renderDirModalInner(container, allTags, allDocs, closeModal) {
        const tagDocCount = {};
        for (const doc of allDocs) {
            for (const t of (doc.tags || [])) {
                const tid = String(typeof t === 'object' ? t.id : t);
                tagDocCount[tid] = (tagDocCount[tid] || 0) + 1;
            }
        }

        const presentTagIds = Object.keys(tagDocCount);
        const presentTags = presentTagIds
            .map(tid => allTags.find(t => String(t.id) === tid))
            .filter(Boolean);

        const assignBadges = allTags.map(t => {
            const tid = String(t.id);
            const color = t.color || 'var(--color-primary)';
            const allHaveIt = tagDocCount[tid] === allDocs.length && allDocs.length > 0;
            const activeStyle   = `background:${color};color:${this._tc(color)};border-color:${color};`;
            const inactiveStyle = `background:var(--color-surface-offset);color:var(--color-text-faint);border-color:var(--color-border);`;
            return `<span
                class="badge badge--dir ${allHaveIt ? 'badge--inactive' : 'badge--active'} docs-dir-tag-assign ${allHaveIt ? 'is-disabled' : 'is-active'}"
                data-tag-id="${tid}"
                data-tag-color="${this.escapeHtml(color)}"
                style="${allHaveIt ? inactiveStyle : activeStyle}"
                title="${allHaveIt ? 'Все файлы уже имеют этот тег' : 'Назначить на все файлы каталога'}"
            >${this.escapeHtml(t.name)}</span>`;
        }).join('');

        const removeBadges = presentTags.length
            ? presentTags.map(t => {
                const tid = String(t.id);
                const color = t.color || 'var(--color-primary)';
                return `<span
                    class="badge badge--dir badge--removable docs-dir-tag-remove is-active"
                    data-tag-id="${tid}"
                    style="background:${color};color:${this._tc(color)};border-color:${color};"
                    title="Снять со всех файлов каталога где он есть"
                >${this.escapeHtml(t.name)}</span>`;
            }).join('')
            : '<span style="color:var(--color-text-faint);font-size:13px;">Нет тегов ни на одном файле</span>';

        container.innerHTML = `
            <div class="docs-dir-modal-section">
                <div class="docs-modal-section-title">Назначить тег на все файлы каталога</div>
                <div class="docs-dir-tag-list" id="docs-dir-assign-list">
                    ${allTags.length ? assignBadges : '<span style="color:var(--color-text-faint);font-size:13px;">Тегов нет</span>'}
                </div>
                <div id="docs-dir-assign-status" class="docs-dir-modal-status" style="display:none;"></div>
            </div>
            <div class="docs-dir-modal-divider"></div>
            <div class="docs-dir-modal-section">
                <div class="docs-modal-section-title">Снять тег со всех файлов каталога</div>
                <div class="docs-dir-tag-list" id="docs-dir-remove-list">
                    ${removeBadges}
                </div>
                <div id="docs-dir-remove-status" class="docs-dir-modal-status" style="display:none;"></div>
            </div>`;

        container.querySelectorAll('.docs-dir-tag-assign.is-active').forEach(badge => {
            badge.addEventListener('click', async () => {
                const tagId = badge.dataset.tagId;
                const statusEl = container.querySelector('#docs-dir-assign-status');
                await this._applyDirTagOp({ docs: allDocs, tagId, mode: 'assign', statusEl, container, closeModal, allTags });
            });
        });

        container.querySelectorAll('.docs-dir-tag-remove.is-active').forEach(badge => {
            badge.addEventListener('click', async () => {
                const tagId = badge.dataset.tagId;
                const statusEl = container.querySelector('#docs-dir-remove-status');
                await this._applyDirTagOp({ docs: allDocs, tagId, mode: 'remove', statusEl, container, closeModal, allTags });
            });
        });
    },

    async _applyDirTagOp({ docs, tagId, mode, statusEl, container, closeModal, allTags }) {
        container.querySelectorAll('.docs-dir-tag-assign, .docs-dir-tag-remove').forEach(b => {
            b.style.pointerEvents = 'none';
            b.style.opacity = '0.5';
        });

        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.className = 'docs-dir-modal-status docs-dir-modal-status--loading';
            statusEl.textContent = '⏳ Обрабатывается…';
        }

        const errors = [];

        for (const doc of docs) {
            const currentTagIds = (doc.tags || []).map(t => String(typeof t === 'object' ? t.id : t));
            const hasTag = currentTagIds.includes(tagId);

            let newTagIds;
            if (mode === 'assign') {
                if (hasTag) continue;
                newTagIds = [...currentTagIds, tagId];
            } else {
                if (!hasTag) continue;
                newTagIds = currentTagIds.filter(id => id !== tagId);
            }

            try {
                await this.api.updateDocumentLabels(String(doc.id), newTagIds);
            } catch (e) {
                errors.push(doc.source_path || doc.path || String(doc.id));
            }
        }

        container.querySelectorAll('.docs-dir-tag-assign, .docs-dir-tag-remove').forEach(b => {
            b.style.pointerEvents = '';
            b.style.opacity = '';
        });

        if (statusEl) {
            if (errors.length) {
                statusEl.className = 'docs-dir-modal-status docs-dir-modal-status--error';
                statusEl.innerHTML = `⚠️ Не удалось обновить ${errors.length} файл(ов):<br>
                    <span style="font-size:11px;color:var(--color-text-muted);">${errors.map(p => this.escapeHtml(p)).join('<br>')}</span>`;
            } else {
                statusEl.className = 'docs-dir-modal-status docs-dir-modal-status--ok';
                statusEl.textContent = '✅ Готово';
                setTimeout(() => { statusEl.style.display = 'none'; }, 2000);
            }
        }

        await this.loadDocumentsData();
    },

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
            const tid   = String(t.id);
            const on    = this._docsCurrentTags.includes(tid);
            const color = t.color || 'var(--color-primary)';
            const activeStyle   = `background:${color};color:${this._tc(color)};border-color:${color};`;
            const inactiveStyle = `background:var(--color-surface-offset);color:var(--color-text);border-color:var(--color-border);`;
            return `<span
                class="badge badge--modal badge--active docs-modal-tag-toggle ${on ? 'is-on' : 'is-off'}"
                data-tag-id="${tid}"
                data-color="${this.escapeHtml(color)}"
                style="${on ? activeStyle : inactiveStyle}"
            >${this.escapeHtml(t.name)}</span>`;
        }).join('');

        container.querySelectorAll('.docs-modal-tag-toggle').forEach(el => {
            el.addEventListener('click', () => {
                const tid   = String(el.dataset.tagId);
                const on    = this._docsCurrentTags.includes(tid);
                const color = el.dataset.color || 'var(--color-primary)';
                if (on) {
                    this._docsCurrentTags = this._docsCurrentTags.filter(x => x !== tid);
                    el.style.background  = 'var(--color-surface-offset)';
                    el.style.color       = 'var(--color-text)';
                    el.style.borderColor = 'var(--color-border)';
                    el.classList.replace('is-on', 'is-off');
                } else {
                    this._docsCurrentTags.push(tid);
                    el.style.background  = color;
                    el.style.color       = this._tc(color);
                    el.style.borderColor = color;
                    el.classList.replace('is-off', 'is-on');
                }
            });
        });
    },

    async handleDocumentsAction(action, btn) {
        if (action === 'run-indexer') {
            const runBtn = document.querySelector('[data-action="run-indexer"]');
            if (runBtn) { runBtn.disabled = true; runBtn.textContent = '⏳ Запуск…'; }
            try {
                const result = await this.api.runIndexer(this._activeDomainId || null);
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
