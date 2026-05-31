const DocumentsTabMixin = {
    _docsSidePanelOpen: false,
    _docsCurrentDoc: null,
    _docsAllTags: [],
    _docsCurrentTags: [],
    _docsAllDocs: [],

    async renderDocumentsTab() {
        return `
        <div class="settings-toolbar" style="gap:var(--space-3);align-items:center;display:flex;flex-wrap:wrap;">
            <button class="btn btn-primary" data-action="run-indexer">▶ Запустить индексацию</button>
            <input type="text" id="docs-search-input" placeholder="🔍 поиск по имени..." class="input-field" style="max-width:260px;">
            <span id="docs-indexer-status" style="color:var(--color-text-muted);font-size:var(--text-sm);"></span>
        </div>
        <div class="docs-layout" style="display:flex;gap:var(--space-4);margin-top:var(--space-4);">
            <div style="flex:1;overflow:auto;">
                <table class="data-table" id="docs-table">
                    <thead><tr>
                        <th>Файл</th><th>Статус</th><th>Теги</th><th style="width:48px;"></th>
                    </tr></thead>
                    <tbody id="docs-tbody">
                        <tr><td colspan="4" class="empty-state">Загрузка...</td></tr>
                    </tbody>
                </table>
            </div>
            <div id="docs-side-panel" class="docs-side-panel" style="display:none;width:300px;flex-shrink:0;"></div>
        </div>`;
    },

    async loadDocumentsData() {
        const vaultId = await this._resolveVaultId();
        if (!vaultId) {
            const tb = document.getElementById('docs-tbody');
            if (tb) tb.innerHTML = '<tr><td colspan="4" class="empty-state">Vault не найден. Добавьте Vault в настройках.</td></tr>';
            return;
        }
        try {
            const resp = await this.api.getDocuments(vaultId);
            const docs = Array.isArray(resp) ? resp : (resp.documents || []);
            this._docsAllDocs = docs;
            this._renderDocsRows(docs);
            const inp = document.getElementById('docs-search-input');
            if (inp) inp.oninput = () => this._filterDocsTable(inp.value);
        } catch (e) {
            const tb = document.getElementById('docs-tbody');
            if (tb) tb.innerHTML = `<tr><td colspan="4" class="empty-state" style="color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</td></tr>`;
        }
    },

    _renderDocsRows(docs) {
        const tbody = document.getElementById('docs-tbody');
        if (!tbody) return;
        if (!docs || !docs.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Документов нет</td></tr>';
            return;
        }
        const statusColor = (s) => ({ indexed: 'var(--color-success)', pending: 'var(--color-gold)', error: 'var(--color-error)' }[s] || 'var(--color-text-muted)');
        tbody.innerHTML = docs.map(doc => {
            const tags = (doc.tags || []).map(t =>
                `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:var(--color-text);margin-right:2px;">${this.escapeHtml(t.name)}</span>`
            ).join('');
            return `<tr class="docs-row" data-id="${this.escapeHtml(String(doc.id))}" style="cursor:pointer;">
                <td>${this.escapeHtml(doc.source_path || doc.path || String(doc.id))}</td>
                <td><span style="color:${statusColor(doc.status)};font-weight:600;">${this.escapeHtml(doc.status || '—')}</span></td>
                <td>${tags || '<span style="color:var(--color-text-faint)">—</span>'}</td>
                <td><button class="btn btn-sm" style="color:var(--color-error);" data-action="delete-doc" data-id="${this.escapeHtml(String(doc.id))}" data-path="${this.escapeHtml(doc.source_path || String(doc.id))}" title="Удалить">🗑</button></td>
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
        this._renderDocsRows(q ? (this._docsAllDocs || []).filter(d => (d.source_path || d.path || '').toLowerCase().includes(q)) : this._docsAllDocs);
    },

    async _openDocsSidePanel(doc) {
        this._docsCurrentDoc = doc;
        const vaultId = await this._resolveVaultId();
        const domainId = this._activeDomainId || await this._resolveDomainId();
        const panel = document.getElementById('docs-side-panel');
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = `<div style="padding:var(--space-4);"><b>Теги: ${this.escapeHtml(doc.source_path || String(doc.id))}</b><div class="empty-state" style="padding:var(--space-4)">Загрузка тегов...</div></div>`;
        try {
            const allTagsResp = domainId
                ? await this.api.getTags(domainId)
                : (vaultId ? await this.api.getTagsByVault(vaultId) : []);
            const grouped = Array.isArray(allTagsResp) ? { global_tags: allTagsResp, by_campaign: {} } : (allTagsResp || {});
            const globalTags = Array.isArray(grouped.global_tags) ? grouped.global_tags : [];
            const byCampaign = grouped.by_campaign && typeof grouped.by_campaign === 'object' ? Object.values(grouped.by_campaign).flat() : [];
            this._docsAllTags = [...globalTags, ...byCampaign];
            this._docsCurrentTags = Array.isArray(doc.tags) ? doc.tags.map(t => (typeof t === 'object' ? t.id : t)) : [];

            panel.innerHTML = `
                <div style="padding:var(--space-4);">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-3);">
                        <b style="font-size:var(--text-sm);">${this.escapeHtml((doc.source_path || String(doc.id)).split('/').pop())}</b>
                        <button data-action="close-panel" style="background:none;border:none;cursor:pointer;color:var(--color-text-muted);font-size:1.2rem;">✕</button>
                    </div>
                    <div style="margin-bottom:var(--space-3);">
                        <label style="font-size:var(--text-sm);color:var(--color-text-muted);">ID: ${this.escapeHtml(String(doc.id))}</label>
                    </div>
                    <div style="margin-bottom:var(--space-4);">
                        <p style="font-size:var(--text-sm);margin-bottom:var(--space-2);"><b>Присвоить теги:</b></p>
                        <div style="display:flex;flex-wrap:wrap;gap:4px;">
                            ${this._docsAllTags.map(t => {
                                const assigned = this._docsCurrentTags.includes(t.id);
                                return `<span class="badge docs-tag-toggle" data-tag-id="${t.id}" style="background:${assigned ? (t.color || 'var(--color-primary)') : 'var(--color-surface-offset)'};color:${assigned ? 'white' : 'var(--color-text)'};cursor:pointer;">${this.escapeHtml(t.name)}</span>`;
                            }).join('') || '<span style="color:var(--color-text-faint)">тегов нет</span>'}
                        </div>
                    </div>
                    <button class="btn btn-primary" data-action="save-doc-tags" style="width:100%;">Сохранить теги</button>
                </div>`;

            panel.querySelectorAll('.docs-tag-toggle').forEach(el => {
                el.addEventListener('click', () => {
                    const tid = Number(el.dataset.tagId);
                    if (this._docsCurrentTags.includes(tid)) {
                        this._docsCurrentTags = this._docsCurrentTags.filter(x => x !== tid);
                        el.style.background = 'var(--color-surface-offset)';
                        el.style.color = 'var(--color-text)';
                    } else {
                        this._docsCurrentTags.push(tid);
                        const tag = this._docsAllTags.find(t => t.id === tid);
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
                    await this.api.updateDocumentLabels(doc.id, this._docsCurrentTags);
                    await this.loadDocumentsData();
                    panel.style.display = 'none';
                } catch (e) {
                    alert('Ошибка: ' + e.message);
                }
            });

        } catch (e) {
            panel.innerHTML = `<div style="padding:var(--space-4);color:var(--color-error);">Ошибка загрузки тегов: ${this.escapeHtml(e.message)}</div>`;
        }
    },

    async handleDocumentsAction(action, btn) {
        if (action === 'run-indexer') {
            const vaultId = await this._resolveVaultId();
            if (!vaultId) { alert('Vault не выбран'); return; }
            const status = document.getElementById('docs-indexer-status');
            try {
                if (status) status.textContent = 'Запуск...';
                // Используем reindexVault (правильный метод, runIndexer=alias)
                await this.api.reindexVault(vaultId, false);
                if (status) status.textContent = 'Индексация запущена';
                setTimeout(() => { if (status) status.textContent = ''; }, 4000);
            } catch (e) {
                if (status) status.textContent = 'Ошибка: ' + e.message;
            }
            return;
        }
        if (action === 'delete-doc') {
            const id = btn.dataset?.id || btn;
            const path = typeof btn === 'object' ? btn.dataset?.path || id : id;
            if (!confirm(`Удалить документ "${path}"?`)) return;
            try {
                await this.api.deleteDocumentById(String(id));
                await this.loadDocumentsData();
            } catch (e) {
                alert('Ошибка: ' + e.message);
            }
        }
    },
};

Object.assign(SettingsManager.prototype, DocumentsTabMixin);
