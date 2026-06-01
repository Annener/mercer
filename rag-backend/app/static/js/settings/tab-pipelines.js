const PipelinesTabMixin = {
    async renderPipelinesTab() {
        const domainId = this._activeDomainId || null;
        let pipelines = await this.api.getPipelines(domainId);
        if (!Array.isArray(pipelines)) pipelines = [];

        // Загружаем домены для domain-selector
        let domains = [];
        try {
            const dr = await this.api.getSettingsDomains();
            domains = Array.isArray(dr) ? dr : (dr.domains || []);
        } catch (_) {}

        const domainSelector = `
            <select id="pipelines-domain-select" class="input-field" style="max-width:200px;height:36px;">
                <option value="">Все домены</option>
                ${domains.map(d => {
                    const did = this.escapeHtml(d.domain_id || d.id || '');
                    const dname = this.escapeHtml(d.display_name || d.domain_id || d.id || '');
                    const sel = (d.domain_id || d.id) === domainId ? ' selected' : '';
                    return `<option value="${did}"${sel}>${dname}</option>`;
                }).join('')}
            </select>`;

        const toolbar = `<div class="settings-toolbar">
            <button class="btn btn-primary" data-action="new-pipeline">+ Новый pipeline</button>
            ${domainSelector}
        </div>`;
        if (pipelines.length === 0) return toolbar + `<div class="empty-state">Pipeline'ов нет</div>`;
        return toolbar + `<div class="settings-grid">${pipelines.map(pipeline => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(pipeline.name)}</h3>
                    <p>${this.escapeHtml(pipeline.pipeline_id || pipeline.id)} · ${pipeline.steps?.length || 0} шаг.</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(String(pipeline.id))}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">✏️ Редактировать</button>
                        <button class="card-menu-item" data-action="activate-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">▶️ Активировать</button>
                        <button class="card-menu-item" data-action="deactivate-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">⏸️ Деактивировать</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">🗑️ Удалить</button>
                    </div>
                </div>
                <div><span class="badge ${pipeline.is_active ? 'ok' : 'muted'}">${pipeline.is_active ? 'active' : 'inactive'}</span></div>
            </article>`).join('')}</div>`;
    },

    _attachPipelinesTabListeners(container) {
        const sel = container.querySelector('#pipelines-domain-select');
        if (sel) {
            sel.addEventListener('change', () => {
                this._activeDomainId = sel.value || null;
                this.loadTab('pipelines');
            });
        }
    },

    async showPipelineModal() {
        if (!window.PipelineBuilder || typeof window.PipelineBuilder.openCreate !== 'function') {
            alert('Редактор pipeline не загружен');
            return;
        }
        await window.PipelineBuilder.openCreate(this.api, () => this.loadTab(this.currentTab));
    },

    async showPipelineEditModal(pipelineId) {
        const domainId = this._activeDomainId || null;
        const all = await this.api.getPipelines(domainId);
        const list = Array.isArray(all) ? all : (all.pipelines || []);
        const pipeline = list.find(p => String(p.id) === String(pipelineId));
        if (!pipeline) {
            alert('Pipeline не найден');
            return;
        }
        if (!window.PipelineBuilder || typeof window.PipelineBuilder.openEdit !== 'function') {
            alert('Редактор pipeline не загружен');
            return;
        }
        await window.PipelineBuilder.openEdit(this.api, pipeline, () => this.loadTab(this.currentTab));
    },
};

Object.assign(SettingsManager.prototype, PipelinesTabMixin);
