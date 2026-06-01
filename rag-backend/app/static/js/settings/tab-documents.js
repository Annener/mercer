const DocumentsTabMixin = {
    _docsSidePanelOpen: false,
    _docsCurrentDoc: null,
    _docsAllTags: [],
    _docsCurrentTags: [],
    _docsAllDocs: [],
    _docsFilterStatus: '',
    _docsFilterTagId: '',
    _docsIndexTaskId: null,
    _docsIndexPollTimer: null,

    async renderDocumentsTab() {
        return `
        <div class="settings-toolbar" style="gap:var(--space-3);align-items:center;display:flex;flex-wrap:wrap;">
            <button class="btn btn-primary" data-action="run-indexer">▶ Запустить индексацию</button>
            <input type="text" id="docs-search-input" placeholder="🔍 поиск по имени..." class="input-field" style="max-width:220px;">
            <select id="docs-status-filter" class="input-field" style="max-width:150px;">
                <option value="">Все статусы</option>
                <option value="indexed">indexed</option>
                <option value="pending">pending</option>
                <option value="error">error</option>
            </select>
            <select id="docs-tag-filter" class="input-field" style="max-width:180px;">
                <option value="">Все теги</option>
            </select>
            <button class="btn btn-secondary" data-action="manage-tags" style="margin-left:auto;">🏷 Теги домена</button>
            <span id="docs-indexer-status" style="color:var(--color-text-muted);font-size:var(--text-sm);"></span>
        </div>
        <div class="docs-layout" style="display:flex;gap:var(--space-4);margin-top:var(--space-4);">
            <div style="flex:1;overflow:auto;">
                <table class="data-table" id="docs-table">
                    <thead><tr>
                        <th>Файл</th><th>Vault</th><th>Статус</th><th>Теги</th><th style="width:48px;"></th>
                    </tr></thead>
                    <tbody id="docs-tbody">
                        <tr><td colspan="5" class="empty-state">Загрузка...</td></tr>
                    </tbody>
                </table>
            </div>
            <div id="docs-side-panel" class="docs-side-panel" style="display:none;width:320px;flex-shrink:0;"></div>
        </div>`;
    },

    async loadDocumentsData() {
        // S40-A fix: перешли на getSettingsDocuments — серверные фильтры status и tag_id.
        // Один из vaultId или domainId обязателен (бэк вернёт 400 если не передать).
        const vaultId  = await this._resolveVaultId();
        const domainId = this._activeDomainId || await this._resolveDomainId();
        const tbody = document.getElementById('docs-tbody');

        if (!vaultId && !domainId) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Vault не найден. Добавьте vault в настройках.</td></tr>';
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
                statusSel.onchange = () => {
                    this._docsFilterStatus = statusSel.value;
                    this.loadDocumentsData();
                };
            }

            if (domainId) await this._loadTagFilterOptions(domainId);

        } catch (e) {
            if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="empty-state" style="color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</td></tr>`;
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
            sel.onchange = () => {
                this._docsFilterTagId = sel.value;
                this.loadDocumentsData();
            };
        } catch (_) { /* не критично */ }
    },

    _renderDocsRows(docs) {
        const tbody = document.getElementById('docs-tbody');
        if (!tbody) return;
        if (!docs || !docs.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Документов нет</td></tr>';
            return;
        }
        const statusColor = (s) => ({ indexed: 'var(--color-success)', pending: 'var(--color-gold)', error: 'var(--color-error)' }[s] || 'var(--color-text-muted)');
        tbody.innerHTML = docs.map(doc => {
            const tags = (doc.tags || []).map(t =>
                `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:var(--color-text);margin-right:2px;">${this.escapeHtml(t.name)}</span>`
            ).join('');
            const fileName = (doc.source_path || doc.path || String(doc.id)).split('/').pop();
            const vaultLabel = this.escapeHtml(doc.vault_id || '—');
            // D2 fix: data-vault передаётся в кнопку удаления для vault_id
            return `<tr class="docs-row" data-id="${this.escapeHtml(String(doc.id))}" style="cursor:pointer;">
                <td title="${this.escapeHtml(doc.source_path || String(doc.id))}">${this.escapeHtml(fileName)}</td>
                <td style="color:var(--color-text-muted);font-size:var(--text-xs);">${vaultLabel}</td>
                <td><span style="color:${statusColor(doc.status)};font-weight:600;">${this.escapeHtml(doc.status || '—')}</span></td>
                <td>${tags || '<span style="color:var(--color-text-faint)">—</span>'}</td>
                <td><button class="btn btn-sm" style="color:var(--color-error);" data-action="delete-doc" data-id="${this.escapeHtml(String(doc.id))}" data-vault="${this.escapeHtml(doc.vault_id || '')}" data-path="${this.escapeHtml(doc.source_path || String(doc.id))}" title="Удалить">🗑</button></td>
            </tr>`;
        }).join('');

        tbody.querySelectorAll('.docs-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('[data-action="delete-doc"]')) return;
                const doc = (this._docsAllDocs || []).find(d => String(d.id) === row.dataset.id);
                if (doc) this._openDocsSidePanel(doc);
            });
        });

        tbody.querySelectorAll('[data-action="delete-doc"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.handleDocumentsAction('delete-doc', btn);
            });
        });
    },

    _filterDocsTable(query) {
        const q = (query || '').toLowerCase();
        this._renderDocsRows(q
            ? (this._docsAllDocs || []).filter(d => (d.source_path || d.path || '').toLowerCase().includes(q))
            : this._docsAllDocs
        );
    },

    async _openDocsSidePanel(doc) {
        this._docsCurrentDoc = doc;
        const domainId = this._activeDomainId || await this._resolveDomainId();
        const panel = document.getElementById('docs-side-panel');
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = `<div style="padding:var(--space-4);"><b>${this.escapeHtml(doc.source_path || String(doc.id))}</b><div class="empty-state" style="padding:var(--space-4)">Загрузка тегов...</div></div>`;
        try {
            const resp = domainId ? await this.api.getTags(domainId) : [];
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);
            const byCampaign = (resp && resp.by_campaign) ? Object.values(resp.by_campaign).flat() : [];
            this._docsAllTags = [...globalTags, ...byCampaign];
            this._docsCurrentTags = (doc.tags || []).map(t => String(typeof t === 'object' ? t.id : t));
            this._renderDocsSidePanel(panel, doc);
        } catch (e) {
            panel.innerHTML = `<div style="padding:var(--space-4);color:var(--color-error);">Ошибка загрузки тегов: ${this.escapeHtml(e.message)}</div>`;
        }
    },

    _renderDocsSidePanel(panel, doc) {
        const fileName = (doc.source_path || String(doc.id)).split('/').pop();
        panel.innerHTML = `
            <div style="padding:var(--space-4);">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-3);">
                    <b style="font-size:var(--text-sm);">${this.escapeHtml(fileName)}</b>
                    <button data-action="close-panel" style="background:none;border:none;cursor:pointer;color:var(--color-text-muted);font-size:1.2rem;">✕</button>
                </div>
                <div style="margin-bottom:var(--space-3);">
                    <span style="font-size:var(--text-xs);color:var(--color-text-muted);">ID: ${this.escapeHtml(String(doc.id))}</span><br>
                    <span style="font-size:var(--text-xs);color:var(--color-text-muted);">Vault: ${this.escapeHtml(doc.vault_id || '—')}</span>
                </div>
                <div style="margin-bottom:var(--space-4);">
                    <p style="font-size:var(--text-sm);margin-bottom:var(--space-2);"><b>Присвоить теги:</b></p>
                    <div id="docs-tag-badges" style="display:flex;flex-wrap:wrap;gap:4px;">
                        ${this._docsAllTags.map(t => {
                            const tagIdStr = String(t.id);
                            const assigned = this._docsCurrentTags.includes(tagIdStr);
                            return `<span class="badge docs-tag-toggle" data-tag-id="${tagIdStr}" style="background:${assigned ? (t.color || 'var(--color-primary)') : 'var(--color-surface-offset)'};color:${assigned ? 'white' : 'var(--color-text)'};cursor:pointer;">${this.escapeHtml(t.name)}</span>`;
                        }).join('') || '<span style="color:var(--color-text-faint)">тегов нет</span>'}
                    </div>
                </div>
                <button class="btn btn-primary" data-action="save-doc-tags" style="width:100%;margin-bottom:var(--space-2);">Сохранить теги</button>
            </div>`;

        panel.querySelectorAll('.docs-tag-toggle').forEach(el => {
            el.addEventListener('click', () => {
                const tid = String(el.dataset.tagId);
                if (this._docsCurrentTags.includes(tid)) {
                    this._docsCurrentTags = this._docsCurrentTags.filter(x => x !== tid);
                    el.style.background = 'var(--color-surface-offset)';
                    el.style.color = 'var(--color-text)';
                } else {
                    this._docsCurrentTags.push(tid);
                    const tag = this._docsAllTags.find(t => String(t.id) === tid);
                    el.style.background = tag?.color || 'var(--color-primary)';
                    el.style.color = 'white';
                }
            });
        });

        panel.querySelector('[data-action="close-panel"]')?.addEventListener('click', () => {
            panel.style.display = 'none';
        });

        panel.querySelector('[data-action="save-doc-tags"]')?.addEventListener('click', async () => {
            try {
                await this.api.updateDocumentLabels(String(doc.id), this._docsCurrentTags);
                await this.loadDocumentsData();
                panel.style.display = 'none';
            } catch (e) {
                alert('Ошибка сохранения тегов: ' + e.message);
            }
        });
    },

    async _openTagsManagePanel() {
        const domainId = this._activeDomainId || await this._resolveDomainId();
        const panel = document.getElementById('docs-side-panel');
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = `<div style="padding:var(--space-4);"><b>Теги домена</b><div class="empty-state" style="padding:var(--space-4)">Загрузка...</div></div>`;

        if (!domainId) {
            panel.innerHTML = '<div style="padding:var(--space-4);color:var(--color-error);">Домен не выбран</div>';
            return;
        }
        await this._renderTagsManagePanel(panel, domainId);
    },

    async _renderTagsManagePanel(panel, domainId) {
        try {
            const resp = await this.api.getTags(domainId);
            const globalTags = Array.isArray(resp) ? resp : (resp.global_tags || []);

            const tagsHtml = globalTags.length
                ? globalTags.map(t => `
                    <div class="docs-tag-row" style="display:flex;align-items:center;gap:var(--space-2);margin-bottom:var(--space-2);">
                        <span class="badge" style="background:${t.color || 'var(--color-primary)'};color:white;flex:1;overflow:hidden;text-overflow:ellipsis;">${this.escapeHtml(t.name)}</span>
                        <input type="color" value="${t.color || '#01696f'}" data-tag-edit-color="${String(t.id)}" style="width:28px;height:28px;padding:1px;border:1px solid var(--color-border);border-radius:var(--radius-sm);cursor:pointer;" title="Цвет тега">
                        <button class="btn btn-sm" data-action="edit-tag-name" data-tag-id="${String(t.id)}" data-tag-name="${this.escapeHtml(t.name)}" title="Переименовать">✏️</button>
                        <button class="btn btn-sm" style="color:var(--color-error);" data-action="delete-tag" data-tag-id="${String(t.id)}" data-tag-name="${this.escapeHtml(t.name)}" title="Удалить тег">🗑</button>
                    </div>`).join('')
                : '<p style="color:var(--color-text-muted);font-size:var(--text-sm);">Тегов нет</p>';

            panel.innerHTML = `
                <div style="padding:var(--space-4);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-3);">
                        <b>Теги домена</b>
                        <button data-action="close-panel" style="background:none;border:none;cursor:pointer;color:var(--color-text-muted);font-size:1.2rem;">✕</button>
                    </div>
                    <div style="margin-bottom:var(--space-4);max-height:300px;overflow-y:auto;">${tagsHtml}</div>
                    <div style="border-top:1px solid var(--color-divider);padding-top:var(--space-3);">
                        <p style="font-size:var(--text-sm);margin-bottom:var(--space-2);"><b>Создать тег:</b></p>
                        <div style="display:flex;gap:var(--space-2);">
                            <input type="text" id="new-tag-name" placeholder="Название тега" class="input-field" style="flex:1;">
                            <input type="color" id="new-tag-color" value="#01696f" style="width:36px;height:36px;padding:2px;border:1px solid var(--color-border);border-radius:var(--radius-sm);cursor:pointer;">
                            <button class="btn btn-primary" data-action="create-tag">➕</button>
                        </div>
                    </div>
                </div>`;

            panel.querySelector('[data-action="close-panel"]')?.addEventListener('click', () => {
                panel.style.display = 'none';
            });

            panel.querySelectorAll('[data-action="delete-tag"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const tagId = btn.dataset.tagId;
                    const tagName = btn.dataset.tagName;
                    if (!confirm(`Удалить тег «${tagName}»?`)) return;
                    try {
                        await this.api.deleteTag(tagId);
                        await this._renderTagsManagePanel(panel, domainId);
                        await this.loadDocumentsData();
                    } catch (e) {
                        alert('Ошибка удаления: ' + e.message);
                    }
                });
            });

            panel.querySelectorAll('[data-action="edit-tag-name"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const tagId = btn.dataset.tagId;
                    const newName = prompt('Новое название:', btn.dataset.tagName);
                    if (!newName || !newName.trim()) return;
                    try {
                        await this.api.updateTag(tagId, { name: newName.trim() });
                        await this._renderTagsManagePanel(panel, domainId);
                    } catch (e) {
                        alert('Ошибка переименования: ' + e.message);
                    }
                });
            });

            panel.querySelectorAll('[data-tag-edit-color]').forEach(inp => {
                inp.addEventListener('change', async () => {
                    const tagId = inp.dataset.tagEditColor;
                    try {
                        await this.api.updateTag(tagId, { color: inp.value });
                        await this.loadDocumentsData();
                    } catch (e) {
                        alert('Ошибка цвета: ' + e.message);
                    }
                });
            });

            panel.querySelector('[data-action="create-tag"]')?.addEventListener('click', async () => {
                const nameInp  = panel.querySelector('#new-tag-name');
                const colorInp = panel.querySelector('#new-tag-color');
                const name = nameInp?.value?.trim();
                if (!name) return;
                try {
                    await this.api.createTag({ name, color: colorInp?.value || '#01696f', domain_id: domainId });
                    if (nameInp) nameInp.value = '';
                    await this._renderTagsManagePanel(panel, domainId);
                } catch (e) {
                    alert('Ошибка создания: ' + e.message);
                }
            });

        } catch (e) {
            panel.innerHTML = `<div style="padding:var(--space-4);color:var(--color-error);">Ошибка загрузки тегов: ${this.escapeHtml(e.message)}</div>`;
        }
    },
};
