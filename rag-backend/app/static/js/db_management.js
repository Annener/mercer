// === DB Management — Search only (v3) ===
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
        await this._loadDomains();
    }

    close() {
        this.modal.style.display = 'none';
    }

    // ─── Загрузка доменов ──────────────────────────────────────────────────
    async _loadDomains() {
        try {
            const resp = await chatAPI.getDomains();
            // getDomains() возвращает массив DomainRead или {domains: [...]}
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
        const prev = sel.value;
        sel.innerHTML = '';
        for (const d of this.domains) {
            const opt = document.createElement('option');
            opt.value = d.domain_id;
            // display_name из DomainRead; fallback — форматированный domain_id
            opt.textContent = d.display_name || this._formatDomainId(d.domain_id);
            sel.appendChild(opt);
        }
        // Восстанавливаем выбранное
        if (prev && [...sel.options].some(o => o.value === prev)) {
            sel.value = prev;
        }
    }

    _formatDomainId(id) {
        if (!id) return '';
        const map = { dnd: 'D&D', work: 'Работа' };
        return map[id] || (id.charAt(0).toUpperCase() + id.slice(1));
    }

    // ─── Поиск ────────────────────────────────────────────────────────────
    async doSearch() {
        const domainId = this.searchDomainSelect?.value;
        const query    = this.searchQueryInput?.value?.trim();
        const limit    = parseInt(this.searchLimitInput?.value || '20', 10);

        if (!query) {
            this.searchQueryInput?.focus();
            return;
        }
        if (!domainId) return;
        if (!this.searchResults) return;

        this.searchResults.innerHTML = '<div class="empty-state">Поиск…</div>';

        try {
            const data  = await chatAPI.textSearchByDomain(domainId, query, limit);
            // Ответ: TextSearchResponse { results: SearchHit[] }
            // SearchHit: { chunk_id, document_id, text, metadata, score }
            const items = data.results ?? [];

            if (!items.length) {
                this.searchResults.innerHTML = '<div class="empty-state">Ничего не найдено</div>';
                return;
            }

            this.searchResults.innerHTML = '';
            for (const hit of items) {
                this.searchResults.appendChild(this._renderHit(hit));
            }
        } catch (e) {
            this.searchResults.innerHTML =
                `<div class="empty-state" style="color:var(--color-error, #c0392b)">Ошибка: ${this._esc(e.message)}</div>`;
        }
    }

    // ─── Карточка результата ──────────────────────────────────────────────
    _renderHit(hit) {
        // source_path лежит в metadata (заполняется indexer'ом)
        const sourcePath = hit.metadata?.source_path || hit.metadata?.file_path || hit.document_id || '';
        const sourceName = sourcePath.split('/').pop() || sourcePath;
        const scoreStr   = hit.score != null ? hit.score.toFixed(3) : '—';
        const preview    = (hit.text || '').slice(0, 320);
        const hasFull    = (hit.text || '').length > 320;

        const el = document.createElement('div');
        el.className = 'search-hit';
        el.innerHTML = `
            <div class="search-hit-header">
                <span class="search-hit-source" title="${this._esc(sourcePath)}">${this._esc(sourceName)}</span>
                <span class="search-hit-meta">${this._esc(hit.document_id)}</span>
                <span class="search-hit-score">score: ${scoreStr}</span>
                <button class="search-hit-detail-btn" title="Весь текст чанка">🔍</button>
            </div>
            <div class="search-hit-body">
                <div class="search-hit-preview">${this._esc(preview)}${hasFull ? '…' : ''}</div>
                ${hasFull ? '<button class="search-hit-expand-btn">Показать полностью</button>' : ''}
            </div>
        `;

        el.querySelector('.search-hit-detail-btn').addEventListener('click', () => this._openChunkModal(hit));

        if (hasFull) {
            const preview$ = el.querySelector('.search-hit-preview');
            const expand$  = el.querySelector('.search-hit-expand-btn');
            expand$.addEventListener('click', () => {
                if (expand$.dataset.expanded) {
                    preview$.textContent = preview + '…';
                    expand$.textContent  = 'Показать полностью';
                    delete expand$.dataset.expanded;
                } else {
                    preview$.textContent = hit.text;
                    expand$.textContent  = 'Свернуть';
                    expand$.dataset.expanded = '1';
                }
            });
        }

        return el;
    }

    // ─── Chunk detail modal ───────────────────────────────────────────────
    _openChunkModal(hit) {
        if (!this.chunkModal || !this.chunkModalContent) return;

        const sourcePath = hit.metadata?.source_path || hit.metadata?.file_path || hit.document_id || '—';

        // Строим таблицу мета-полей
        const metaRows = Object.entries(hit.metadata || {}).map(([k, v]) =>
            `<tr>
                <td class="chunk-prop-key">${this._esc(k)}</td>
                <td class="chunk-prop-val">${this._esc(String(v))}</td>
            </tr>`
        ).join('');

        this.chunkModalContent.innerHTML = `
            <div class="chunk-modal-title">${this._esc(sourcePath)}</div>
            <table class="chunk-props-table">
                <tr><td class="chunk-prop-key">chunk_id</td><td class="chunk-prop-val">${this._esc(hit.chunk_id)}</td></tr>
                <tr><td class="chunk-prop-key">document_id</td><td class="chunk-prop-val">${this._esc(hit.document_id)}</td></tr>
                <tr><td class="chunk-prop-key">score</td><td class="chunk-prop-val">${hit.score != null ? hit.score.toFixed(6) : '—'}</td></tr>
                ${metaRows}
            </table>
            <div class="chunk-modal-section-label">Текст чанка</div>
            <div class="chunk-modal-text">${this._esc(hit.text || '')}</div>
        `;
        this.chunkModal.style.display = 'flex';
    }

    closeChunkModal() {
        if (this.chunkModal) this.chunkModal.style.display = 'none';
    }

    // ─── Утилиты ──────────────────────────────────────────────────────────
    _esc(text) {
        const d = document.createElement('div');
        d.textContent = text == null ? '' : String(text);
        return d.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.dbManager = new DBManager();
});
