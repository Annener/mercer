const PipelinesTabMixin = {
    async renderPipelinesTab() {
        let pipelines = await this.api.getPipelines();
        if (!Array.isArray(pipelines)) pipelines = [];
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-pipeline">+ Новый pipeline</button></div>`;
        if (pipelines.length === 0) return toolbar + `<div class="empty-state">Pipeline'ов нет</div>`;
        return toolbar + `<div class="settings-grid">${pipelines.map(pipeline => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(pipeline.name)}</h3>
                    <p>${this.escapeHtml(pipeline.pipeline_id || pipeline.id)} · ${pipeline.steps?.length || 0} шаг.</p>
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(pipeline.id)}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-pipeline" data-id="${this.escapeHtml(pipeline.id)}">✏️ Редактировать</button>
                        <button class="card-menu-item" data-action="activate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">▶️ Активировать</button>
                        <button class="card-menu-item" data-action="deactivate-pipeline" data-id="${this.escapeHtml(pipeline.id)}">⏸️ Деактивировать</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-pipeline" data-id="${this.escapeHtml(pipeline.id)}">🗑️ Удалить</button>
                    </div>
                </div>
                <div><span class="badge ${pipeline.is_active ? 'ok' : 'muted'}">${pipeline.is_active ? 'active' : 'inactive'}</span></div>
            </article>`).join('')}</div>`;
    },

    async showPipelineModal() {
        if (!window.PipelineBuilder || typeof window.PipelineBuilder.openCreate !== 'function') {
            alert('Редактор pipeline не загружен');
            return;
        }
        await window.PipelineBuilder.openCreate(this.api, () => this.loadTab(this.currentTab));
    },

    async showPipelineEditModal(pipelineUuid) {
        const all = await this.api.getPipelines();
        const list = Array.isArray(all) ? all : (all.pipelines || []);
        const pipeline = list.find(p => p.id === pipelineUuid);
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
