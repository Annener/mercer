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

    async _resolveVaultId() {
        if (this._activeVaultId) return this._activeVaultId;
        try {
            const vaults = await this.api.getSettingsVaults();
            const arr = Array.isArray(vaults) ? vaults : [];
            // Приоритет: enabled vault, затем любой первый
            const active = arr.find(v => v.enabled) || arr[0];
            this._activeVaultId = active?.vault_id || active?.id || null;
        } catch (e) {
            this._activeVaultId = null;
        }
        return this._activeVaultId;
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
        const panel = document.getElementById('docs-side-panel');
        if (!panel) return;
        panel.style.display = 'block';
        panel.innerHTML = `<div style="padding:var(--space-4);"><b>Теги: ${this.escapeHtml(doc.source_path || String(doc.id))}</b><div class="empty-state" style="padding:var(--space-4)">Загрузка тегов...</div></div>`;
        try {
            const allTagsResp = vaultId ? await this.api.getTags(vaultId) : [];
            const grouped = Array.isArray(allTagsResp) ? { global_tags: allTagsResp, by_campaign: {} } : (allTagsResp || {});
            const globalTags = Array.isArray(grouped.global_tags) ? grouped.global_tags : [];
            const byCampaign = grouped.by_campaign && typeof grouped.by_campaign === 'object' ? Object.values(grouped.by_campaign).flat() : [];
            this._docsAllTags = [...globalTags, ...byCampaign];
            this._docsCurrentTags = [...(doc.tags || [])];
            this._renderDocsSidePanel(doc);
        } catch (e) {
            panel.innerHTML = `<div style="padding:var(--space-4);color:var(--color-error)">Ошибка: ${this.escapeHtml(e.message)}</div>`;
        }
    },

    _renderDocsSidePanel(doc) {
        const panel = document.getElementById('docs-side-panel');
        if (!panel) return;
        const currentTagIds = new Set(this._docsCurrentTags.map(t => String(t.id)));
        const available = this._docsAllTags.filter(t => !currentTagIds.has(String(t.id)));
        const currentHtml = this._docsCurrentTags.length
            ? this._docsCurrentTags.map(t =>
                `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:var(--color-text);margin:2px;cursor:pointer;" data-remove-tag="${this.escapeHtml(String(t.id))}">${this.escapeHtml(t.name)} ×</span>`
              ).join('')
            : '<span style="color:var(--color-text-faint)">нет тегов</span>';
        const availableOptions = available.map(t =>
            `<option value="${this.escapeHtml(String(t.id))}">${this.escapeHtml(t.name)}</option>`
        ).join('');
        const shortName = (doc.source_path || String(doc.id)).split('/').pop();

        panel.innerHTML = `
        <div style="padding:var(--space-4);border-left:1px solid var(--color-border);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-4);">
                <b style="font-size:var(--text-sm);">Теги: ${this.escapeHtml(shortName)}</b>
                <button class="btn" style="padding:2px 8px;" id="docs-close-panel">✕</button>
            </div>
            <div style="margin-bottom:var(--space-3);">
                <div style="font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:var(--space-2);">Текущие теги:</div>
                <div id="docs-current-tags">${currentHtml}</div>
            </div>
            <div style="margin-bottom:var(--space-4);">
                <div style="font-size:var(--text-xs);color:var(--color-text-muted);margin-bottom:var(--space-2);">Добавить тег:</div>
                <div style="display:flex;gap:var(--space-2);">
                    <select id="docs-tag-select" class="input-field" style="flex:1;">
                        <option value="">— выбрать —</option>
                        ${availableOptions}
                    </select>
                    <button class="btn btn-secondary" style="padding:4px 10px;font-size:var(--text-sm);" id="docs-add-tag-btn">+ Добавить</button>
                </div>
            </div>
            <button class="btn btn-primary" style="width:100%;" id="docs-save-tags-btn">Сохранить</button>
        </div>`;

        panel.querySelector('#docs-close-panel').onclick = () => { panel.style.display = 'none'; };

        panel.querySelectorAll('[data-remove-tag]').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.dataset.removeTag;
                this._docsCurrentTags = this._docsCurrentTags.filter(t => String(t.id) !== id);
                this._renderDocsSidePanel(doc);
            });
        });

        panel.querySelector('#docs-add-tag-btn').onclick = () => {
            const sel = panel.querySelector('#docs-tag-select');
            const tagId = sel?.value;
            if (!tagId) return;
            const tag = this._docsAllTags.find(t => String(t.id) === tagId);
            if (tag) { this._docsCurrentTags.push(tag); this._renderDocsSidePanel(doc); }
        };

        panel.querySelector('#docs-save-tags-btn').onclick = async () => {
            try {
                await this.api.updateDocumentLabels(doc.id, this._docsCurrentTags.map(t => t.id));
                doc.tags = [...this._docsCurrentTags];
                this._renderDocsRows(this._docsAllDocs);
                const btn = panel.querySelector('#docs-save-tags-btn');
                if (btn) { btn.textContent = '✅ Сохранено'; setTimeout(() => { if (btn) btn.textContent = 'Сохранить'; }, 1500); }
            } catch (e) { alert('Ошибка: ' + e.message); }
        };
    },

    async handleDocumentsAction(action, target) {
        if (action === 'run-indexer') {
            const vaultId = await this._resolveVaultId();
            if (!vaultId) { alert('Vault не найден. Добавьте Vault в настройках.'); return; }
            const status = document.getElementById('docs-indexer-status');
            if (status) status.textContent = '⏳ Индексация запущена...';
            try {
                await this.api.reindexVault(vaultId, false);
                if (status) status.textContent = '✅ Индексация запущена';
                setTimeout(() => this.loadDocumentsData(), 3000);
            } catch (e) {
                if (status) status.textContent = `❌ ${e.message}`;
            }
            return;
        }
        if (action === 'delete-doc') {
            const docId = target.dataset.id;
            const docPath = target.dataset.path;
            if (!confirm(`Удалить ${docPath}?\nФизический файл останется, будут удалены только данные индекса.`)) return;
            try {
                await this.api.deleteDocumentById(docId);
                this._docsAllDocs = (this._docsAllDocs || []).filter(d => String(d.id) !== docId);
                this._renderDocsRows(this._docsAllDocs);
                const panel = document.getElementById('docs-side-panel');
                if (this._docsCurrentDoc && String(this._docsCurrentDoc.id) === docId && panel) {
                    panel.style.display = 'none';
                }
            } catch (e) { alert('Ошибка удаления: ' + e.message); }
        }
    },
};

Object.assign(SettingsManager.prototype, DocumentsTabMixin);
