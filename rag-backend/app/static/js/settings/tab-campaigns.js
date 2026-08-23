const CampaignsTabMixin = {
    async renderCampaignsTab() {
        const domainId = this._activeDomainId || null;
        let campaigns = [];
        try {
            const resp = await this.api.getCampaigns(domainId);
            campaigns = Array.isArray(resp) ? resp : (resp.campaigns || []);
        } catch (e) { /* ignore */ }

        // Загружаем домены для Domain Rail
        let domains = [];
        try {
            const dr = await this.api.getSettingsDomains();
            domains = Array.isArray(dr) ? dr : (dr.domains || []);
        } catch (_) {}

        // Для каждой кампании параллельно проверяем наличие state_fields
        // и active state version — это определяет UI Initial State.
        const initialStateInfo = await this._loadInitialStateInfo(campaigns);

        const railHtml = window.DomainRail
            ? window.DomainRail.render(domains, domainId, this.escapeHtml.bind(this))
            : '';

        const toolbar = `<div class="settings-toolbar">
            <button class="btn btn-primary" data-action="new-campaign">+ Новая кампания</button>
        </div>`;

        const cardsHtml = !campaigns.length
            ? toolbar + '<div class="empty-state">Кампаний нет. Создайте первую.</div>'
            : toolbar + `<div class="settings-grid">${campaigns.map(c => `
            <article class="settings-card" data-id="${this.escapeHtml(String(c.id))}">
                <div>
                    <h3>${this.escapeHtml(c.name)}</h3>
                    <p style="color:var(--color-text-muted);font-size:var(--text-sm);">${this.escapeHtml(c.description || '')}</p>
                    ${this._renderInitialStateBadge(c.id, initialStateInfo.get(String(c.id)))}
                </div>
                <div class="card-menu-container">
                    <button class="card-menu-toggle" data-id="${this.escapeHtml(String(c.id))}" aria-label="Меню">⋮</button>
                    <div class="card-menu">
                        <button class="card-menu-item" data-action="edit-campaign" data-id="${this.escapeHtml(String(c.id))}">&#9999;&#65039; Редактировать</button>
                        <button class="card-menu-item card-menu-danger" data-action="delete-campaign" data-id="${this.escapeHtml(String(c.id))}">&#128465;&#65039; Удалить</button>
                    </div>
                </div>
            </article>`).join('')}</div>`;

        return `<div class="domain-rail-layout">
            ${railHtml}
            <div class="domain-rail-pane">${cardsHtml}</div>
        </div>`;
    },

    /**
     * Для каждой кампании параллельно проверяем:
     *   - список state_fields (нужен для отображения в карточке);
     *   - есть ли active state version (если да — initial уже применён).
     *
     * Возвращает Map<campaignId, { fields, hasFields, hasActiveState }>.
     * Любая ошибка на кампании трактуется как «нет данных» (UI просто скроет блок).
     */
    async _loadInitialStateInfo(campaigns) {
        const result = new Map();
        if (!window.chatAPI) return result;
        const checks = await Promise.allSettled(
            (campaigns || []).map(async (c) => {
                const cid = String(c.id);
                const [fields, activeState] = await Promise.all([
                    this.api.getStateFields(cid).catch(() => []),
                    this.api.getActiveCampaignState(cid).catch(() => null),
                ]);
                const fieldsArr = Array.isArray(fields) ? fields : [];
                const hasFields = fieldsArr.length > 0;
                const hasActiveState = !!(activeState && activeState.summary);
                result.set(cid, { fields: fieldsArr, hasFields, hasActiveState });
            })
        );
        for (const r of checks) {
            if (r.reason) console.warn('Initial State info check failed:', r.reason);
        }
        return result;
    },

    /**
     * Возвращает HTML-фрагмент для слота «Поля Campaign State» в карточке кампании.
     * Больше не используется — управление полями вынесено в модалку редактирования.
     * Оставлено как no-op, чтобы случайные старые вызовы не падали.
     */
    _renderStateFieldsSlot() {
        return '';
    },

    /**
     * Компактный индикатор Initial State в карточке кампании.
     *   - если applied → badge «Initial State применён»;
     *   - иначе → ничего (управление — через модалку редактирования).
     */
    _renderInitialStateBadge(campaignId, info) {
        if (!info || !info.hasActiveState) return '';
        return `<div class="card-initial-state" data-id="${this.escapeHtml(String(campaignId))}">
            <span class="badge badge-success">Initial State применён</span>
        </div>`;
    },

    _attachCampaignsTabListeners(container) {
        if (window.DomainRail) {
            window.DomainRail.attach(container, (domainId) => {
                this._activeDomainId = domainId || null;
                this.loadTab('campaigns');
            });
        }
    },

    async showCampaignModal(campaignId = null) {
        const isEdit = !!campaignId;
        let campaign = { name: '', description: '', system_prompt: '' };
        let campaignTags = [];
        let globalTags = [];
        const selectedDomainId = this._activeDomainId || null;

        if (isEdit) {
            try {
                campaign = await this.api.getCampaign(campaignId);
                campaignTags = campaign.tags || [];
            } catch (e) { alert('Ошибка загрузки кампании: ' + e.message); return; }
        }

        const effectiveDomainId = isEdit
            ? (campaign.domain_id || selectedDomainId || null)
            : selectedDomainId;

        if (effectiveDomainId) {
            try {
                const tagsResp = await this.api.getTags(effectiveDomainId);
                const grouped = Array.isArray(tagsResp) ? { global_tags: tagsResp, by_campaign: {} } : (tagsResp || {});
                globalTags = Array.isArray(grouped.global_tags) ? grouped.global_tags : [];
            } catch (e) { /* ignore */ }
        }
        let linkedGlobalTagIds = new Set();
        if (isEdit && campaignId) {
            try {
                const linked = await this.api.getCampaignGlobalTags(campaignId);
                linkedGlobalTagIds = new Set((linked || []).map(t => String(t.id)));
            } catch (e) { /* ignore */ }
        }

        let domains = [];
        if (!isEdit) {
            try {
                const dr = await this.api.getSettingsDomains();
                domains = Array.isArray(dr) ? dr : (dr.domains || []);
            } catch (_) {}
        }

        const domainSelectHtml = !isEdit ? `
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Домен <span style="color:var(--color-error);">*</span></label>
                <select id="camp-domain-id" class="input-field">
                    <option value="">— выберите домен —</option>
                    ${domains.map(d => {
                        const did = this.escapeHtml(d.domain_id || d.id || '');
                        const dname = this.escapeHtml(d.display_name || d.domain_id || d.id || '');
                        const sel = (d.domain_id || d.id) === selectedDomainId ? ' selected' : '';
                        return `<option value="${did}"${sel}>${dname}</option>`;
                    }).join('')}
                </select>
            </div>` : '';

        const overlay = document.createElement('div');
        overlay.className = 'modal';
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:1000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.55);';
        overlay.innerHTML = `<div class="modal-content" style="max-width:560px;width:100%;max-height:90vh;overflow-y:auto;">
            <div class="modal-header">
                <h3>${isEdit ? 'Редактировать' : 'Создать'} кампанию</h3>
                <button class="btn-close" id="camp-modal-close">✕</button>
            </div>
            ${domainSelectHtml}
            <div class="form-group" style="padding:0 1.5rem;margin-top:1rem;">
                <label>Название</label>
                <input type="text" id="camp-name" class="input-field" value="${this.escapeHtml(campaign.name)}">
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Описание</label>
                <textarea id="camp-desc" class="input-field" rows="2">${this.escapeHtml(campaign.description || '')}</textarea>
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>System Prompt</label>
                <textarea id="camp-prompt" class="input-field" rows="5" placeholder="Инструкция для AI в этой кампании">${this.escapeHtml(campaign.system_prompt || '')}</textarea>
            </div>
            ${isEdit ? `
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Теги кампании</label>
                <div id="camp-tags-list" class="badge-group"></div>
                <details>
                    <summary style="cursor:pointer;font-size:var(--text-sm);color:var(--color-primary);margin-top:4px;">+ Создать тег</summary>
                    <div style="display:flex;gap:8px;margin-top:8px;align-items:center;">
                        <input type="text" id="new-tag-name" class="input-field" placeholder="Название" style="flex:1;">
                        <input type="color" id="new-tag-color" value="#4f98a3" style="width:36px;height:32px;border:none;cursor:pointer;border-radius:var(--radius-sm);">
                        <button class="btn btn-secondary" style="padding:4px 12px;" id="create-ctag-btn">Создать</button>
                    </div>
                </details>
            </div>
            <div class="form-group" style="padding:0 1.5rem;">
                <label>Глобальные теги домена</label>
                <div id="camp-global-tags-list" class="badge-group"></div>
                ${globalTags.length ? `
                <select id="camp-global-tag-select" class="input-field" style="margin-top:8px;">
                    <option value="">+ Добавить глобальный тег...</option>
                    ${globalTags.filter(t => !linkedGlobalTagIds.has(String(t.id))).map(t =>
                        `<option value="${this.escapeHtml(String(t.id))}">${this.escapeHtml(t.name)}</option>`
                    ).join('')}
                </select>` : '<span style="color:var(--color-text-faint);font-size:var(--text-sm);">В домене нет глобальных тегов</span>'}
            </div>
            <div id="camp-state-fields-mount" style="padding:0 1.5rem;"></div>
            <div id="camp-initial-state-mount" style="padding:0 1.5rem;"></div>` : ''}
            <div class="modal-actions" style="display:flex;justify-content:space-between;gap:8px;margin-top:1rem;padding:1rem 1.5rem;border-top:1px solid var(--color-border);">
                <button class="btn btn-primary" id="camp-save-btn">${isEdit ? 'Сохранить' : 'Создать'}</button>
                ${isEdit ? `<button class="btn" style="color:var(--color-error);" id="camp-delete-btn">Удалить кампанию</button>` : ''}
            </div>
        </div>`;
        document.body.appendChild(overlay);

        // Секции «Поля Campaign State» и «Initial State» внутри модалки редактирования.
        // Создаются через фабрики модулей state-fields.js / initial-state.js —
        // те же модули переиспользуются без overlay-обёрток.
        let stateFieldsSection = null;
        let initialStateSection = null;
        if (isEdit && window.StateFieldsSection && window.InitialStateSection) {
            const fieldsMount = overlay.querySelector('#camp-state-fields-mount');
            const initialMount = overlay.querySelector('#camp-initial-state-mount');
            if (fieldsMount) {
                stateFieldsSection = window.StateFieldsSection.build();
                // Снимаем padding form-group — он уже есть у mount-point.
                stateFieldsSection.element.style.padding = '0';
                fieldsMount.appendChild(stateFieldsSection.element);
                stateFieldsSection.load(campaignId, {
                    onChange: () => {
                        // При изменении полей обновляем Initial State секцию и карточку.
                        if (initialStateSection) initialStateSection.refresh(campaignId);
                    },
                });
            }
            if (initialMount) {
                initialStateSection = window.InitialStateSection.build();
                initialStateSection.element.style.padding = '0';
                initialMount.appendChild(initialStateSection.element);
                const wizardDomainId = effectiveDomainId || campaign.domain_id || null;
                initialStateSection.load(campaignId, {
                    onChanged: () => this.loadTab('campaigns'),
                    onApplyClick: (cid) => {
                        if (window.InitialStateWizard) {
                            window.InitialStateWizard.open(cid, {
                                domainId: wizardDomainId,
                                onApplied: () => initialStateSection.refresh(cid),
                            });
                        }
                    },
                });
            }
        }
        window._campEditHelpers = { stateFieldsSection: () => stateFieldsSection, initialStateSection: () => initialStateSection };

        let localCampTags = [...campaignTags];

        const refreshTagsList = () => {
            const list = overlay.querySelector('#camp-tags-list');
            if (!list) return;
            if (!localCampTags.length) {
                list.innerHTML = '<span style="color:var(--color-text-faint)">нет тегов</span>';
                return;
            }
            list.innerHTML = localCampTags.map(t =>
                tagBadgeHtml(t, {
                    context: 'campaign-own',
                    removable: true,
                    dataAttrs: { 'data-remove-ctag': String(t.id) },
                })
            ).join('');
            list.querySelectorAll('[data-remove-ctag]').forEach(el => {
                el.onclick = async () => {
                    const tid = el.dataset.removeCtag;
                    if (!confirm('Удалить тег?')) return;
                    try {
                        await this.api.deleteTag(tid);
                        localCampTags = localCampTags.filter(t => String(t.id) !== tid);
                        refreshTagsList();
                        if (initialStateSection) initialStateSection.refresh(campaignId);
                    }
                    catch (e) { alert(e.message); }
                };
            });
        };
        refreshTagsList();

        let localLinkedGlobalTagIds = new Set(linkedGlobalTagIds);

        const refreshGlobalTagsList = () => {
            const list = overlay.querySelector('#camp-global-tags-list');
            if (!list) return;
            const linked = globalTags.filter(t => localLinkedGlobalTagIds.has(String(t.id)));
            if (!linked.length) {
                list.innerHTML = '<span style="color:var(--color-text-faint);font-size:var(--text-sm);">нет подключённых тегов</span>';
                return;
            }
            list.innerHTML = linked.map(t =>
                tagBadgeHtml(t, {
                    context: 'campaign-global',
                    removable: true,
                    dataAttrs: { 'data-unlink-gtag': String(t.id) },
                })
            ).join('');
            list.querySelectorAll('[data-unlink-gtag]').forEach(el => {
                el.onclick = async () => {
                    const tid = el.dataset.unlinkGtag;
                    try {
                        await this.api.unlinkCampaignGlobalTag(campaignId, tid);
                        localLinkedGlobalTagIds.delete(tid);
                        const sel = overlay.querySelector('#camp-global-tag-select');
                        if (sel) {
                            const tag = globalTags.find(t => String(t.id) === tid);
                            if (tag) {
                                const opt = document.createElement('option');
                                opt.value = tid;
                                opt.textContent = tag.name;
                                sel.appendChild(opt);
                            }
                        }
                        refreshGlobalTagsList();
                        if (initialStateSection) initialStateSection.refresh(campaignId);
                    } catch (e) { alert(e.message); }
                };
            });
        };
        refreshGlobalTagsList();

        overlay.querySelector('#camp-global-tag-select')?.addEventListener('change', async (e) => {
            const tid = e.target.value;
            if (!tid) return;
            try {
                await this.api.linkCampaignGlobalTag(campaignId, tid);
                localLinkedGlobalTagIds.add(tid);
                e.target.querySelector(`option[value="${tid}"]`)?.remove();
                e.target.value = '';
                refreshGlobalTagsList();
                if (initialStateSection) initialStateSection.refresh(campaignId);
            } catch (err) { alert(err.message); }
        });

        overlay.querySelector('#camp-modal-close').onclick = () => overlay.remove();

        if (isEdit) {
            overlay.querySelector('#create-ctag-btn')?.addEventListener('click', async () => {
                const name = overlay.querySelector('#new-tag-name').value.trim();
                const color = overlay.querySelector('#new-tag-color').value;
                if (!name) return;
                try {
                    const tag = await this.api.createCampaignTag(campaignId, { name, color });
                    localCampTags.push(tag);
                    overlay.querySelector('#new-tag-name').value = '';
                    refreshTagsList();
                    if (initialStateSection) initialStateSection.refresh(campaignId);
                } catch (e) { alert(e.message); }
            });

            overlay.querySelector('#camp-delete-btn')?.addEventListener('click', async () => {
                if (!confirm('Удалить кампанию и все её теги?')) return;
                try {
                    await this.api.deleteCampaign(campaignId);
                    overlay.remove();
                    this.loadTab('campaigns');
                } catch (e) { alert(e.message); }
            });
        }

        overlay.querySelector('#camp-save-btn').addEventListener('click', async () => {
            const data = {
                name: overlay.querySelector('#camp-name').value.trim(),
                description: overlay.querySelector('#camp-desc').value.trim(),
                system_prompt: overlay.querySelector('#camp-prompt').value.trim(),
            };
            if (!data.name) { alert('Введите название'); return; }
            try {
                if (isEdit) {
                    await this.api.updateCampaign(campaignId, data);
                } else {
                    const chosenDomain = overlay.querySelector('#camp-domain-id')?.value || selectedDomainId;
                    if (!chosenDomain) {
                        alert('Выберите домен для кампании');
                        return;
                    }
                    data.domain_id = chosenDomain;
                    await this.api.createCampaign(data);
                }
                overlay.remove();
                this.loadTab('campaigns');
            } catch (e) { alert('Ошибка: ' + e.message); }
        });
    },

    async handleCampaignsAction(action, id) {
        if (action === 'new-campaign') { await this.showCampaignModal(); return; }
        if (action === 'edit-campaign') { await this.showCampaignModal(id); return; }
        if (action === 'delete-campaign') {
            if (!confirm('Удалить кампанию?')) return;
            try { await this.api.deleteCampaign(id); this.loadTab('campaigns'); }
            catch (e) { alert(e.message); }
        }
    },
};

Object.assign(SettingsManager.prototype, CampaignsTabMixin);
