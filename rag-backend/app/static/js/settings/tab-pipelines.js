const PipelinesTabMixin = {
    async renderPipelinesTab() {
        const domainId = this._activeDomainId || null;
        let pipelines = await this.api.getPipelines(domainId);
        if (!Array.isArray(pipelines)) pipelines = [];

        let domains = [];
        try {
            const dr = await this.api.getSettingsDomains();
            domains = Array.isArray(dr) ? dr : (dr.domains || []);
        } catch (_) {}

        const railHtml = window.DomainRail
            ? window.DomainRail.render(domains, domainId, this.escapeHtml.bind(this))
            : '';

        const toolbar = `<div class="settings-toolbar">
            <button class="btn btn-primary" data-action="new-pipeline">+ Новый пайплайн</button>
        </div>`;

        const cardsHtml = pipelines.length === 0
            ? toolbar + `<div class="empty-state">Пайплайны отсутствуют</div>`
            : toolbar + `<div class="settings-grid">${pipelines.map(pipeline => `
            <article class="settings-card" data-id="${this.escapeHtml(String(pipeline.id))}">
                <div>
                    <h3>${this.escapeHtml(pipeline.name)}</h3>
                    <p>${this.escapeHtml(pipeline.pipeline_id || pipeline.id)} · ${pipeline.steps?.length || 0} шаг.</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(String(pipeline.id))}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">&#9999;&#65039; Редактировать</button>
                        <button class="card-menu-item" data-action="activate-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">&#9654;&#65039; Активировать</button>
                        <button class="card-menu-item" data-action="deactivate-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">&#9208;&#65039; Деактивировать</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-pipeline" data-id="${this.escapeHtml(String(pipeline.id))}">&#128465;&#65039; Удалить</button>
                    </div>
                </div>
                <div><span class="badge ${pipeline.is_active ? 'ok' : 'muted'}">${pipeline.is_active ? 'active' : 'inactive'}</span></div>
            </article>`).join('')}</div>`;

        return `<div class="domain-rail-layout">
            ${railHtml}
            <div class="domain-rail-pane">${cardsHtml}</div>
        </div>`;
    },

    _attachPipelinesTabListeners(container) {
        if (window.DomainRail) {
            window.DomainRail.attach(container, (domainId) => {
                this._activeDomainId = domainId || null;
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
