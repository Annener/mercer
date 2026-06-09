const DocumentsTabMixin = {
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
                <span id="docs-indexer-status" class="docs-indexer-status"></span>
            </div>
        </div>
        <div class="docs-layout">
            <div class="docs-table-wrap">
                <table class="data-table" id="docs-table">
                    <thead><tr>
                        <th>Файл</th><th>Vault</th><th>Статус</th><th>Теги</th><th style="width:48px;"></th>
                    </tr></thead>
                    <tbody id="docs-tbody">
                        <tr><td colspan="5" class="empty-state">Загрузка...</td></tr>
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
                statusSel.onchange = () => { this._docsFilterStatus = statusSel.value; this.loadDocumentsData(); };
            }

            if (domainId) {
                await this._loadTagFilterOptions(domainId);
                await this._refreshTagsPanel(domainId);
            }
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

    // ─── Таблица документов ──────────────────────────────────────────────────

    _renderDocsRows(docs) {
        const tbody = document.getElementById('docs-tbody');
        if (!tbody) return;
        if (!docs || !docs.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Документов нет</td></tr>';
            return;
        }
        const statusColor = s => ({ indexed: 'var(--color-success)', pending: 'var(--color-gold)', error: 'var(--color-error)' }[s] || 'var(--color-text-muted)');
        tbody.innerHTML = docs.map(doc => {
            const tags = (doc.tags || []).map(t =>
                `<span class="badge" style="background:${t.color || 'var(--color-primary-highlight)'};color:var(--color-text);margin-right:2px;">${this.escapeHtml(t.name)}</span>`
            ).join('');
            const fileName = (doc.source_path || doc.path || String(doc.id)).split('/').pop();
            return `<tr class="docs-row" data-id="${this.escapeHtml(String(doc.id))}" style="cursor:pointer;" title="Нажмите для редактирования тегов">
                <td title="${this.escapeHtml(doc.source_path || String(doc.id))}">${this.escapeHtml(fileName)}</td>
                <td style="color:var(--color-text-muted);font-size:var(--text-xs);">${this.escapeHtml(doc.vault_id || '—')}</td>
                <td><span style="color:${statusColor(doc.status)};font-weight:600;">${this.escapeHtml(doc.status || '—')}</span></td>
                <td>${tags || '<span style="color:var(--color-text-faint)">—</span>'}</td>
                <td><button class="btn btn-sm" style="color:var(--color-error);" data-action="delete-doc" data-id="${this.escapeHtml(String(doc.id))}" data-vault="${this.escapeHtml(doc.vault_id || '')}" data-path="${this.escapeHtml(doc.source_path || String(doc.id))}" title="Удалить">🗑</button></td>
            </tr>`;
        }).join('');

        tbody.querySelectorAll('.docs-row').forEach(row => {
            row.addEventListener('click', e => {
                if (e.target.closest('[data-action="delete-doc"]')) return;
                const doc = (this._docsAllDocs || []).find(d => String(d.id) === row.dataset.id);
                if (doc) this._openDocModal(doc);
            });
        });

        tbody.querySelectorAll('[data-action="delete-doc"]').forEach(btn => {
            btn.addEventListener('click', e => { e.stopPropagation(); this.handleDocumentsAction('delete-doc', btn); });
        });
    },

    _filterDocsTable(query) {
        const q = (query || '').toLowerCase();
        this._renderDocsRows(q
            ? (this._docsAllDocs || []).filter(d => (d.source_path || d.path || '').toLowerCase().includes(q))
            : this._docsAllDocs
        );
    },

    // ─── Модальное окно документа ───────────────────────────────────────────

    async _openDocModal(doc) {
        this._docsCurrentDoc = doc;
        const domainId = this._activeDomainId || await this._resolveDomainId();

        // Удаляем старый модал если есть
        document.getElementById('docs-modal-backdrop')?.remove();

        const backdrop = document.createElement('div');
        backdrop.id = 'docs-modal-backdrop';
        backdrop.className = 'docs-modal-backdrop';

        const fileName = (doc.source_path || doc.path || String(doc.id)).split('/').pop();
        const fullPath = doc.source_path || doc.path || '—';

        // Строим метаданные документа
        const metaRows = [
            ['ID',           doc.id           || '—'],
            ['Vault',        doc.vault_id     || '—'],
            ['Путь',        fullPath],
            ['Статус',      doc.status       || '—'],
            ['Мим-тип',    doc.mime_type    || '—'],
            ['Размер',      doc.file_size != null ? `${(doc.file_size / 1024).toFixed(1)} KB` : '—'],
            ['Страниц',   doc.page_count   != null ? doc.page_count : '—'],
            ['Чанков',    doc.chunk_count  != null ? doc.chunk_count : '—'],
            ['Добавлен', doc.created_at ? new Date(doc.created_at).toLocaleString('ru') : '—'],
            ['Изменён', doc.updated_at ? new Date(doc.updated_at).toLocaleString('ru') : '—'],
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
                        <button class="btn btn-primary docs-modal-save-btn" data-action="save-doc-tags" style="margin-top:12px;width:100%;">Сохранить теги</button>
                    </div>
                </div>
            </div>
        </div>`;

        document.body.appendChild(backdrop);
        document.body.style.overflow = 'hidden';

        // Закрытие по backdrop / Escape
        const closeModal = () => {
            backdrop.remove();
            document.body.style.overflow = '';
        };
        backdrop.addEventListener('click', e => { if (e.target === backdrop) closeModal(); });
        backdrop.querySelector('[data-action="close-modal"]').addEventListener('click', closeModal);
        const escHandler = e => { if (e.key === 'Escape') { closeModal(); document.removeEventListener('keydown', escHandler); } };
        document.addEventListener('keydown', escHandler);

        // Загрузим теги
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
            const statusEl = document.getElementById('docs-indexer-status');
            try {
                if (statusEl) statusEl.textContent = '⏳ Запуск...';
                const result = await this.api.runIndexer();
                const taskId = result?.task_id || result?.id || null;
                this._docsIndexTaskId = taskId;
                if (statusEl) statusEl.textContent = taskId ? `Задача: ${taskId}` : '✅ Запущено';
                if (taskId) this._pollIndexerStatus(taskId, statusEl);
            } catch (e) { if (statusEl) statusEl.textContent = '❌ ' + e.message; }
            return;
        }
        if (action === 'delete-doc') {
            const docId   = btn?.dataset?.id;
            const vaultId = btn?.dataset?.vault;
            const path    = btn?.dataset?.path;
            if (!docId) return;
            if (!confirm(`Удалить документ «${path || docId}»?`)) return;
            try { await this.api.deleteDocumentById(docId, vaultId || null); await this.loadDocumentsData(); }
            catch (e) { alert('Ошибка удаления: ' + e.message); }
            return;
        }
    },

    _pollIndexerStatus(taskId, statusEl) {
        if (this._docsIndexPollTimer) clearInterval(this._docsIndexPollTimer);
        let attempts = 0;
        this._docsIndexPollTimer = setInterval(async () => {
            attempts++;
            try {
                const status = await this.api.getIndexTaskState(taskId);
                const state = status?.state || status?.status || 'unknown';
                if (statusEl) statusEl.textContent = `Задача ${taskId}: ${state}`;
                if (['SUCCESS', 'FAILURE', 'REVOKED', 'completed', 'failed', 'done', 'error'].includes(state) || attempts > 60) {
                    clearInterval(this._docsIndexPollTimer); this._docsIndexPollTimer = null;
                    await this.loadDocumentsData();
                }
            } catch (_) { if (attempts > 10) { clearInterval(this._docsIndexPollTimer); this._docsIndexPollTimer = null; } }
        }, 3000);
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
