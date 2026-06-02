const DomainsTabMixin = {
    // S5-A fix: вместо getDomains() (путь /config/domains, read-only sidebar)
    // используем getSettingsDomains() (путь /api/settings/domains, CRUD)
    async renderDomainsTab() {
        const resp = await this.api.getSettingsDomains();
        const domains = Array.isArray(resp) ? resp : (resp.domains || []);
        const toolbar = `<div class="settings-toolbar"><button class="btn btn-primary" data-action="new-domain">+ Новый домен</button></div>`;
        if (!domains.length) return toolbar + `<div class="empty-state">Нет доменов</div>`;
        return toolbar + `<div class="settings-grid">${domains.map(domain => `
            <article class="settings-card">
                <div>
                    <h3>${this.escapeHtml(domain.display_name)}</h3>
                    <p>${this.escapeHtml(domain.domain_id)}</p>
                </div>
                <div class="settings-actions">
                    <button class="btn btn-sm btn-secondary" data-action="edit-domain" data-id="${this.escapeHtml(domain.domain_id)}">Изменить</button>
                    <button class="btn btn-sm btn-secondary" data-action="manage-prompts" data-id="${this.escapeHtml(domain.domain_id)}">Промпты</button>
                    <button class="btn btn-sm btn-secondary" data-action="manage-fields" data-id="${this.escapeHtml(domain.domain_id)}">Поля</button>
                    <button class="btn btn-sm btn-danger" data-action="delete-domain" data-id="${this.escapeHtml(domain.domain_id)}"${domain.is_system ? ' disabled' : ''}>Удалить</button>
                </div>
                <div>
                    <span class="badge ${domain.enabled ? 'ok' : 'muted'}">${domain.enabled ? 'включён' : 'выключен'}</span>
                </div>
            </article>`).join('')}</div>`;
    },

    // S5-A fix: в showDomainModal также заменяем getDomains на getSettingsDomains
    async showDomainModal(domainId = null) {
        let domain = null;
        if (domainId) {
            const resp = await this.api.getSettingsDomains();
            const domains = Array.isArray(resp) ? resp : (resp.domains || []);
            domain = domains.find(d => d.domain_id === domainId) || null;
        }
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content">
                <h3>${domain ? 'Редактировать домен' : 'Новый домен'}</h3>
                <div class="form-group">
                    <label>ID домена</label>
                    <input type="text" id="domain-id-input" value="${this.escapeHtml(domain?.domain_id || '')}"
                        ${domain ? 'disabled' : ''} pattern="[a-z0-9_]{3,32}"
                        title="3-32 символа, только a-z, 0-9 и _">
                </div>
                <div class="form-group">
                    <label>Отображаемое название</label>
                    <input type="text" id="domain-name-input" value="${this.escapeHtml(domain?.display_name || '')}">
                </div>
                <div class="form-group">
                    <label>Описание</label>
                    <textarea id="domain-desc-input">${this.escapeHtml(domain?.description || '')}</textarea>
                </div>
                <div class="domain-enabled-row">
                    <div class="domain-enabled-label">
                        <span class="domain-enabled-title">Домен активен</span>
                        <span class="domain-enabled-hint">Если выключить — домен не будет отображаться в списке при создании чата.</span>
                    </div>
                    <label class="toggle-switch">
                        <input type="checkbox" id="domain-enabled-input" ${domain?.enabled !== false ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
                <div class="modal-actions">
                    <button id="domain-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="domain-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.querySelector('#domain-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.querySelector('#domain-save-btn')?.addEventListener('click', async () => {
            const domainIdValue = modal.querySelector('#domain-id-input').value.trim();
            if (!domainId && !/^[a-z0-9_]{3,32}$/.test(domainIdValue)) {
                alert('ID домена должен содержать от 3 до 32 символов, только a-z, 0-9 и _');
                return;
            }
            const data = {
                display_name: modal.querySelector('#domain-name-input').value,
                description: modal.querySelector('#domain-desc-input').value,
                enabled: modal.querySelector('#domain-enabled-input').checked,
            };
            if (domainId) await this.api.updateDomain(domainId, data);
            else { data.domain_id = domainIdValue; await this.api.createDomain(data); }
            modal.remove();
            await this.loadTab(this.currentTab);
        });
    },

    async showPromptsModal(domainId) {
        const PROMPT_DESCRIPTIONS = {
            system: {
                title: 'Системный промпт',
                desc: 'Главная инструкция для ИИ — задаёт роль, стиль ответов и правила поведения.',
                vars: '{{domain_id}}, {{domain_name}}',
            },
            clarification: {
                title: 'Промпт уточнения',
                desc: 'Используется когда ИИ решает задать уточняющий вопрос перед ответом.',
                vars: '{{question}}, {{clarification_fields}}',
            },
            planner: {
                title: 'Промпт планировщика',
                desc: 'Инструкция для этапа планирования — ИИ решает какие источники знаний использовать.',
                vars: '{{question}}, {{available_vaults}}, {{domain_name}}',
            },
            pipeline_router: {
                title: 'Роутер пайплайна',
                desc: 'Определяет какой пайплайн обработки выбрать для входящего запроса.',
                vars: '{{question}}, {{pipelines}}',
            },
        };
        try {
            const prompts = await this.api.getDomainPrompts(domainId);
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content" style="max-width:min(95vw,1200px); max-height:90vh; overflow-y:auto;">
                    <h3>Промпты домена: ${this.escapeHtml(domainId)}</h3>
                    ${Object.entries(prompts).map(([type, content]) => {
                        const info = PROMPT_DESCRIPTIONS[type] || { title: type, desc: '', vars: '' };
                        return `
                            <div class="prompt-block" style="margin-bottom:24px;">
                                <div style="margin-bottom:8px;">
                                    <strong style="font-size:1.05em;">${this.escapeHtml(info.title)}</strong>
                                    <p style="font-size:0.9em;color:#666;margin:4px 0 2px;">${this.escapeHtml(info.desc)}</p>
                                    ${info.vars ? `<p style="font-size:0.8em;color:#999;font-family:monospace;">Переменные: ${this.escapeHtml(info.vars)}</p>` : ''}
                                </div>
                                <textarea class="prompt-editor" data-type="${this.escapeHtml(type)}" rows="10"
                                    style="width:100%;box-sizing:border-box;font-size:13px;">${this.escapeHtml(content)}</textarea>
                            </div>`;
                    }).join('')}
                    <div class="modal-actions">
                        <button id="prompts-save-btn" class="btn btn-primary">Сохранить все промпты</button>
                        <button id="prompts-cancel-btn" class="btn btn-secondary">Отмена</button>
                    </div>
                </div>`;
            document.body.appendChild(modal);
            modal.querySelector('#prompts-cancel-btn').addEventListener('click', () => modal.remove());
            modal.querySelector('#prompts-save-btn').addEventListener('click', async () => {
                const textareas = modal.querySelectorAll('.prompt-editor');
                for (const ta of textareas) {
                    await this.api.updateDomainPrompt(domainId, ta.dataset.type, ta.value);
                }
                alert('Промпты успешно сохранены!');
                modal.remove();
            });
        } catch (err) {
            alert('Ошибка загрузки промптов: ' + err.message);
        }
    },

    // S12-A: новый модал для управления DomainClarificationField
    async showFieldsModal(domainId) {
        let fields = [];
        try {
            fields = await this.api.getDomainFields(domainId);
        } catch (err) {
            alert('Ошибка загрузки полей: ' + err.message);
            return;
        }
        let workingFields = fields.map(f => ({ ...f }));

        const renderRows = () => workingFields.map((f, i) => `
            <tr data-idx="${i}">
                <td><input class="field-name" value="${this.escapeHtml(f.field_name || '')}" placeholder="field_name"></td>
                <td><input class="field-label" value="${this.escapeHtml(f.label || '')}" placeholder="Название"></td>
                <td><input class="field-hint" value="${this.escapeHtml(f.hint || '')}" placeholder="Подсказка"></td>
                <td style="text-align:center;">
                    <input type="checkbox" class="field-required" ${f.required ? 'checked' : ''}>
                </td>
                <td>
                    <button class="btn btn-sm btn-danger field-delete-btn" data-idx="${i}">×</button>
                </td>
            </tr>`).join('');

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width:min(95vw,860px); max-height:90vh; overflow-y:auto;">
                <h3>Поля уточнения: ${this.escapeHtml(domainId)}</h3>
                <p style="font-size:0.9em;color:#666;margin-bottom:12px;">
                    Добавьте поля, которые ИИ будет запрашивать для уточнения запроса. Каждое поле — отдельная запись в таблице DomainClarificationField.
                </p>
                <table class="data-table" id="fields-table" style="table-layout:fixed; width:100%;">
                    <thead>
                        <tr>
                            <th>field_name</th>
                            <th>Название</th>
                            <th>Подсказка</th>
                            <th style="width:70px;text-align:center;">Обяз.</th>
                            <th style="width:50px;"></th>
                        </tr>
                    </thead>
                    <tbody id="fields-tbody">${renderRows()}</tbody>
                </table>
                <button class="btn btn-secondary" id="fields-add-btn" style="margin-top:12px;">+ Добавить поле</button>
                <div class="modal-actions" style="margin-top:16px;">
                    <button id="fields-save-btn" class="btn btn-primary">Сохранить</button>
                    <button id="fields-cancel-btn" class="btn btn-secondary">Отмена</button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        const tbody = modal.querySelector('#fields-tbody');

        const syncFromDOM = () => {
            workingFields = Array.from(tbody.querySelectorAll('tr[data-idx]')).map((row, i) => ({
                field_name: row.querySelector('.field-name').value.trim(),
                label:      row.querySelector('.field-label').value.trim(),
                hint:       row.querySelector('.field-hint').value.trim(),
                required:   row.querySelector('.field-required').checked,
                order:      i,
            }));
        };

        tbody.addEventListener('click', (e) => {
            const delBtn = e.target.closest('.field-delete-btn');
            if (!delBtn) return;
            syncFromDOM();
            const idx = parseInt(delBtn.dataset.idx, 10);
            workingFields.splice(idx, 1);
            tbody.innerHTML = renderRows();
        });

        modal.querySelector('#fields-add-btn').addEventListener('click', () => {
            syncFromDOM();
            workingFields.push({ field_name: '', label: '', hint: '', required: false, order: workingFields.length });
            tbody.innerHTML = renderRows();
        });

        modal.querySelector('#fields-cancel-btn').addEventListener('click', () => modal.remove());

        modal.querySelector('#fields-save-btn').addEventListener('click', async () => {
            syncFromDOM();
            const names = workingFields.map(f => f.field_name);
            const invalid = names.some(n => !n || !/^[a-z0-9_]{1,64}$/.test(n));
            if (invalid) {
                alert('field_name: обязательное поле, только a-z, 0-9, _ (1-64 символа)');
                return;
            }
            if (names.length !== new Set(names).size) {
                alert('Имена полей (field_name) должны быть уникальными');
                return;
            }
            const saveBtn = modal.querySelector('#fields-save-btn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Сохранение...';
            try {
                await this.api.updateDomainFields(domainId, workingFields);
                modal.remove();
            } catch (err) {
                saveBtn.disabled = false;
                saveBtn.textContent = 'Сохранить';
                alert('Ошибка сохранения: ' + err.message);
            }
        });
    },
};

Object.assign(SettingsManager.prototype, DomainsTabMixin);
