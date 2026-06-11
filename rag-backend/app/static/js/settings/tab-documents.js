const DocumentsTabMixin = {
    _docsCurrentDoc: null,
    _docsAllTags: [],
    _docsCurrentTags: [],
    _docsAllDocs: [],
    _docsFilterStatus: '',
    _docsFilterTagId: '',
    _docsIndexTaskId: null,

    initDocumentsTab() {
        this._docsCurrentDoc = null;
        this._docsAllTags    = [];
        this._docsCurrentTags = [];
        this._docsAllDocs    = [];
        this._docsFilterStatus = '';
        this._docsFilterTagId  = '';
    },

    buildDocsToolbar() {
        return `
            <div class="docs-toolbar" id="docs-toolbar">
                <select id="docs-status-filter" class="input-field docs-toolbar-select">
                    <option value="">Все статусы</option>
                    <option value="indexed">indexed</option>
                    <option value="pending">pending</option>
                    <option value="error">error</option>
                    <option value="indexing">indexing</option>
                </select>
                <select id="docs-tag-filter" class="input-field docs-toolbar-select">
                    <option value="">Все теги</option>
                </select>
                <button class="btn btn-secondary docs-toolbar-btn" data-action="open-tags-panel" title="Управление тегами">🏷️ Теги</button>
                <button class="btn btn-secondary docs-toolbar-btn" data-action="reindex-all" title="Переиндексировать всё">🔄 Переиндексировать</button>
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
            </div>`;
    },

    async loadDocumentsData() {
        const domainId = this._docsCurrentDomainId();
        if (!domainId) return;
        try {
            const resp = await this.api.getSettingsDocuments({
                domainId,
                status: this._docsFilterStatus || null,
                tagId:    this._docsFilterTagId   || null,
            });
            this._docsAllDocs = Array.isArray(resp) ? resp : (resp.documents || []);
            await this._refreshTagFilter(domainId);
            this._renderDocsTable();
        } catch (e) {
            const tbody = document.getElementById('docs-tbody');
            if (tbody) tbody.innerHTML = `<tr><td colspan="1" class="empty-state" style="color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</td></tr>`;
        }
    },

    async _refreshTagFilter(domainId) {
        const sel = document.getElementById('docs-tag-filter');
        if (!sel) return;
        try {
            const resp = await this.api.getDomainTags(domainId);
            const tags = [
                ...(Array.isArray(resp) ? resp : (resp.global_tags || [])),
            ];
            const current = sel.value;
            sel.innerHTML = '<option value="">Все теги</option>' +
                tags.map(t => `<option value="${t.id}"${t.id == current ? ' selected' : ''}>${this.escapeHtml(t.name)}</option>`).join('');
        } catch (_) {}
    },

    async _refreshTagsPanel(domainId) {
        const listEl = document.getElementById('docs-tags-panel-list');
        if (!listEl) return;
        try {
            const resp = await this.api.getDomainTags(domainId);
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
                    catch (e) { alert('Ошибка: ' + e.message); }
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
                    catch (e) { alert('Ошибка: ' + e.message); }
                });
            });
            const createBtn = document.querySelector('[data-action="create-tag"]');
            if (createBtn) {
                createBtn.onclick = async () => {
                    const nameInp  = document.getElementById('new-tag-name');
                    const colorInp = document.getElementById('new-tag-color');
                    const name = nameInp?.value.trim();
                    if (!name) return;
                    try {
                        await this.api.createTag({ name, color: colorInp?.value || '#01696f', domain_id: domainId });
                        nameInp.value = '';
                        await this._refreshTagsPanel(domainId); await this.loadDocumentsData();
                    } catch (e) { alert('Ошибка: ' + e.message); }
                };
            }
        } catch (e) {
            if (listEl) listEl.innerHTML = `<span style="color:var(--color-error);font-size:var(--text-xs);">Ошибка: ${this.escapeHtml(e.message)}</span>`;
        }
    },

    _renderDocsTable() {
        const tbody = document.getElementById('docs-tbody');
        if (!tbody) return;
        const docs  = this._docsAllDocs;

        if (!docs.length) {
            tbody.innerHTML = `<tr><td colspan="1" class="empty-state">Нет документов</td></tr>`;
            return;
        }

        // Группируем по директории
        const groups = {};   // dirKey -> { dirLabel, children: [{doc, filename}] }
        for (const doc of docs) {
            const parts = (doc.source_path || doc.title || '').replace(/\\/g, '/').split('/');
            const filename = parts.pop();
            const dirKey   = parts.join('/') || '/';
            const dirLabel = parts.length ? parts[parts.length - 1] : '/';
            if (!groups[dirKey]) groups[dirKey] = { dirKey, dirLabel, children: [] };
            groups[dirKey].children.push({ doc, filename });
        }

        const rows = [];
        for (const g of Object.values(groups)) {
            rows.push({ type: 'dir', dirKey: g.dirKey, dirLabel: g.dirLabel, children: g.children });
            for (const child of g.children) rows.push({ type: 'file', ...child });
        }

        tbody.innerHTML = '';
        for (const item of rows) {
            if (item.type === 'dir') {
                const tr = document.createElement('tr');
                tr.className = 'docs-dir-row';
                tr.dataset.dirKey = item.dirKey;
                tr.innerHTML = `
                    <td class="docs-dir-cell" colspan="1">
                        <span class="docs-dir-toggle" data-dir-key="${this.escapeHtml(item.dirKey)}">▶</span>
                        <span class="docs-dir-name" data-dir-key="${this.escapeHtml(item.dirKey)}" style="cursor:pointer;">📁 ${this.escapeHtml(item.dirLabel)}</span>
                        <span class="docs-dir-count">(${item.children.length})</span>
                        <span class="docs-dir-tags-area" data-dir-key="${this.escapeHtml(item.dirKey)}"></span>
                    </td>`;
                tbody.appendChild(tr);
            } else {
                const doc = item.doc;
                const tags = (doc.tags || []).map(t =>
                    `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:#ffffff;">${this.escapeHtml(t.name)}</span>`
                ).join('');

                const row = document.createElement('tr');
                row.className = 'docs-row';
                row.dataset.docId  = doc.id;
                row.dataset.dirKey = (() => {
                    const parts = (doc.source_path || doc.title || '').replace(/\\/g, '/').split('/');
                    parts.pop();
                    return parts.join('/') || '/';
                })();
                row.style.display = 'none';

                row.innerHTML = `
                    <td class="docs-cell-file">
                        <div class="docs-file-info">
                            <span class="docs-file-name">${this.escapeHtml(item.filename)}</span>
                            <span class="docs-file-tags">
                                ${tags || '<span style="color:var(--color-text-faint)">—</span>'}
                            </span>
                        </div>
                    </td>`;
                tbody.appendChild(row);

                row.addEventListener('click', () => this._openDocModal(doc));
            }
        }

        // Toggle dir rows
        tbody.querySelectorAll('.docs-dir-toggle, .docs-dir-name').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const dirKey = el.dataset.dirKey;
                const dirRow = tbody.querySelector(`.docs-dir-row[data-dir-key="${CSS.escape(dirKey)}"]`);
                const toggle = dirRow?.querySelector('.docs-dir-toggle');
                const isOpen = toggle?.textContent === '▼';

                tbody.querySelectorAll(`.docs-row[data-dir-key="${CSS.escape(dirKey)}"]`).forEach(r => {
                    r.style.display = isOpen ? 'none' : '';
                });
                if (toggle) toggle.textContent = isOpen ? '▶' : '▼';

                if (!isOpen) {
                    const dirTagsArea = dirRow?.querySelector('.docs-dir-tags-area');
                    if (dirTagsArea && !dirTagsArea.dataset.loaded) {
                        dirTagsArea.dataset.loaded = '1';
                        this._renderDirTagsArea(dirTagsArea, dirKey);
                    }
                }
            });
        });
    },

    async _renderDirTagsArea(areaEl, dirKey) {
        const domainId = this._docsCurrentDomainId();
        if (!domainId) return;
        areaEl.innerHTML = `<div style="color:var(--color-text-muted);font-size:13px;">Загрузка тегов…</div>`;
        try {
            const resp = await this.api.getDomainTags(domainId);
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);

            const allDocs = this._docsAllDocs.filter(doc => {
                const parts = (doc.source_path || doc.title || '').replace(/\\/g, '/').split('/');
                parts.pop();
                return (parts.join('/') || '/') === dirKey;
            });

            const tagDocCount = {}; // tagId -> кол-во файлов с этим тегом
            for (const doc of allDocs) {
                for (const t of (doc.tags || [])) {
                    const tid = String(t.id);
                    tagDocCount[tid] = (tagDocCount[tid] || 0) + 1;
                }
            }

            const presentTagIds = Object.keys(tagDocCount);
            const relevantTags  = globalTags.filter(t => presentTagIds.includes(String(t.id)));

            const inner = document.createElement('span');
            inner.className = 'docs-dir-tags-inner';

            if (!relevantTags.length) {
                areaEl.innerHTML = '';
                return;
            }

            inner.innerHTML = relevantTags.map(t => {
                const tid = String(t.id);
                const allHaveIt = tagDocCount[tid] === allDocs.length && allDocs.length > 0;
                return `<span class="badge docs-dir-tag-assign ${allHaveIt ? 'is-disabled' : 'is-active'}"
                data-tag-id="${tid}"
                data-tag-color="${this.escapeHtml(t.color || '')}"
                style="background:${allHaveIt ? 'var(--color-surface-offset)' : (t.color || 'var(--color-primary)')};
                       color:${allHaveIt ? 'var(--color-text-faint)' : 'white'};
                       border:1px solid ${allHaveIt ? 'var(--color-border)' : (t.color || 'var(--color-primary)')};
                       cursor:${allHaveIt ? 'default' : 'pointer'};font-size:11px;"
                title="${allHaveIt ? 'У всех файлов' : 'Назначить всем'}">${this.escapeHtml(t.name)}</span>`;
            }).join('');

            inner.querySelectorAll('.docs-dir-tag-assign.is-active').forEach(span => {
                span.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const tagId  = span.dataset.tagId;
                    const docIds = allDocs.map(d => String(d.id));
                    try {
                        await this.api.batchLabelDocuments(docIds, [tagId]);
                        delete areaEl.dataset.loaded;
                        await this.loadDocumentsData();
                    } catch (err) { alert('Ошибка: ' + err.message); }
                });
            });

            const removeTagsHtml = relevantTags.map(t => {
                const tid = String(t.id);
                return `<span class="badge docs-dir-tag-remove is-active"
                    data-tag-id="${tid}"
                    style="background:var(--color-surface-offset);color:var(--color-text-muted);
                           border:1px solid var(--color-border);cursor:pointer;font-size:11px;"
                    title="Убрать тег у всех файлов папки">✕ ${this.escapeHtml(t.name)}</span>`;
            }).join('');

            if (removeTagsHtml) {
                const removeArea = document.createElement('span');
                removeArea.className = 'docs-dir-tags-remove-area';
                removeArea.innerHTML = removeTagsHtml;
                removeArea.querySelectorAll('.docs-dir-tag-remove').forEach(span => {
                    span.addEventListener('click', async (e) => {
                        e.stopPropagation();
                        const tagId  = span.dataset.tagId;
                        const docIds = allDocs
                            .filter(d => (d.tags || []).some(t => String(t.id) === tagId))
                            .map(d => String(d.id));
                        if (!docIds.length) return;
                        try {
                            await this.api.batchUnlabelDocuments(docIds, [tagId]);
                            delete areaEl.dataset.loaded;
                            await this.loadDocumentsData();
                        } catch (err) { alert('Ошибка: ' + err.message); }
                    });
                });
                inner.appendChild(removeArea);
            }

            areaEl.innerHTML = '';
            areaEl.appendChild(inner);
        } catch (e) {
            if (areaEl) areaEl.innerHTML = `<div style="color:var(--color-error);">Ошибка загрузки тегов: ${this.escapeHtml(e.message)}</div>`;
        }
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

    async _openDocModal(doc) {
        this._docsCurrentDoc = doc;
        const modal = document.getElementById('doc-modal');
        if (!modal) return;

        // Title
        const titleEl = modal.querySelector('.doc-modal-title');
        if (titleEl) titleEl.textContent = doc.title || doc.source_path || '—';

        // Info
        const infoEl = modal.querySelector('.doc-modal-info');
        if (infoEl) {
            infoEl.innerHTML = `
                <div><b>Путь:</b> ${this.escapeHtml(doc.source_path || '—')}</div>
                <div><b>Статус:</b> ${this._docStatusBadge(doc.status)}</div>
                <div><b>Chunks:</b> ${doc.chunk_count ?? '—'}</div>
                <div><b>MD5:</b> <code>${this.escapeHtml(doc.md5 || '—')}</code></div>
            `;
        }

        // Tags
        const domainId = this._docsCurrentDomainId();
        const tagsContainer = modal.querySelector('#doc-modal-tags');
        if (tagsContainer && domainId) {
            tagsContainer.innerHTML = `<div style="color:var(--color-text-muted);font-size:13px;">Загрузка тегов…</div>`;
            try {
                const resp = await this.api.getDomainTags(domainId);
                const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);
                const assignedIds = new Set((doc.tags || []).map(t => String(t.id)));

                tagsContainer.innerHTML = globalTags.map(t => {
                    const tid = String(t.id);
                    const active = assignedIds.has(tid);
                    return `<span class="badge docs-tag-toggle ${active ? 'is-active' : ''}"
                        data-tag-id="${tid}"
                        style="background:${active ? (t.color || 'var(--color-primary)') : 'var(--color-surface-offset)'};
                               color:${active ? 'white' : 'var(--color-text-muted)'};
                               border:1px solid ${active ? (t.color || 'var(--color-primary)') : 'var(--color-border)'};
                               cursor:pointer;">
                        ${this.escapeHtml(t.name)}
                    </span>`;
                }).join('');

                tagsContainer.querySelectorAll('.docs-tag-toggle').forEach(span => {
                    span.addEventListener('click', () => {
                        span.classList.toggle('is-active');
                        const tagId = span.dataset.tagId;
                        const tag = globalTags.find(t => String(t.id) === tagId);
                        const nowActive = span.classList.contains('is-active');
                        span.style.background = nowActive ? (tag?.color || 'var(--color-primary)') : 'var(--color-surface-offset)';
                        span.style.color = nowActive ? 'white' : 'var(--color-text-muted)';
                        span.style.border = `1px solid ${nowActive ? (tag?.color || 'var(--color-primary)') : 'var(--color-border)'}`;
                    });
                });
            } catch (e) {
                tagsContainer.innerHTML = `<div style="color:var(--color-error);">Ошибка загрузки тегов: ${this.escapeHtml(e.message)}</div>`;
            }
        }

        // State
        const stateEl = modal.querySelector('#doc-modal-clarif-state');
        if (stateEl) {
            try {
                const state = await this.api.getDocumentClarifState?.(doc.id);
                if (state) {
                    stateEl.innerHTML = `
                        <div><b>Stage:</b> ${this.escapeHtml(state.stage || '—')}</div>
                        <div><b>Turn:</b> ${state.turn ?? '—'}</div>
                        <div><b>Collected:</b> <code>${this.escapeHtml(JSON.stringify(state.collected || {}))}</code></div>
                        ${state.error ? `<div style="color:var(--color-error);font-size:var(--text-xs);margin-top:8px;">${this.escapeHtml(state.error)}</div>` : ''}
                    `;
                } else {
                    stateEl.innerHTML = '<span style="color:var(--color-text-faint)">—</span>';
                }
            } catch (_) {
                stateEl.innerHTML = '<span style="color:var(--color-text-faint)">—</span>';
            }
        }

        modal.classList.add('is-open');
    },

    _closeDocModal() {
        const modal = document.getElementById('doc-modal');
        if (modal) modal.classList.remove('is-open');
        this._docsCurrentDoc = null;
    },

    async _saveDocTags() {
        const doc = this._docsCurrentDoc;
        if (!doc) return;
        const modal = document.getElementById('doc-modal');
        const tagsContainer = modal?.querySelector('#doc-modal-tags');
        if (!tagsContainer) return;

        const tagIds = [...tagsContainer.querySelectorAll('.docs-tag-toggle.is-active')]
            .map(s => s.dataset.tagId);

        try {
            await this.api.updateDocumentLabels(doc.id, tagIds);
            this._closeDocModal();
            await this.loadDocumentsData();
        } catch (e) {
            alert('Ошибка сохранения тегов: ' + e.message);
        }
    },

    async _deleteDoc() {
        const doc = this._docsCurrentDoc;
        if (!doc) return;
        if (!confirm(`Удалить документ «${doc.title || doc.source_path}»?`)) return;
        try {
            await this.api.deleteDocument(doc.id);
            this._closeDocModal();
            await this.loadDocumentsData();
        } catch (e) {
            alert('Ошибка удаления: ' + e.message);
        }
    },

    async onDocsTabActivated(domainId) {
        const toolbar = document.getElementById('docs-toolbar-container');
        if (toolbar && !toolbar.querySelector('.docs-toolbar')) {
            toolbar.innerHTML = this.buildDocsToolbar();
            this._bindDocsToolbarEvents(domainId);
        }
        await this._refreshTagsPanel(domainId);
        await this.loadDocumentsData();
    },

    _bindDocsToolbarEvents(domainId) {
        const statusSel = document.getElementById('docs-status-filter');
        if (statusSel) {
            statusSel.addEventListener('change', async () => {
                this._docsFilterStatus = statusSel.value;
                await this.loadDocumentsData();
            });
        }
        const tagSel = document.getElementById('docs-tag-filter');
        if (tagSel) {
            tagSel.addEventListener('change', async () => {
                this._docsFilterTagId = tagSel.value;
                await this.loadDocumentsData();
            });
        }

        const tagsBtn = document.querySelector('[data-action="open-tags-panel"]');
        if (tagsBtn) {
            tagsBtn.addEventListener('click', () => {
                const panel = document.getElementById('docs-tags-panel');
                if (panel) panel.classList.toggle('is-open');
            });
        }

        const reindexBtn = document.querySelector('[data-action="reindex-all"]');
        if (reindexBtn) {
            reindexBtn.addEventListener('click', async () => {
                if (!confirm('Запустить переиндексацию всех документов?')) return;
                try {
                    await this.api.reindexAll?.();
                    alert('Переиндексация запущена');
                } catch (e) { alert('Ошибка: ' + e.message); }
            });
        }

        // Modal events
        const saveBtn = document.getElementById('doc-modal-save');
        if (saveBtn) saveBtn.addEventListener('click', () => this._saveDocTags());

        const deleteBtn = document.getElementById('doc-modal-delete');
        if (deleteBtn) deleteBtn.addEventListener('click', () => this._deleteDoc());

        const closeBtn = document.getElementById('doc-modal-close');
        if (closeBtn) closeBtn.addEventListener('click', () => this._closeDocModal());

        const overlay = document.getElementById('doc-modal-overlay');
        if (overlay) overlay.addEventListener('click', () => this._closeDocModal());
    },

    _docsCurrentDomainId() {
        try {
            const list = this._state?.domains || this.domains || [];
            const first = list.find(d => d.domain_id === this._state?.currentDomainId)
                       || list.find(d => d.domain_id === this.currentDomainId)
                       || list.find(d => !d.is_system && d.enabled !== false) || list[0];
            return first ? (first.domain_id || first.id || null) : null;
        } catch (_) { return null; }
    },
};

Object.assign(SettingsManager.prototype, DocumentsTabMixin);
