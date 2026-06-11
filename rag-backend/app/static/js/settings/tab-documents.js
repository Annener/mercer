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

    _filterDocsTable(query) {
        const q = query.trim().toLowerCase();
        const filtered = q
            ? this._docsAllDocs.filter(d => {
                const name = (d.title || d.source_path || '').toLowerCase();
                const tagMatch = (d.tags || []).some(t => t.name.toLowerCase().includes(q));
                return name.includes(q) || tagMatch;
              })
            : this._docsAllDocs;
        this._renderDocsRows(filtered);
    },

    _renderDocsRows(docs) {
        const table = document.getElementById('docs-table');
        if (!table) return;

        // Удаляем все tbody кроме первого (он — заглушка)
        while (table.tBodies.length > 1) table.removeChild(table.tBodies[table.tBodies.length - 1]);
        const stubBody = table.tBodies[0];

        if (!docs || docs.length === 0) {
            stubBody.innerHTML = '<tr><td colspan="1" class="empty-state">Документов нет</td></tr>';
            return;
        }
        stubBody.innerHTML = '';

        const openDirs = this._docsOpenDirs || new Set();
        const tree = this._buildDocsTree(docs);
        this._renderDocsTree(tree, table, 0, openDirs);
    },

    _renderDocsTree(node, container, depth, openDirs) {
        const sortedKeys = Object.keys(node.children).sort((a, b) => {
            const aIsDir = node.children[a]._isDir;
            const bIsDir = node.children[b]._isDir;
            if (aIsDir && !bIsDir) return -1;
            if (!aIsDir && bIsDir) return 1;
            return a.localeCompare(b);
        });

        for (const name of sortedKeys) {
            const child = node.children[name];

            if (child._isDir) {
                const isOpen = openDirs.has(name);

                const dirBody = document.createElement('tbody');
                const dirRow = document.createElement('tr');
                dirRow.className = 'docs-dir-row';
                dirRow.innerHTML = `
                    <td colspan="1" class="docs-dir-cell" style="padding-left:${8 + depth * 18}px;">
                        <span class="docs-dir-toggle" title="Раскрыть / свернуть">${isOpen ? '▾' : '▸'}</span>
                        <span class="docs-dir-label" title="Управление тегами каталога">
                            <span class="docs-dir-icon">📁</span>
                            <span class="docs-dir-name">${this.escapeHtml(name)}</span>
                        </span>
                        <span class="docs-dir-count">(${countFiles(child)})</span>
                    </td>`;
                dirBody.appendChild(dirRow);
                container.appendChild(dirBody);

                const childGroup = document.createElement('tbody');
                childGroup.style.display = isOpen ? '' : 'none';
                this._renderDocsTree(child, childGroup, depth + 1, openDirs);
                container.appendChild(childGroup);

                dirRow.addEventListener('click', (e) => {
                    if (e.target.closest('.docs-dir-label')) {
                        this._openDirModal(name, child);
                        return;
                    }
                    const nowOpen = childGroup.style.display !== 'none';
                    childGroup.style.display = nowOpen ? 'none' : '';
                    dirRow.querySelector('.docs-dir-toggle').textContent = nowOpen ? '▸' : '▾';
                    if (nowOpen) openDirs.delete(name); else openDirs.add(name);
                    this._docsOpenDirs = openDirs;
                });
                dirRow.after(childGroup);

            } else {
                const doc = child.doc;
                const tags = (doc.tags || []).map(t =>
                    `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:${this._getContrastColor(t.color)};">${this.escapeHtml(t.name)}</span>`
                ).join('');

                const row = document.createElement('tr');
                row.className = 'docs-row';
                row.dataset.id   = String(doc.id);
                row.dataset.path = doc.source_path || String(doc.id);
                row.style.cursor = 'pointer';
                row.title = 'Нажмите для редактирования тегов';
                row.innerHTML = `
                    <td class="docs-file-cell" style="padding-left:${8 + depth * 18}px;">
                        <div class="docs-file-row">
                            <span class="docs-file-name">
                                <span class="docs-file-icon">📄</span>${this.escapeHtml(name)}
                            </span>
                            <span class="docs-file-tags">
                                ${tags || '<span style="color:var(--color-text-faint)">—</span>'}
                            </span>
                        </div>
                        <div class="docs-file-meta">
                            ${this._renderDocStatus(doc.status)}
                        </div>
                    </td>`;

                row.addEventListener('click', () => this._openDocModal(doc));

                const fileBody = document.createElement('tbody');
                fileBody.appendChild(row);
                container.appendChild(fileBody);
            }
        }
    },

    _renderDocStatus(status) {
        const map = {
            indexed: { bg: '#e6f5ee', color: '#206a43', label: 'indexed' },
            pending: { bg: '#fff7e0', color: '#7a5700', label: 'pending' },
            error:   { bg: '#fdecea', color: '#a12c7b', label: 'error' },
            indexing:{ bg: '#e8f0fd', color: '#1a4fa3', label: 'indexing' },
        };
        const s = map[status] || { bg: '#eef2f6', color: '#657789', label: status || '—' };
        return `<span class="doc-status-badge" style="background:${s.bg};color:${s.color};">${this.escapeHtml(s.label)}</span>`;
    },

    // ─── Модальное окно файла ───────────────────────────────────────────────

    async _openDocModal(doc) {
        this._docsCurrentDoc = doc;
        const domainId = this._activeDomainId || await this._resolveDomainId();

        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop';

        let allTags = [];
        try {
            const resp = await this.api.getTags(domainId);
            allTags = [
                ...(Array.isArray(resp) ? resp : (resp.global_tags || [])),
                ...Object.values((resp && resp.by_campaign) || {}).flat(),
            ];
        } catch (_) {}

        const currentTagIds = new Set((doc.tags || []).map(t => String(t.id)));

        const renderBadges = () => allTags.map(t => {
            const active = currentTagIds.has(String(t.id));
            const bg = active ? (t.color || 'var(--color-primary)') : 'var(--color-surface-offset)';
            const allHaveIt = false;
            return `<span class="badge docs-modal-tag-badge"
                       data-tag-id="${String(t.id)}"
                       style="background:${bg};
                       color:${active ? this._getContrastColor(t.color) : 'var(--color-text-muted)'};
                       cursor:pointer;
                       opacity:${allHaveIt ? 0.5 : 1};
                       border: 1px solid ${active ? 'transparent' : 'var(--color-border)'};"
                       title="${active ? 'Снять тег' : 'Назначить тег'}">${this.escapeHtml(t.name)}</span>`;
        }).join('');

        backdrop.innerHTML = `
            <div class="modal docs-modal">
                <div class="modal-header">
                    <span class="docs-modal-filename">📄 ${this.escapeHtml(doc.title || doc.source_path || String(doc.id))}</span>
                    <button class="modal-close" data-action="close-modal">✕</button>
                </div>
                <div class="modal-body docs-modal-body">
                    <div class="docs-modal-tags-wrap">
                        <div class="docs-modal-tags-label">Теги</div>
                        <div class="docs-modal-tag-badges" id="docs-modal-tag-badges">
                            ${allTags.length ? renderBadges() : '<div id="docs-modal-tags-loading" style="color:var(--color-text-muted);font-size:13px;">Загрузка...</div>'}
                        </div>
                    </div>
                </div>
                <div class="modal-footer docs-modal-footer-btns">
                    <button class="btn btn-primary docs-modal-save-btn" data-action="save-doc-tags">Сохранить теги</button>
                    <button class="btn docs-modal-delete-btn" data-action="delete-doc">🗑 Удалить</button>
                </div>
            </div>`;

        backdrop.addEventListener('click', async (e) => {
            const action = e.target.closest('[data-action]')?.dataset?.action;
            if (action === 'close-modal' || e.target === backdrop) {
                backdrop.remove();
                return;
            }
            if (action === 'save-doc-tags') {
                try {
                    await this.api.updateDocumentTags(String(doc.id), [...currentTagIds]);
                    backdrop.remove();
                    await this.loadDocumentsData();
                } catch (err) { alert('Ошибка сохранения: ' + err.message); }
                return;
            }
            if (action === 'delete-doc') {
                if (!confirm(`Удалить документ «${doc.title || doc.source_path}»?`)) return;
                try {
                    await this.api.deleteDocument(String(doc.id));
                    backdrop.remove();
                    await this.loadDocumentsData();
                } catch (err) { alert('Ошибка удаления: ' + err.message); }
                return;
            }
            const badge = e.target.closest('.docs-modal-tag-badge');
            if (badge) {
                const tid = badge.dataset.tagId;
                if (currentTagIds.has(tid)) currentTagIds.delete(tid);
                else currentTagIds.add(tid);
                const container = document.getElementById('docs-modal-tag-badges');
                if (container) container.innerHTML = renderBadges();
            }
        });

        document.body.appendChild(backdrop);
    },

    // ─── Модальное окно каталога ────────────────────────────────────────────

    async _openDirModal(dirName, dirNode) {
        const allDocs = this._collectDirDocs(dirNode);
        const domainId = this._activeDomainId || await this._resolveDomainId();

        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop';
        backdrop.innerHTML = `
            <div class="modal docs-dir-modal">
                <div class="modal-header">
                    <span class="docs-modal-filename">📁 ${this.escapeHtml(dirName)}</span>
                    <span class="docs-dir-modal-count">${allDocs.length} файл(ов)</span>
                    <button class="modal-close" data-action="close-modal">✕</button>
                </div>
                <div class="docs-dir-modal-body">
                    <div class="docs-dir-modal-section">
                        <div style="color:var(--color-text-muted);font-size:13px;">Загрузка тегов…</div>
                    </div>
                </div>
            </div>`;

        backdrop.addEventListener('click', e => {
            if (e.target.closest('[data-action="close-modal"]') || e.target === backdrop)
                backdrop.remove();
        });
        document.body.appendChild(backdrop);

        let allTags = [];
        try {
            const resp = await this.api.getTags(domainId);
            allTags = [
                ...(Array.isArray(resp) ? resp : (resp.global_tags || [])),
                ...Object.values((resp && resp.by_campaign) || {}).flat(),
            ];
        } catch (_) {}

        const docTagCounts = {};
        for (const doc of allDocs) {
            for (const t of (doc.tags || [])) {
                docTagCounts[String(t.id)] = (docTagCounts[String(t.id)] || 0) + 1;
            }
        }

        const selectedTagIds = new Set();
        const removedTagIds  = new Set();

        const renderAssignBadges = () => allTags.map(t => {
            const tid = String(t.id);
            const count = docTagCounts[tid] || 0;
            const allHaveIt = count === allDocs.length;
            const active = selectedTagIds.has(tid);
            const removing = removedTagIds.has(tid);
            let bg, color, border;
            if (removing) {
                bg = '#fdecea'; color = '#a12c7b'; border = '#f5c6cb';
            } else if (active) {
                bg = t.color || 'var(--color-primary)';
                color = this._getContrastColor(t.color);
                border = 'transparent';
            } else {
                bg = allHaveIt
                    ? (t.color || 'var(--color-primary)')
                    : 'var(--color-surface-offset)';
                color = allHaveIt
                    ? this._getContrastColor(t.color)
                    : 'var(--color-text-muted)';
                border = allHaveIt ? 'transparent' : 'var(--color-border)';
            }
            const countLabel = count > 0 ? ` (${count}/${allDocs.length})` : '';
            return `<span class="badge docs-dir-tag-badge"
                       data-tag-id="${tid}"
                       style="background:${bg};color:${color};cursor:pointer;border:1px solid ${border};"
                       title="${allHaveIt ? 'Все файлы имеют этот тег' : `${count} из ${allDocs.length} файлов`}">
                       ${this.escapeHtml(t.name)}${countLabel}
                    </span>`;
        }).join('');

        const assignBadges = renderAssignBadges();
        const body = backdrop.querySelector('.docs-dir-modal-body');
        body.innerHTML = `
            <div class="docs-dir-modal-section">
                <div style="font-size:12px;color:var(--color-text-muted);margin-bottom:6px;">Назначить / снять теги для всех файлов каталога:</div>
                <div class="docs-dir-tag-list" id="dir-tag-assign-list">
                    ${allTags.length ? assignBadges : '<span style="color:var(--color-text-faint);font-size:13px;">Нет тегов ни на одном файле</span>'}
                </div>
            </div>
            <div class="docs-dir-modal-divider"></div>
            <div class="docs-modal-footer-btns">
                <button class="btn btn-primary docs-modal-save-btn" data-action="save-dir-tags">Применить</button>
            </div>
            <div id="dir-op-status"></div>`;

        const listEl = document.getElementById('dir-tag-assign-list');
        if (listEl) {
            listEl.addEventListener('click', e => {
                const badge = e.target.closest('.docs-dir-tag-badge');
                if (!badge) return;
                const tid = badge.dataset.tagId;
                if (removedTagIds.has(tid)) {
                    removedTagIds.delete(tid);
                } else if (selectedTagIds.has(tid)) {
                    selectedTagIds.delete(tid);
                    removedTagIds.add(tid);
                } else {
                    selectedTagIds.add(tid);
                }
                listEl.innerHTML = renderAssignBadges();
            });
        }

        const saveBtn = backdrop.querySelector('[data-action="save-dir-tags"]');
        if (saveBtn) {
            saveBtn.addEventListener('click', async () => {
                const statusEl = document.getElementById('dir-op-status');
                if (!selectedTagIds.size && !removedTagIds.size) {
                    backdrop.remove();
                    return;
                }
                saveBtn.disabled = true;
                let done = 0, errors = [];
                for (const doc of allDocs) {
                    try {
                        const currentIds = new Set((doc.tags || []).map(t => String(t.id)));
                        selectedTagIds.forEach(tid => currentIds.add(tid));
                        removedTagIds.forEach(tid => currentIds.delete(tid));
                        await this.api.updateDocumentTags(String(doc.id), [...currentIds]);
                        done++;
                        if (statusEl) {
                            statusEl.className = 'docs-dir-modal-status docs-dir-modal-status--loading';
                            statusEl.textContent = `Обновлено ${done} / ${allDocs.length}…`;
                        }
                    } catch (err) {
                        errors.push(doc.source_path || String(doc.id));
                    }
                }
                if (statusEl) {
                    if (errors.length) {
                        statusEl.className = 'docs-dir-modal-status';
                        statusEl.style.background = '#fdecea';
                        statusEl.style.color = '#a12c7b';
                        statusEl.innerHTML = `Ошибки (${errors.length}):<br>
                    <span style="font-size:11px;color:var(--color-text-muted);">${errors.map(p => this.escapeHtml(p)).join('<br>')}</span>`;
                    } else {
                        statusEl.className = 'docs-dir-modal-status';
                        statusEl.style.background = '#e6f5ee';
                        statusEl.style.color = '#206a43';
                        statusEl.textContent = `✓ Обновлено ${done} файлов`;
                    }
                }
                saveBtn.disabled = false;
                await this.loadDocumentsData();
            });
        }
    },

    _collectDirDocs(node) {
        const result = [];
        const walk = (n) => {
            for (const child of Object.values(n.children)) {
                if (child._isDir) walk(child);
                else result.push(child.doc);
            }
        };
        walk(node);
        return result;
    },

    // ─── Прогресс индексации ────────────────────────────────────────────────

    async _startIndexer() {
        const vaultId = await this._resolveVaultId();
        if (!vaultId) { alert('Vault не найден'); return; }
        try {
            await this.api.runIndexer(vaultId);
            this._startIndexPoll(vaultId);
        } catch (e) {
            alert('Ошибка запуска индексатора: ' + e.message);
        }
    },

    _startIndexPoll(vaultId) {
        if (this._docsIndexPollTimer) clearInterval(this._docsIndexPollTimer);
        const panel = document.getElementById('docs-index-progress-panel');
        if (panel) panel.style.display = '';

        const poll = async () => {
            try {
                const state = await this.api.getIndexerStatus(vaultId);
                this._renderIndexProgress(state);
                if (['idle', 'done', 'error', 'cancelled'].includes(state.status)) {
                    clearInterval(this._docsIndexPollTimer);
                    this._docsIndexPollTimer = null;
                    await this.loadDocumentsData();
                }
            } catch (_) {}
        };
        poll();
        this._docsIndexPollTimer = setInterval(poll, 2000);
    },

    _renderIndexProgress(state) {
        const panel = document.getElementById('docs-index-progress-panel');
        if (!panel) return;
        const statusMap = {
            idle: 'Ожидание', running: 'Индексация', done: 'Завершено',
            error: 'Ошибка', cancelled: 'Отменено',
        };
        const statusLabel = statusMap[state.status] || state.status;
        const total = state.total_files || 0;
        const done  = state.indexed_files || 0;
        const pct   = total > 0 ? Math.round((done / total) * 100) : 0;

        panel.innerHTML = `
            <div class="docs-index-progress-header">
                <span class="idx-status-label">${statusLabel}</span>
                ${total > 0 ? `<span class="idx-global-count">${done} / ${total} файлов</span>` : ''}
                ${total > 0 ? `<span class="idx-pct">${pct}%</span>` : ''}
            </div>
            ${total > 0 ? `<div class="idx-progress-bar"><div class="idx-progress-fill" style="width:${pct}%"></div></div>` : ''}
            <div class="idx-files-list" id="idx-files-list"></div>
            ${state.error ? `<div style="color:var(--color-error);font-size:var(--text-xs);margin-top:8px;">${this.escapeHtml(state.error)}</div>` : ''}`;

        const filesList = document.getElementById('idx-files-list');
        if (filesList && state.files) {
            filesList.innerHTML = state.files.map(f => {
                const name = f.path.split('/').pop();
                const stageMap = {
                    parsing: { bg: '#fff3cd', color: '#856404' },
                    chunking: { bg: '#e8d5f5', color: '#5a1e8c' },
                    indexing: { bg: '#d1ecf1', color: '#0c5460' },
                    done: { bg: '#d4edda', color: '#155724' },
                    error: { bg: '#f8d7da', color: '#721c24' },
                };
                const st = stageMap[f.stage] || { bg: '#f8f9fa', color: '#6a737d' };
                return `
                    <div class="file-row2">
                        <div class="file-row2-top">
                            <span class="file-row2-name" title="${this.escapeHtml(f.path)}">${this.escapeHtml(name)}</span>
                            <span class="file-row2-chunks">${f.chunks_done ?? 0}/${f.chunks_total ?? 0} чанков</span>
                        </div>
                        <span class="file-row2-stage"
                              style="display:inline-block;padding:1px 7px;border-radius:9px;
                                     background:${st.bg};color:${st.color};font-size:10px;">
                            ${this.escapeHtml(f.stage || '—')}
                        </span>
                    </div>`;
            }).join('');
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

    _getContrastColor(hex) {
        if (!hex || hex.startsWith('var(')) return '#111111';
        const h = hex.replace('#', '');
        const r = parseInt(h.substring(0, 2), 16);
        const g = parseInt(h.substring(2, 4), 16);
        const b = parseInt(h.substring(4, 6), 16);
        // Perceived luminance (WCAG formula)
        const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        return luminance > 0.55 ? '#111111' : '#ffffff';
    },

};

Object.assign(SettingsManager.prototype, DocumentsTabMixin);
