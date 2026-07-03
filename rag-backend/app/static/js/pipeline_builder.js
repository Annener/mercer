
const PipelineBuilder = (() => {
  /* ── helpers ── */
  const _esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

  /* ── step type registry ── */
  const STEP_TYPES = {
    retrieval: {
      label: 'Retrieval',
      icon: '🔍',
      fields: [
        { key: 'vault_id',       label: 'Vault ID',          type: 'text',   placeholder: 'my-vault' },
        { key: 'top_k',          label: 'Top K',             type: 'number', placeholder: '5' },
        { key: 'score_threshold',label: 'Score threshold',   type: 'number', placeholder: '0.0' },
        { key: 'query_key',      label: 'Query key',         type: 'text',   placeholder: 'query' },
        { key: 'output_key',     label: 'Output key',        type: 'text',   placeholder: 'chunks' },
      ],
    },
    rerank: {
      label: 'Rerank',
      icon: '📊',
      fields: [
        { key: 'model_id',    label: 'Model ID',    type: 'text',   placeholder: 'rerank-model' },
        { key: 'top_n',       label: 'Top N',       type: 'number', placeholder: '3' },
        { key: 'chunks_key',  label: 'Chunks key',  type: 'text',   placeholder: 'chunks' },
        { key: 'query_key',   label: 'Query key',   type: 'text',   placeholder: 'query' },
        { key: 'output_key',  label: 'Output key',  type: 'text',   placeholder: 'chunks' },
      ],
    },
    generate: {
      label: 'Generate',
      icon: '✨',
      fields: [
        { key: 'model_id',      label: 'Model ID',      type: 'text', placeholder: 'gpt-4o' },
        { key: 'system_prompt', label: 'System prompt', type: 'textarea', placeholder: 'You are a helpful assistant.' },
        { key: 'chunks_key',    label: 'Chunks key',    type: 'text', placeholder: 'chunks' },
        { key: 'query_key',     label: 'Query key',     type: 'text', placeholder: 'query' },
        { key: 'output_key',    label: 'Output key',    type: 'text', placeholder: 'answer' },
      ],
    },
    web_search: {
      label: 'Web Search',
      icon: '🌐',
      fields: [
        { key: 'query_key',  label: 'Query key',  type: 'text',   placeholder: 'query' },
        { key: 'top_k',      label: 'Top K',      type: 'number', placeholder: '5' },
        { key: 'output_key', label: 'Output key', type: 'text',   placeholder: 'web_results' },
      ],
    },
    custom: {
      label: 'Custom',
      icon: '⚙️',
      fields: [
        { key: 'handler',    label: 'Handler',    type: 'text', placeholder: 'my_module.my_func' },
        { key: 'output_key', label: 'Output key', type: 'text', placeholder: 'result' },
      ],
    },
  };

  /* ── state ── */
  let _api = null;
  let _pipeline = null;   // null = create mode, object = edit mode
  let _steps = [];
  let _onSave = null;
  let _overlay = null;

  /* ── render ── */
  function _renderStepFields(step, idx) {
    const def = STEP_TYPES[step.type] || STEP_TYPES.custom;
    return def.fields.map(f => {
      const val = _esc(step[f.key] ?? '');
      const id  = `pb-step-${idx}-${f.key}`;
      if (f.type === 'textarea') {
        return `<div class="pb-field">
          <label for="${id}">${_esc(f.label)}</label>
          <textarea id="${id}" class="input pb-textarea" data-step="${idx}" data-key="${f.key}" placeholder="${_esc(f.placeholder || '')}">${val}</textarea>
        </div>`;
      }
      return `<div class="pb-field">
        <label for="${id}">${_esc(f.label)}</label>
        <input id="${id}" type="${f.type === 'number' ? 'number' : 'text'}" class="input" data-step="${idx}" data-key="${f.key}" value="${val}" placeholder="${_esc(f.placeholder || '')}">
      </div>`;
    }).join('');
  }

  function _renderStep(step, idx) {
    const def = STEP_TYPES[step.type] || STEP_TYPES.custom;
    return `
    <details class="pb-step" data-idx="${idx}" open>
      <summary class="pb-step-header">
        <span class="pb-step-icon">${def.icon}</span>
        <span class="pb-step-label">${_esc(def.label)}</span>
        <span class="pb-step-num">#${idx + 1}</span>
        <div class="pb-step-actions">
          ${idx > 0 ? `<button class="pb-btn-icon" data-action="move-up" data-idx="${idx}" title="Вверх">↑</button>` : ''}
          ${idx < _steps.length - 1 ? `<button class="pb-btn-icon" data-action="move-down" data-idx="${idx}" title="Вниз">↓</button>` : ''}
          <button class="pb-btn-icon pb-btn-danger" data-action="remove-step" data-idx="${idx}" title="Удалить">✕</button>
        </div>
      </summary>
      <div class="pb-step-body">
        ${_renderStepFields(step, idx)}
      </div>
    </details>`;
  }

  function _renderModal() {
    const typeOptions = Object.entries(STEP_TYPES)
      .map(([k, v]) => `<option value="${k}">${v.icon} ${_esc(v.label)}</option>`)
      .join('');

    const stepsHtml = _steps.length
      ? _steps.map((s, i) => _renderStep(s, i)).join('')
      : `<div class="pb-empty">Шаги не добавлены</div>`;

    return `
    <div class="pb-modal-inner">
      <div class="pb-header">
        <div class="pb-title-row">
          <span class="pb-title">${_pipeline ? '✏️ ' + _esc(_pipeline.name) : 'Новый пайплайн'}</span>
          <button class="pb-btn-close" data-action="close">✕</button>
        </div>
        <div class="pb-name-row">
          <label for="pb-name">Название</label>
          <input id="pb-name"   class="input pb-input-inline" placeholder="Название пайплайна"
                 value="${_esc(_pipeline?.name || '')}">
        </div>
        <div class="pb-name-row">
          <label for="pb-pid">Pipeline ID</label>
          <input id="pb-pid" class="input pb-input-inline" placeholder="my-pipeline"
                 value="${_esc(_pipeline?.pipeline_id || '')}">
        </div>
      </div>

      <div class="pb-add-row">
        <select id="pb-step-type" class="input pb-select">${typeOptions}</select>
        <button class="pb-btn pb-btn-add" data-action="add-step">+ Добавить шаг</button>
      </div>

      <div class="pb-steps" id="pb-steps-list">
        ${stepsHtml}
      </div>

      <div class="pb-footer">
        <button class="pb-btn pb-btn-primary" data-action="save">
          ${_pipeline ? 'Сохранить' : 'Создать'}
        </button>
        ${_pipeline ? `<button class="pb-btn pb-btn-danger" data-action="delete">Удалить</button>` : ''}
        <button class="pb-btn" data-action="close">Отмена</button>
      </div>
    </div>`;
  }

  /* ── sync steps from DOM ── */
  function _syncStepsFromDOM() {
    if (!_overlay) return;
    _overlay.querySelectorAll('[data-step]').forEach(el => {
      const idx = parseInt(el.dataset.step, 10);
      const key = el.dataset.key;
      if (!_steps[idx]) return;
      const raw = el.value ?? '';
      const def = STEP_TYPES[_steps[idx].type];
      const fieldDef = def?.fields.find(f => f.key === key);
      _steps[idx][key] = (fieldDef?.type === 'number' && raw !== '') ? Number(raw) : raw;
    });
  }

  /* ── re-render steps list only ── */
  function _refreshStepsList() {
    if (!_overlay) return;
    const container = _overlay.querySelector('#pb-steps-list');
    if (!container) return;
    container.innerHTML = _steps.length
      ? _steps.map((s, i) => _renderStep(s, i)).join('')
      : `<div class="pb-empty">Шаги не добавлены</div>`;
    _attachStepListeners(container);
  }

  /* ── event delegation inside steps list ── */
  function _attachStepListeners(container) {
    container.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      const idx    = parseInt(btn.dataset.idx, 10);

      if (action === 'remove-step') {
        _syncStepsFromDOM();
        _steps.splice(idx, 1);
        _refreshStepsList();
      } else if (action === 'move-up' && idx > 0) {
        _syncStepsFromDOM();
        [_steps[idx - 1], _steps[idx]] = [_steps[idx], _steps[idx - 1]];
        _refreshStepsList();
      } else if (action === 'move-down' && idx < _steps.length - 1) {
        _syncStepsFromDOM();
        [_steps[idx], _steps[idx + 1]] = [_steps[idx + 1], _steps[idx]];
        _refreshStepsList();
      }
    });
  }

  /* ── open ── */
  function _open(api, pipeline, onSave) {
    _api      = api;
    _pipeline = pipeline;
    _steps    = pipeline ? JSON.parse(JSON.stringify(pipeline.steps || [])) : [];
    _onSave   = onSave;

    _overlay = document.createElement('div');
    _overlay.className = 'pb-overlay';
    _overlay.innerHTML = _renderModal();
    document.body.appendChild(_overlay);
    _injectStyles();
    _attachListeners();
  }

  /* ── listeners ── */
  function _attachListeners() {
    if (!_overlay) return;

    /* close on backdrop */
    _overlay.addEventListener('click', e => {
      if (e.target === _overlay) _close();
    });

    /* delegated actions */
    _overlay.addEventListener('click', async e => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;

      if (action === 'close') {
        _close();

      } else if (action === 'add-step') {
        _syncStepsFromDOM();
        const type = _overlay.querySelector('#pb-step-type')?.value || 'retrieval';
        _steps.push({ type });
        _refreshStepsList();

      } else if (action === 'save') {
        await _save();

      } else if (action === 'delete') {
        await _delete();
      }
    });

    /* step list listeners */
    const stepsList = _overlay.querySelector('#pb-steps-list');
    if (stepsList) _attachStepListeners(stepsList);
  }

  /* ── save ── */
  async function _save() {
    _syncStepsFromDOM();
    const name       = _overlay.querySelector('#pb-name')?.value.trim() || '';
    const pipelineId = _overlay.querySelector('#pb-pid')?.value.trim()  || '';

    if (!name) { alert('Введите название пайплайна'); return; }

    const payload = { name, steps: _steps };
    if (pipelineId) payload.pipeline_id = pipelineId;

    try {
      if (_pipeline) {
        await _api.updatePipeline(_pipeline.id, payload);
      } else {
        await _api.createPipeline(payload);
      }
      _close();
      if (typeof _onSave === 'function') _onSave();
    } catch (e) {
      alert('Ошибка сохранения: ' + e.message);
    }
  }

  /* ── delete ── */
  async function _delete() {
    if (!_pipeline) return;
    if (!confirm(`Удалить пайплайн "${_pipeline.name}"?`)) return;
    try {
      await _api.deletePipeline(_pipeline.id);
      _close();
      if (typeof _onSave === 'function') _onSave();
    } catch (e) {
      alert('Ошибка удаления: ' + e.message);
    }
  }

  /* ── close ── */
  function _close() {
    if (_overlay) { _overlay.remove(); _overlay = null; }
  }

  /* ── styles (injected once) ── */
  let _stylesInjected = false;
  function _injectStyles() {
    if (_stylesInjected) return;
    _stylesInjected = true;
    const style = document.createElement('style');
    style.textContent = `
.pb-overlay {
  position: fixed; inset: 0; z-index: 2000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.6);
}
.pb-modal-inner {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  width: min(700px, 96vw);
  max-height: 90vh;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.pb-header {
  padding: var(--space-6) var(--space-6) var(--space-4);
  border-bottom: 1px solid var(--color-divider);
}
.pb-title-row {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: var(--space-3);
}
.pb-title {
  font-size: var(--text-lg); font-weight: 600;
  color: var(--color-text);
}
.pb-btn-close {
  background: none; border: none; cursor: pointer;
  color: var(--color-text-muted); font-size: var(--text-base);
  padding: var(--space-1);
  transition: color var(--transition-interactive);
}
.pb-btn-close:hover { color: var(--color-text); }
.pb-name-row {
  display: flex; align-items: center; gap: var(--space-3);
  margin-top: var(--space-2);
}
.pb-name-row label {
  font-size: var(--text-sm); color: var(--color-text-muted);
  white-space: nowrap; min-width: 90px;
}
.pb-input-inline {
  flex: 1; padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
}
.pb-add-row {
  display: flex; gap: var(--space-3); padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--color-divider);
}
.pb-select { flex: 1; font-size: var(--text-sm); }
.pb-steps {
  flex: 1; overflow-y: auto;
  padding: var(--space-4) var(--space-6);
  display: flex; flex-direction: column; gap: var(--space-3);
}
.pb-empty {
  text-align: center; color: var(--color-text-faint);
  font-size: var(--text-sm); padding: var(--space-8);
}
.pb-step {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface-2);
  overflow: hidden;
}
.pb-step-header {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  cursor: pointer; list-style: none;
  font-size: var(--text-sm); font-weight: 500;
  color: var(--color-text);
  background: var(--color-surface-offset);
}
.pb-step-header::-webkit-details-marker { display: none; }
.pb-step-icon { font-size: 1rem; }
.pb-step-label { flex: 1; }
.pb-step-num {
  font-size: var(--text-xs); color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}
.pb-step-actions {
  display: flex; gap: var(--space-1); margin-left: var(--space-2);
}
.pb-btn-icon {
  background: none; border: none; cursor: pointer;
  color: var(--color-text-muted); padding: 2px 6px;
  border-radius: var(--radius-sm); font-size: var(--text-sm);
  transition: color var(--transition-interactive), background var(--transition-interactive);
}
.pb-btn-icon:hover { color: var(--color-text); background: var(--color-surface-dynamic); }
.pb-btn-icon.pb-btn-danger:hover { color: var(--color-error); }
.pb-step-body {
  padding: var(--space-4);
  display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3);
}
.pb-field { display: flex; flex-direction: column; gap: var(--space-1); }
.pb-field label { font-size: var(--text-xs); color: var(--color-text-muted); }
.pb-field .pb-textarea { resize: vertical; min-height: 60px; font-family: var(--font-body, monospace); }
.pb-footer {
  display: flex; gap: var(--space-3); padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--color-divider);
}
.pb-btn {
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-md);
  font-size: var(--text-sm); font-weight: 500;
  cursor: pointer; border: 1px solid var(--color-border);
  background: var(--color-surface-offset);
  color: var(--color-text);
  transition: background var(--transition-interactive), border-color var(--transition-interactive);
}
.pb-btn:hover { background: var(--color-surface-dynamic); }
.pb-btn-primary {
  background: var(--color-primary); color: white; border-color: var(--color-primary);
}
.pb-btn-primary:hover { background: var(--color-primary-hover); border-color: var(--color-primary-hover); }
.pb-btn-add {
  background: var(--color-surface-offset); white-space: nowrap;
}
.pb-btn-danger {
  background: none; border-color: var(--color-error);
  color: var(--color-error); margin-left: auto;
}
.pb-btn-danger:hover { background: var(--color-error-highlight); }
@media (max-width: 500px) {
  .pb-step-body { grid-template-columns: 1fr; }
}
    `;
    document.head.appendChild(style);
  }

  /* ── public API ── */
  return {
    openCreate(api, onSave) { _open(api, null, onSave); },
    openEdit(api, pipeline, onSave) { _open(api, pipeline, onSave); },
  };
})();

window.PipelineBuilder = PipelineBuilder;
