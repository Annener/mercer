/**
 * PipelineBuilder — визуальный конструктор pipeline'ов
 * Подключается к settings.js через window.PipelineBuilder
 * Зависимости: window.chatAPI (api.js)
 */

const PipelineBuilder = (() => {

  const STEP_ROLES = ['methodology', 'lore', 'campaign_context', 'character_sheet', 'session_log', 'rules'];
  const ROLE_LABELS = {
    methodology:      'Методология',
    lore:             'Лор',
    campaign_context: 'Контекст кампании',
    character_sheet:  'Лист персонажа',
    session_log:      'Лог сессии',
    rules:            'Правила',
  };

  let _api      = null;
  let _modal    = null;
  let _pipeline = null;
  let _steps    = [];
  let _domains  = [];
  let _vaults   = [];
  let _tags     = [];
  let _onSave   = null;

  // ─── public ─────────────────────────────────────────────────────────────────────────────────

  async function openCreate(api, onSave) {
    _api = api; _onSave = onSave; _pipeline = null; _steps = [];
    await _loadReferences();
    _renderModal();
  }

  async function openEdit(api, pipelineData, onSave) {
    _api = api; _onSave = onSave; _pipeline = pipelineData;
    _steps = (pipelineData.steps || []).sort((a, b) => a.order - b.order).map(s => ({ ...s }));
    await _loadReferences(pipelineData.domain_id, pipelineData.campaign_id);
    _renderModal();
  }

  // ─── data loading ───────────────────────────────────────────────────────────────────────────

  async function _loadReferences(domainId = null, campaignId = null) {
    try {
      const resp = await _api.getDomains();
      _domains = (Array.isArray(resp) ? resp : (resp.domains || [])).filter(d => d.enabled !== false);
    } catch (e) { _domains = []; }

    try {
      const v = await _api.getSettingsVaults();
      _vaults = Array.isArray(v) ? v : [];
    } catch (e) { _vaults = []; }

    _tags = [];
    const effectiveDomainId = domainId
      || (_vaults.find(v => v.is_active) || _vaults[0])?.domain_id
      || null;

    if (effectiveDomainId) {
      try {
        const tagsResp = await _api.getTags(effectiveDomainId, campaignId || null);
        if (Array.isArray(tagsResp)) {
          _tags = tagsResp;
        } else if (tagsResp && (tagsResp.global_tags || tagsResp.by_campaign)) {
          _tags = [
            ...(tagsResp.global_tags || []),
            ...Object.values(tagsResp.by_campaign || {}).flat(),
          ];
        } else {
          _tags = tagsResp?.tags || [];
        }
      } catch (e) { _tags = []; }
    }
  }

  // ─── modal ──────────────────────────────────────────────────────────────────────────────────

  function _renderModal() {
    if (_modal) _modal.remove();
    _modal = document.createElement('div');
    _modal.className = 'modal modal-lg pipeline-builder-modal';
    _modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:1000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.55);';
    const inner = document.createElement('div');
    inner.className = 'pb-inner';
    inner.innerHTML = _modalHTML();
    _modal.appendChild(inner);
    document.body.appendChild(_modal);
    _bindModalEvents();
    _renderStepsList();
  }

  function _modalHTML() {
    const title    = _pipeline ? `Редактировать: ${_esc(_pipeline.name)}` : 'Новый pipeline';
    const name     = _pipeline?.name || '';
    const pid      = _pipeline?.pipeline_id || '';
    const domainId = _pipeline?.domain_id || '';
    const domainsOptions = _domains.map(d =>
      `<option value="${_esc(d.domain_id)}" ${d.domain_id === domainId ? 'selected' : ''}>${_esc(d.display_name)}</option>`
    ).join('');

    return `
      <div class="modal-header">
        <h3>${title}</h3>
        <button class="btn btn-sm" id="pb-close-btn">✕</button>
      </div>
      <div class="modal-body">
        <div class="pb-section">
          <div class="form-row">
            <div class="form-group" style="flex:1">
              <label>Название pipeline</label>
              <input id="pb-name" type="text" class="input" value="${_esc(name)}" placeholder="DnD Rules Lookup">
            </div>
            ${!_pipeline ? `<div class="form-group" style="flex:1">
              <label>ID pipeline</label>
              <input id="pb-id" type="text" class="input" value="${_esc(pid)}" placeholder="dnd_rules_lookup">
            </div>` : ''}
          </div>
          <div class="form-group">
            <label>Домен</label>
            <select id="pb-domain" class="input">
              <option value="">— выберите домен —</option>
              ${domainsOptions}
            </select>
          </div>
        </div>

        <div class="pb-section">
          <div class="pb-section-header">
            <span>Шаги</span>
            <button class="btn btn-sm btn-primary" id="pb-add-step-btn">+ Добавить шаг</button>
          </div>
          <div id="pb-steps-list" class="pb-steps-list"></div>
        </div>

        <div class="pb-section">
          <div class="pb-section-header">
            <span>Финальная композиция</span>
            <span class="pb-hint">Собирает результаты всех шагов в финальный ответ</span>
          </div>
          <div class="form-group">
            <label>System prompt финальной композиции</label>
            <textarea id="pb-final-prompt" class="input pb-textarea" rows="5"
              placeholder="Ты — помощник. Используй контекст для ответа.&#10;&#10;Контекст: {{context}}"
            >${_esc(_pipeline?.final_composition?.system_prompt || '')}</textarea>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" id="pb-cancel-btn">Отмена</button>
        <button class="btn btn-primary" id="pb-save-btn">💾 Сохранить pipeline</button>
      </div>
    `;
  }

  function _bindModalEvents() {
    const q = sel => _modal.querySelector(sel);
    q('#pb-close-btn')?.addEventListener('click', _close);
    q('#pb-cancel-btn')?.addEventListener('click', _close);
    q('#pb-save-btn')?.addEventListener('click', _save);
    q('#pb-add-step-btn')?.addEventListener('click', _addStep);

    q('#pb-domain')?.addEventListener('change', async (e) => {
      const newDomainId = e.target.value || null;
      if (newDomainId) {
        _syncAllSteps();
        await _loadReferences(newDomainId);
        _renderStepsList();
      }
    });
  }

  // ─── steps ──────────────────────────────────────────────────────────────────────────────────

  function _renderStepsList() {
    const container = _modal?.querySelector('#pb-steps-list');
    if (!container) return;
    if (_steps.length === 0) {
      container.innerHTML = '<div class="pb-empty">Шагов пока нет. Нажмите «+ Добавить шаг»</div>';
      return;
    }
    container.innerHTML = _steps.map((step, idx) => _stepHTML(step, idx)).join('');
    _bindStepEvents(container);
  }

  function _stepHTML(step, idx) {
    const roleOptions = STEP_ROLES.map(r =>
      `<option value="${r}" ${step.role === r ? 'selected' : ''}>${ROLE_LABELS[r] || r}</option>`
    ).join('');

    const tagOptions = _tags.map(t =>
      `<option value="${_esc(String(t.id))}" ${(step.tag_ids || []).map(String).includes(String(t.id)) ? 'selected' : ''}>${_esc(t.name)}</option>`
    ).join('');

    return `
      <div class="pb-step" data-idx="${idx}">
        <div class="pb-step-header">
          <span class="pb-step-num">Шаг ${idx + 1}</span>
          <div class="pb-step-actions">
            <button class="btn btn-xs" data-action="step-up"   data-idx="${idx}" ${idx === 0 ? 'disabled' : ''}>↑</button>
            <button class="btn btn-xs" data-action="step-down" data-idx="${idx}" ${idx === _steps.length - 1 ? 'disabled' : ''}>↓</button>
            <button class="btn btn-xs btn-danger" data-action="step-delete" data-idx="${idx}">✕</button>
          </div>
        </div>
        <div class="pb-step-body">
          <div class="form-row">
            <div class="form-group" style="flex:1">
              <label>Название шага</label>
              <input type="text" class="input pb-step-name" data-idx="${idx}" value="${_esc(step.name || '')}" placeholder="Rule Search">
            </div>
            <div class="form-group" style="width:190px">
              <label>Роль</label>
              <select class="input pb-step-role" data-idx="${idx}">${roleOptions}</select>
            </div>
            <div class="form-group" style="width:80px">
              <label>Top-K</label>
              <input type="number" class="input pb-step-topk" data-idx="${idx}" value="${step.top_k || ''}" placeholder="10" min="1" max="100">
            </div>
          </div>
          <div class="form-group">
            <label>Теги (tag_ids) <span class="pb-hint">зажмите Ctrl/Cmd для множественного выбора</span></label>
            <select class="input pb-step-tag-ids" data-idx="${idx}" multiple size="4" style="min-height:80px;">
              ${tagOptions || '<option disabled>Теги не найдены</option>'}
            </select>
          </div>
          <div class="form-group">
            <label>System prompt шага</label>
            <textarea class="input pb-step-prompt pb-textarea-sm" data-idx="${idx}" rows="3"
              placeholder="Используй контекст: {{context}}"
            >${_esc(step.system_prompt || '')}</textarea>
          </div>
        </div>
      </div>
    `;
  }

  // ─── step events ──────────────────────────────────────────────────────────────────────────────

  function _bindStepEvents(container) {
    container.querySelectorAll('[data-action]').forEach(btn => {
      const action = btn.dataset.action;
      const idx = parseInt(btn.dataset.idx);
      btn.addEventListener('click', () => {
        if (action === 'step-up')     { _syncAllSteps(); _moveStep(idx, idx - 1); }
        if (action === 'step-down')   { _syncAllSteps(); _moveStep(idx, idx + 1); }
        if (action === 'step-delete') { _syncAllSteps(); _steps.splice(idx, 1); _renderStepsList(); }
      });
    });
  }

  function _syncStepFromDOM(idx) {
    const stepEl = _modal?.querySelector(`.pb-step[data-idx="${idx}"]`);
    if (!stepEl) return;
    const get = cls => stepEl.querySelector(cls);
    const step = _steps[idx];
    step.name          = get('.pb-step-name')?.value?.trim()   || '';
    step.type          = 'retrieval';
    step.is_final      = false;
    step.role          = get('.pb-step-role')?.value           || 'rules';
    step.system_prompt = get('.pb-step-prompt')?.value?.trim() || '';
    const topk = parseInt(get('.pb-step-topk')?.value);
    step.top_k = isNaN(topk) ? undefined : topk;
    const tagSel = get('.pb-step-tag-ids');
    step.tag_ids = tagSel ? Array.from(tagSel.selectedOptions).map(o => o.value) : [];
  }

  function _syncAllSteps() { _steps.forEach((_, idx) => _syncStepFromDOM(idx)); }

  function _moveStep(fromIdx, toIdx) {
    if (toIdx < 0 || toIdx >= _steps.length) return;
    [_steps[fromIdx], _steps[toIdx]] = [_steps[toIdx], _steps[fromIdx]];
    _renderStepsList();
  }

  function _addStep() {
    _syncAllSteps();
    _steps.push({ order: _steps.length + 1, type: 'retrieval', name: '', role: 'rules', system_prompt: '', tag_ids: [], is_final: false });
    _renderStepsList();
    _modal?.querySelector('#pb-steps-list')?.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ─── save ───────────────────────────────────────────────────────────────────────────────────

  async function _save() {
    _syncAllSteps();
    const name        = _modal.querySelector('#pb-name')?.value?.trim();
    const domainId    = _modal.querySelector('#pb-domain')?.value;
    const finalPrompt = _modal.querySelector('#pb-final-prompt')?.value?.trim();

    if (!name)          return _showError('Введите название pipeline');
    if (!domainId)      return _showError('Выберите домен');
    if (!finalPrompt)   return _showError('Заполните system prompt финальной композиции');
    if (!_steps.length) return _showError('Добавьте хотя бы один шаг');

    for (let i = 0; i < _steps.length; i++) {
      const s = _steps[i];
      if (!s.name)          return _showError(`Шаг ${i+1}: введите название`);
      if (!s.system_prompt) return _showError(`Шаг ${i+1}: заполните system prompt`);
    }

    const steps = _steps.map((s, i) => ({ ...s, order: i + 1 }));
    const payload = { name, domain_id: domainId, steps, final_composition: { system_prompt: finalPrompt }, is_active: true };

    const btn = _modal.querySelector('#pb-save-btn');
    btn.disabled = true; btn.textContent = 'Сохранение…';

    try {
      if (_pipeline) {
        await _api.updatePipeline(_pipeline.pipeline_id, payload);
      } else {
        payload.pipeline_id = _modal.querySelector('#pb-id')?.value?.trim() || `pipeline_${Date.now()}`;
        await _api.createPipeline(payload);
      }
      _close();
      if (_onSave) await _onSave();
    } catch (err) {
      btn.disabled = false; btn.textContent = '💾 Сохранить pipeline';
      _showError('Ошибка сохранения: ' + (err.message || String(err)));
    }
  }

  // ─── helpers ──────────────────────────────────────────────────────────────────────────────────

  function _close() { _modal?.remove(); _modal = null; }

  function _showError(msg) {
    _modal?.querySelector('.pb-error')?.remove();
    const div = document.createElement('div');
    div.className = 'pb-error'; div.textContent = msg;
    _modal?.querySelector('.modal-footer')?.prepend(div);
    setTimeout(() => div.remove(), 5000);
  }

  function _esc(str) {
    if (str == null) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ─── styles ──────────────────────────────────────────────────────────────────────────────────

  function _injectStyles() {
    if (document.getElementById('pb-styles')) return;
    const s = document.createElement('style');
    s.id = 'pb-styles';
    s.textContent = `
      .pb-inner {
        background: var(--color-surface, #fff);
        border-radius: 10px;
        width: 90%;
        max-width: 880px;
        max-height: 90vh;
        display: flex;
        flex-direction: column;
        box-shadow: 0 8px 40px rgba(0,0,0,0.28);
        overflow: hidden;
      }
      .pb-inner .modal-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 1rem 1.5rem; border-bottom: 1px solid var(--color-border,#ddd);
        background: var(--color-surface,#fff);
      }
      .pb-inner .modal-header h3 { margin: 0; }
      .pb-inner .modal-body {
        flex: 1; overflow-y: auto; padding: 0 1.5rem;
        background: var(--color-surface,#fff);
      }
      .pb-inner .modal-footer {
        display: flex; align-items: center; justify-content: flex-end;
        padding: 1rem 1.5rem; border-top: 1px solid var(--color-border,#ddd);
        background: var(--color-surface,#fff); gap: 0.5rem;
      }
      .pb-section { margin: 1.25rem 0; }
      .pb-section-header {
        display: flex; align-items: center; justify-content: space-between;
        margin-bottom: 0.75rem; font-weight: 600; font-size: 0.85rem;
        color: var(--color-text-muted,#888); text-transform: uppercase; letter-spacing: 0.05em;
      }
      .pb-hint { font-size: 0.78rem; font-weight: 400; color: var(--color-text-faint,#bbb); text-transform: none; letter-spacing: 0; margin-left: 0.5rem; }
      .pb-steps-list { display: flex; flex-direction: column; gap: 0.75rem; }
      .pb-empty { text-align:center; color:var(--color-text-faint,#bbb); padding:2rem; border:1px dashed var(--color-border,#ddd); border-radius:8px; }
      .pb-step { border: 1px solid var(--color-border,#ddd); border-radius: 8px; background: var(--color-surface,#fff); overflow: hidden; }
      .pb-step-header { display:flex; align-items:center; justify-content:space-between; padding:0.5rem 0.75rem; background:var(--color-surface-offset,#f5f5f5); border-bottom:1px solid var(--color-border,#ddd); }
      .pb-step-num { font-weight:600; font-size:0.85rem; display:flex; align-items:center; gap:0.4rem; }
      .pb-step-actions { display:flex; gap:0.25rem; }
      .pb-step-body { padding:0.75rem; display:flex; flex-direction:column; gap:0.5rem; }
      .form-row { display:flex; gap:0.75rem; flex-wrap:wrap; align-items:flex-start; }
      .form-group { display:flex; flex-direction:column; gap:0.25rem; min-width:100px; }
      .form-group label { font-size:0.8rem; font-weight:500; color:var(--color-text-muted,#888); }
      .pb-textarea { min-height:100px; resize:vertical; font-family:monospace; font-size:0.85rem; }
      .pb-textarea-sm { min-height:60px; resize:vertical; font-family:monospace; font-size:0.82rem; }
      .btn-xs { padding:2px 7px; font-size:0.75rem; }
      .pb-error { color:var(--color-error,#c0392b); font-size:0.85rem; padding:0.4rem 0.75rem; background:var(--color-error-highlight,#fdecea); border-radius:6px; margin-right:auto; }
    `;
    document.head.appendChild(s);
  }

  _injectStyles();
  return { openCreate, openEdit };
})();

window.PipelineBuilder = PipelineBuilder;
