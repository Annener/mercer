// === DB Management — Search only (v3.1) ===
class DBManager {
    constructor() {
        this.modal = document.getElementById('db-mgmt-modal');
        this.openBtn = document.getElementById('db-mgmt-btn');
        this.closeBtn = document.getElementById('db-mgmt-close-btn');

        // Поиск
        this.searchDomainSelect = document.getElementById('search-domain-select');
        this.searchQueryInput   = document.getElementById('search-query-input');
        this.searchLimitInput   = document.getElementById('search-limit');
        this.searchBtn          = document.getElementById('search-btn');
        this.searchResults      = document.getElementById('search-results');

        // Chunk detail modal
        this.chunkModal        = document.getElementById('chunk-detail-modal');
        this.chunkModalClose   = document.getElementById('chunk-detail-close');
        this.chunkModalContent = document.getElementById('chunk-detail-content');

        this.domains = [];
        this._domainsLoaded = false;

        this._initListeners();
    }

    _initListeners() {
        this.openBtn?.addEventListener('click', () => this.open());
        this.closeBtn?.addEventListener('click', () => this.close());
        this.modal?.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });

        this.searchBtn?.addEventListener('click', () => this.doSearch());
        this.searchQueryInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.doSearch();
        });

        this.chunkModalClose?.addEventListener('click', () => this.closeChunkModal());
        this.chunkModal?.addEventListener('click', (e) => {
            if (e.target === this.chunkModal) this.closeChunkModal();
        });
    }

    async open() {
        this.modal.style.display = 'flex';
        // Загружаем домены только один раз за жизнь модала
        if (!this._domainsLoaded) {
            await this._loadDomains();
            this._domainsLoaded = true;
        }
    }

    close() {
        this.modal.style.display = 'none';
    }

    // ─── Загрузка доменов ──────────────────────────────────────────────────
    async _loadDomains() {
        try {
            const resp = await chatAPI.getDomains();
            this.domains = Array.isArray(resp) ? resp : (resp.domains || []);
        } catch (e) {
            console.error('DBManager: failed to load domains', e);
            this.domains = [];
        }
        this._populateDomainSelect();
    }

    _populateDomainSelect() {
        const sel = this.searchDomainSelect;
        if (!sel) return;
        sel.innerHTML = '';
        for (const d of this.domains) {
            const opt = document.createElement('option');
            opt.value = d.domain_id;
            opt.textContent = d.display_name || this._formatDomainId(d.domain_id);
            sel.appendChild(opt);
        }
    }

    _formatDomainId(id) {
        if (!id) return '';
        return id.charAt(0).toUpperCase() + id.slice(1);
    }

    // ─── Поиск ────────────────────────────────────────────────────────────
    async doSearch() {
        const domainId = this.searchDomainSelect?.value;
        const query    = this.searchQueryInput?.value?.trim();

        // Валидация limit на клиенте — чтобы не получить 422 с бэкенда
        const rawLimit = parseInt(this.searchLimitInput?.value || '20', 10);
        const limit    = (!isNaN(rawLimit) && rawLimit >= 1 && rawLimit <= 200) ? rawLimit : 20;
        if (this.searchLimitInput) this.searchLimitInput.value = limit;

        if (!query) {
            this.searchQueryInput?.focus();
            return;
        }
        if (!domainId) return;
        if (!this.searchResults) return;

        this._setResults('<div class="empty-state">Поиск…</div>');

        try {
            const data  = await chatAPI.textSearchByDomain(domainId, query, limit);
            const items = data.results ?? [];

            if (!items.length) {
                this._setResults('<div class="empty-state">Ничего не найдено</div>');
                return;
            }

            this.searchResults.innerHTML = '';
            for (const hit of items) {
                this.searchResults.appendChild(this._renderHit(hit));
            }
        } catch (e) {
            this._setResults(`<div class="empty-state search-error">Ошибка: ${this._esc(e.message)}</div>`);
        }
    }

    _setResults(html) {
        if (this.searchResults) this.searchResults.innerHTML = html;
    }

    // ─── Карточка результата ──────────────────────────────────────────────
    _renderHit(hit) {
        const sourcePath = hit.metadata?.source_path || hit.metadata?.file_path || hit.document_id || '';
        const sourceName = sourcePath.split('/').pop() || sourcePath;
        const scoreStr   = hit.score != null ? hit.score.toFixed(3) : '—';
        const preview    = (hit.text || '').slice(0, 320);
        const hasFull    = (hit.text || '').length > 320;

        const el = document.createElement('div');
        el.className = 'search-hit';

        // Хедер — без innerHTML в атрибутах, всё через DOM API (XSS-safe)
        const header = document.createElement('div');
        header.className = 'search-hit-header';

        const srcSpan = document.createElement('span');
        srcSpan.className = 'search-hit-source';
        srcSpan.textContent = sourceName;          // textContent — безопасно
        srcSpan.title = sourcePath;                // title — безопасно

        const metaSpan = document.createElement('span');
        metaSpan.className = 'search-hit-meta';
        metaSpan.textContent = hit.document_id;

        const scoreSpan = document.createElement('span');
        scoreSpan.className = 'search-hit-score';
        scoreSpan.textContent = `score: ${scoreStr}`;

        const detailBtn = document.createElement('button');
        detailBtn.className = 'search-hit-detail-btn';
        detailBtn.title = 'Весь текст чанка';
        detailBtn.textContent = '🔍';
        detailBtn.addEventListener('click', () => this._openChunkModal(hit));

        header.append(srcSpan, metaSpan, scoreSpan, detailBtn);

        // Тело
        const body = document.createElement('div');
        body.className = 'search-hit-body';

        const previewEl = document.createElement('div');
        previewEl.className = 'search-hit-preview';
        previewEl.textContent = preview + (hasFull ? '…' : '');

        body.appendChild(previewEl);

        if (hasFull) {
            const expandBtn = document.createElement('button');
            expandBtn.className = 'search-hit-expand-btn';
            expandBtn.textContent = 'Показать полностью';
            expandBtn.addEventListener('click', () => {
                if (expandBtn.dataset.expanded) {
                    previewEl.textContent = preview + '…';
                    expandBtn.textContent  = 'Показать полностью';
                    delete expandBtn.dataset.expanded;
                } else {
                    previewEl.textContent = hit.text;
                    expandBtn.textContent  = 'Свернуть';
                    expandBtn.dataset.expanded = '1';
                }
            });
            body.appendChild(expandBtn);
        }

        el.append(header, body);
        return el;
    }

    // ─── Chunk detail modal ───────────────────────────────────────────────
    _openChunkModal(hit) {
        if (!this.chunkModal || !this.chunkModalContent) return;

        const sourcePath = hit.metadata?.source_path || hit.metadata?.file_path || hit.document_id || '—';

        // Полностью через DOM API — никакого innerHTML с данными пользователя
        this.chunkModalContent.innerHTML = '';

        const title = document.createElement('div');
        title.className = 'chunk-modal-title';
        title.textContent = sourcePath;
        this.chunkModalContent.appendChild(title);

        // Таблица метаданных
        const table = document.createElement('table');
        table.className = 'chunk-props-table';

        const fixedProps = [
            ['chunk_id',    hit.chunk_id],
            ['document_id', hit.document_id],
            ['score',       hit.score != null ? hit.score.toFixed(6) : '—'],
        ];
        for (const [k, v] of fixedProps) {
            table.appendChild(this._propsRow(k, v));
        }
        for (const [k, v] of Object.entries(hit.metadata || {})) {
            table.appendChild(this._propsRow(k, String(v)));
        }
        this.chunkModalContent.appendChild(table);

        const sectionLabel = document.createElement('div');
        sectionLabel.className = 'chunk-modal-section-label';
        sectionLabel.textContent = 'Текст чанка';
        this.chunkModalContent.appendChild(sectionLabel);

        const textEl = document.createElement('div');
        textEl.className = 'chunk-modal-text';
        textEl.textContent = hit.text || '';
        this.chunkModalContent.appendChild(textEl);

        this.chunkModal.style.display = 'flex';
    }

    _propsRow(key, value) {
        const tr = document.createElement('tr');
        const td1 = document.createElement('td');
        td1.className = 'chunk-prop-key';
        td1.textContent = key;
        const td2 = document.createElement('td');
        td2.className = 'chunk-prop-val';
        td2.textContent = value;
        tr.append(td1, td2);
        return tr;
    }

    closeChunkModal() {
        if (this.chunkModal) this.chunkModal.style.display = 'none';
    }

    // ─── Утилиты ──────────────────────────────────────────────────────────
    // _esc оставляем для обратной совместимости (используется в _setResults)
    _esc(text) {
        const d = document.createElement('div');
        d.textContent = text == null ? '' : String(text);
        return d.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dbManager = new DBManager();
});
