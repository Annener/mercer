// State Fields UI — Stage 1
// Рендер секции «Поля State» внутри модалки редактирования кампании.
// Возвращает { render(campaignId, fields) → HTMLElement, apply(HTMLElement) → обновить state }.
//
// Использование из tab-campaigns.js:
//   const section = StateFieldsSection.build();
//   mountEl.appendChild(section.element);
//   await section.load(campaignId);
//   section.refreshAfterChange();

const StateFieldsImpl = (function () {
    'use strict';

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    const FIELD_KEY_RE = /^[a-z][a-z0-9_]{0,63}$/;

    // ---------------------------------------------------------------
    // Public API: build() → section controller
    // ---------------------------------------------------------------

    function build() {
        const root = document.createElement('div');
        root.className = 'form-group';
        root.innerHTML = `
            <label>Поля Campaign State</label>
            <div class="field-desc">Опишите поля, которые LLM будет заполнять в Initial State (single или list). После применения Initial State менять key/mode нельзя.</div>
            <div class="state-fields-section-list"></div>
            <div class="state-fields-section-form" style="margin-top:12px;"></div>
            <div class="state-fields-section-error" style="display:none;margin-top:8px;"></div>
            <div class="state-fields-section-actions" style="margin-top:8px;display:flex;gap:8px;">
                <button type="button" class="btn btn-secondary" data-action="add">+ Добавить поле</button>
            </div>
        `;

        const state = {
            campaignId: null,
            api: window.chatAPI,
            fields: [],
            editing: null,  // null | {id?, key, label, description, mode, enabled}
            saving: false,
            onChange: null,
        };

        const els = {
            list: root.querySelector('.state-fields-section-list'),
            form: root.querySelector('.state-fields-section-form'),
            error: root.querySelector('.state-fields-section-error'),
            actions: root.querySelector('.state-fields-section-actions'),
            addBtn: root.querySelector('[data-action="add"]'),
        };

        // ---------- helpers ----------

        function showError(msg) {
            els.error.textContent = msg;
            els.error.style.display = msg ? 'block' : 'none';
        }

        function renderList() {
            if (!state.fields.length) {
                els.list.innerHTML = '<span style="color:var(--color-text-faint);font-size:var(--text-sm);">Полей нет.</span>';
                return;
            }
            const items = state.fields.map((f, i) => `
                <div class="state-field-row" data-id="${escapeHtml(f.id)}" style="display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid var(--color-border);border-radius:6px;margin-bottom:4px;">
                    <div style="flex:1;min-width:0;">
                        <div style="display:flex;align-items:center;gap:6px;">
                            <code style="background:#f5f5f5;padding:1px 6px;border-radius:3px;font-size:12px;">${escapeHtml(f.key)}</code>
                            <span style="font-weight:500;">${escapeHtml(f.label)}</span>
                            <span class="badge" style="background:#ecf0f1;color:#2c3e50;font-size:11px;">${escapeHtml(f.mode)}</span>
                            ${f.enabled ? '' : '<span class="badge" style="background:#bdc3c7;color:#fff;font-size:11px;">off</span>'}
                        </div>
                        ${f.description ? `<div style="color:#6b7d8f;font-size:12px;margin-top:2px;">${escapeHtml(f.description)}</div>` : ''}
                    </div>
                    <button type="button" class="btn btn-sm" data-row-action="up" data-id="${escapeHtml(f.id)}" ${i === 0 ? 'disabled' : ''} title="Вверх">↑</button>
                    <button type="button" class="btn btn-sm" data-row-action="down" data-id="${escapeHtml(f.id)}" ${i === state.fields.length - 1 ? 'disabled' : ''} title="Вниз">↓</button>
                    <button type="button" class="btn btn-sm" data-row-action="edit" data-id="${escapeHtml(f.id)}">Изменить</button>
                    <button type="button" class="btn btn-sm btn-danger" data-row-action="delete" data-id="${escapeHtml(f.id)}">Удалить</button>
                </div>
            `).join('');
            els.list.innerHTML = items;

            els.list.querySelectorAll('[data-row-action]').forEach((btn) => {
                const action = btn.dataset.rowAction;
                const fid = btn.dataset.id;
                btn.addEventListener('click', () => {
                    if (action === 'up') return onReorder(fid, 'up');
                    if (action === 'down') return onReorder(fid, 'down');
                    if (action === 'edit') return onEdit(fid);
                    if (action === 'delete') return onDelete(fid);
                });
            });
        }

        function renderForm() {
            if (!state.editing) {
                els.form.innerHTML = '';
                return;
            }
            const isNew = !state.editing.id;
            els.form.innerHTML = `
                <div style="border:1px solid var(--color-border);border-radius:6px;padding:12px;background:#fafbfc;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <strong>${isNew ? 'Новое поле' : 'Изменить поле'}</strong>
                        <button type="button" class="btn-close" data-action="cancel">✕</button>
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label>Ключ (technical id) ${isNew ? '' : '<span class="badge" style="background:#bdc3c7;color:#fff;font-size:10px;">immutable</span>'}</label>
                        <input type="text" class="input-field" data-field="key" value="${escapeHtml(state.editing.key)}" ${isNew ? '' : 'disabled'} placeholder="current_focus">
                        <div class="field-desc">латиница, нижний регистр, без пробелов. После создания нельзя изменить.</div>
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label>Название</label>
                        <input type="text" class="input-field" data-field="label" value="${escapeHtml(state.editing.label)}" placeholder="Текущая локация">
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label>Описание</label>
                        <textarea class="input-field" data-field="description" rows="2" placeholder="Передаётся LLM при формировании state. Опишите, какую информацию включать.">${escapeHtml(state.editing.description || '')}</textarea>
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label>Тип поля ${isNew ? '' : '<span class="badge" style="background:#bdc3c7;color:#fff;font-size:10px;">immutable</span>'}</label>
                        <label style="display:flex;align-items:center;gap:6px;font-weight:400;margin-bottom:4px;">
                            <input type="radio" name="state-field-mode" data-field="mode" value="single" ${state.editing.mode === 'single' ? 'checked' : ''} ${isNew ? '' : 'disabled'}>
                            single — одно актуальное значение
                        </label>
                        <label style="display:flex;align-items:center;gap:6px;font-weight:400;">
                            <input type="radio" name="state-field-mode" data-field="mode" value="list" ${state.editing.mode === 'list' ? 'checked' : ''} ${isNew ? '' : 'disabled'}>
                            list — список независимых пунктов
                        </label>
                    </div>
                    <div class="form-group" style="margin-bottom:8px;">
                        <label style="display:flex;align-items:center;gap:6px;font-weight:400;">
                            <input type="checkbox" data-field="enabled" ${state.editing.enabled ? 'checked' : ''}>
                            Включено
                        </label>
                    </div>
                    <div style="display:flex;gap:8px;justify-content:flex-end;">
                        <button type="button" class="btn" data-action="cancel">Отмена</button>
                        <button type="button" class="btn btn-primary" data-action="save" ${state.saving ? 'disabled' : ''}>${state.saving ? 'Сохранение…' : 'Сохранить'}</button>
                    </div>
                </div>
            `;

            // Wire up form events.
            const keyInput = els.form.querySelector('[data-field="key"]');
            const labelInput = els.form.querySelector('[data-field="label"]');
            const descInput = els.form.querySelector('[data-field="description"]');
            const enabledInput = els.form.querySelector('[data-field="enabled"]');
            const modeInputs = els.form.querySelectorAll('[data-field="mode"]');
            keyInput?.addEventListener('input', (e) => { state.editing.key = e.target.value; });
            labelInput?.addEventListener('input', (e) => { state.editing.label = e.target.value; });
            descInput?.addEventListener('input', (e) => { state.editing.description = e.target.value; });
            enabledInput?.addEventListener('change', (e) => { state.editing.enabled = e.target.checked; });
            modeInputs.forEach((r) => r.addEventListener('change', (e) => {
                if (e.target.checked) state.editing.mode = e.target.value;
            }));

            els.form.querySelectorAll('[data-action="cancel"]').forEach((b) =>
                b.addEventListener('click', () => { state.editing = null; renderForm(); })
            );
            els.form.querySelector('[data-action="save"]').addEventListener('click', onSave);
        }

        // ---------- actions ----------

        els.addBtn.addEventListener('click', () => {
            state.editing = {
                id: null, key: '', label: '', description: '',
                mode: 'single', enabled: true,
            };
            renderForm();
            // focus first input
            setTimeout(() => {
                els.form.querySelector('[data-field="key"]')?.focus();
            }, 0);
        });

        function onEdit(fid) {
            const f = state.fields.find((x) => String(x.id) === String(fid));
            if (!f) return;
            state.editing = {
                id: f.id, key: f.key, label: f.label, description: f.description || '',
                mode: f.mode, enabled: !!f.enabled,
            };
            renderForm();
        }

        async function onDelete(fid) {
            const f = state.fields.find((x) => String(x.id) === String(fid));
            if (!f) return;
            if (!confirm(`Удалить поле «${f.label}» (${f.key})? Будут удалены соответствующие значения в активном состоянии кампании. Действие необратимо.`)) return;
            try {
                await state.api.deleteStateField(state.campaignId, fid);
                state.fields = state.fields.filter((x) => String(x.id) !== String(fid));
                renderList();
                if (typeof state.onChange === 'function') state.onChange();
            } catch (err) {
                const msg = err && err.status === 409
                    ? 'Нельзя удалить: на поле ссылаются значения state.'
                    : mapError(err);
                showError(msg);
            }
        }

        async function onReorder(fid, direction) {
            const idx = state.fields.findIndex((x) => String(x.id) === String(fid));
            if (idx < 0) return;
            const target = direction === 'up' ? idx - 1 : idx + 1;
            if (target < 0 || target >= state.fields.length) return;
            const ids = state.fields.map((x) => String(x.id));
            [ids[idx], ids[target]] = [ids[target], ids[idx]];
            try {
                state.fields = await state.api.reorderStateFields(state.campaignId, ids);
                renderList();
                if (typeof state.onChange === 'function') state.onChange();
            } catch (err) {
                showError(mapError(err));
            }
        }

        async function onSave() {
            const e = state.editing;
            if (!e) return;
            // Validate.
            if (!e.id && (!e.key || !FIELD_KEY_RE.test(e.key))) {
                showError('Ключ: латиница, нижний регистр, начинается с буквы. Только буквы/цифры/_');
                return;
            }
            if (!e.label || !e.label.trim()) {
                showError('Название обязательно');
                return;
            }
            if (!e.mode || (e.mode !== 'single' && e.mode !== 'list')) {
                showError('Выберите тип поля');
                return;
            }
            state.saving = true;
            renderForm();
            try {
                if (e.id) {
                    const updated = await state.api.updateStateField(state.campaignId, e.id, {
                        label: e.label.trim(),
                        description: (e.description || '').trim(),
                        enabled: e.enabled,
                    });
                    const idx = state.fields.findIndex((x) => String(x.id) === String(updated.id));
                    if (idx >= 0) state.fields[idx] = updated;
                } else {
                    const created = await state.api.createStateField(state.campaignId, {
                        key: e.key,
                        label: e.label.trim(),
                        description: (e.description || '').trim(),
                        mode: e.mode,
                        enabled: e.enabled,
                    });
                    state.fields.push(created);
                }
                state.fields.sort(
                    (a, b) => a.display_order - b.display_order || a.key.localeCompare(b.key)
                );
                state.editing = null;
                showError('');
                renderList();
                renderForm();
                if (typeof state.onChange === 'function') state.onChange();
            } catch (err) {
                showError(mapError(err));
            } finally {
                state.saving = false;
                if (state.editing) renderForm();
            }
        }

        function mapError(err) {
            if (!err) return 'Не удалось выполнить операцию';
            if (typeof err.status === 'number') {
                if (typeof err.detail === 'string') return err.detail;
                if (err.detail && typeof err.detail === 'object' && err.detail.code) {
                    return err.detail.code;
                }
            }
            return err.message || 'Не удалось выполнить операцию';
        }

        // ---------- public ----------

        return {
            element: root,
            async load(campaignId, opts = {}) {
                state.campaignId = campaignId;
                state.onChange = opts.onChange || null;
                try {
                    state.fields = await state.api.getStateFields(campaignId);
                } catch (err) {
                    state.fields = [];
                    showError(mapError(err));
                }
                renderList();
                renderForm();
            },
            refresh(campaignId) {
                if (campaignId) state.campaignId = campaignId;
                return state.api.getStateFields(state.campaignId)
                    .then((fields) => { state.fields = fields; renderList(); })
                    .catch((err) => { showError(mapError(err)); });
            },
            getFields() { return [...state.fields]; },
        };
    }

    return { build };
})();

window.StateFieldsSection = StateFieldsImpl;
export { StateFieldsImpl as StateFieldsSection };

