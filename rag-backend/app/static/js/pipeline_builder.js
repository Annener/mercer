/**
 * PipelineBuilder — визуальный конструктор pipeline'ов
 * Подключается к settings.js через window.PipelineBuilder
 * Зависимости: window.chatAPI (api.js)
 */

const PipelineBuilder = (() => {

  const STEP_TYPES = ['book', 'world', 'campaign'];
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
  let _worlds   = [];
  let _vaults   = [];
  let _docCache = {};   // vault_id → DocumentRecord[]
  let _onSave   = null;

  // ─── public ──────────────────────────────────────────────────────────────────

  async function openCreate(api, onSave) {
    _api = api; _onSave = onSave; _pipeline = null; _steps = [];
    await _loadReferences();
    _renderModal();
  }

  async function openEdit(api, pipelineData, onSave) {
    _api = api; _onSave = onSave; _pipeline = pipelineData;
    _steps = (pipelineData.steps || []).sort((a, b) => a.order - b.order).map(s => ({ ...s }));
    await _loadReferences(pipelineData.domain_id);
    _renderModal();
  }

  // ─── data loading ─────────────────────────────────────────────────────────────

  async function _loadReferences(domainId = null) {
    try {
      const resp = await _api.getDomains();
      _domains = (Array.isArray(resp) ? resp : (resp.domains || [])).filter(d => d.enabled !== false);
    } catch (e) { _domains = []; }

    try {
      const v = await _api.getSettingsVaults();
      _vaults = Array.isArray(v) ? v : [];
    } catch (e) { _vaults = []; }

    try {
      const targetVaults = domainId ? _vaults.filter(v => v.domain_id === domainId) : _vaults;
      _worlds = [];
      for (const vault of targetVaults) {
        try {
          const ws = await _api.getWorlds(vault.vault_id);
          const arr = Array.isArray(ws) ? ws : [];
          _worlds.push(...arr.map(w => ({ ...w, vault_id: vault.vault_id, vault_name: vault.display_name || vault.vault_id })));
        } catch (e) { /* skip */ }
      }
    } catch (e) { _worlds = []; }
  }

  async function _loadDocsForVault(vaultId) {
    if (_docCache[vaultId]) return _docCache[vaultId];
    try {
      const resp = await _api.listDocuments(vaultId, 500);
      const docs = resp.documents || [];
      _docCache[vaultId] = docs;
      return docs;
    } catch (e) {
      _docCache[vaultId] = [];
      return [];
    }
  }

  // ─── modal ────────────────────────────────────────────────────────────────────

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
      await _loadReferences(e.target.value);
      _renderStepsList();
    });
  }

  // ─── steps ────────────────────────────────────────────────────────────────────

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
    const typeOptions = STEP_TYPES.map(t =>
      `<option value="${t}" ${step.type === t ? 'selected' : ''}>${t}</option>`
    ).join('');
    const roleOptions = STEP_ROLES.map(r =>
      `<option value="${r}" ${step.role === r ? 'selected' : ''}>${ROLE_LABELS[r] || r}</option>`
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
            <div class="form-group" style="width:140px">
              <label>Тип</label>
              <select class="input pb-step-type" data-idx="${idx}">${typeOptions}</select>
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
          ${_stepTypeFieldsHTML(step, idx)}
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

  function _stepTypeFieldsHTML(step, idx) {
    if (step.type === 'book') {
      // Выпадающий выбор vault + дерево документов с чекбоксами
      const vaultOptions = _vaults.map(v =>
        `<option value="${_esc(v.vault_id)}">${_esc(v.display_name || v.vault_id)}</option>`
      ).join('');
      const selectedVault = step._selectedVault || '';
      return `
        <div class="pb-type-fields" data-typefield="book" data-idx="${idx}">
          <div class="form-row" style="align-items:flex-end">
            <div class="form-group" style="flex:1">
              <label>Vault</label>
              <select class="input pb-step-vault" data-idx="${idx}">
                <option value="">— выберите vault —</option>
                ${vaultOptions}
              </select>
            </div>
            <div class="form-group" style="width:auto;justify-content:flex-end">
              <button class="btn btn-sm btn-secondary pb-load-docs-btn" data-idx="${idx}" style="white-space:nowrap">
                Загрузить файлы
              </button>
            </div>
          </div>
          <div class="pb-doc-tree-wrap" id="pb-doc-tree-${idx}">
            ${_docTreeHTML(step._docs || [], step.document_ids || [], idx)}
          </div>
          <div class="pb-selected-count" id="pb-sel-count-${idx}">
            ${_selectedCountText(step.document_ids || [])}
          </div>
        </div>`;
    }
    if (step.type === 'world') {
      const worldOptions = _worlds.map(w =>
        `<option value="${_esc(w.world_id)}" ${w.world_id === step.world_id ? 'selected' : ''}>${_esc(w.name)} (${_esc(w.vault_name)})</option>`
      ).join('');
      const catVal = (step.categories || []).join(', ');
      return `
        <div class="pb-type-fields">
          <div class="form-row">
            <div class="form-group" style="flex:1">
              <label>World</label>
              <select class="input pb-step-world" data-idx="${idx}">
                <option value="">— выберите world —</option>
                ${worldOptions}
              </select>
            </div>
            <div class="form-group" style="flex:1">
              <label>Категории <span class="pb-hint">(через запятую)</span></label>
              <input type="text" class="input pb-step-categories" data-idx="${idx}" value="${_esc(catVal)}" placeholder="lore, rules">
            </div>
          </div>
        </div>`;
    }
    if (step.type === 'campaign') {
      return `
        <div class="form-group pb-type-fields">
          <label>Campaign ID</label>
          <input type="text" class="input pb-step-campaign" data-idx="${idx}" value="${_esc(step.campaign_id || '')}" placeholder="campaign-uuid">
        </div>`;
    }
    return '';
  }

  // ─── document tree ────────────────────────────────────────────────────────────

  function _buildTree(docs) {
    // docs: [{document_id, document_path, ...}]
    // возвращаем вложенную структуру { name, path, children{}, docs[] }
    const root = { children: {}, docs: [] };
    for (const doc of docs) {
      const parts = (doc.source_path || doc.document_id || 'unknown').replace(/\\/g, '/').split('/');
      const fileName = parts[parts.length - 1];
      const folders  = parts.slice(0, -1);
      let node = root;
      for (const folder of folders) {
        if (!node.children[folder]) node.children[folder] = { name: folder, children: {}, docs: [] };
        node = node.children[folder];
      }
      node.docs.push({ ...doc, _fileName: fileName });
    }
    return root;
  }

  function _docTreeHTML(docs, selectedIds, idx) {
    if (!docs.length) {
      return '<div class="pb-tree-empty">Выберите vault и нажмите «Загрузить файлы»</div>';
    }
    const selected = new Set(selectedIds);
    const tree = _buildTree(docs);

    function renderNode(node, depth) {
      let html = '';
      // сначала папки
      for (const [folderName, child] of Object.entries(node.children)) {
        const allIds = _allDocIds(child);
        const allChecked = allIds.length > 0 && allIds.every(id => selected.has(id));
        const someChecked = !allChecked && allIds.some(id => selected.has(id));
        html += `
          <div class="pb-tree-folder" style="padding-left:${depth * 16}px">
            <label class="pb-tree-folder-label">
              <input type="checkbox" class="pb-folder-check" data-idx="${idx}" data-docids="${_esc(JSON.stringify(allIds))}"
                ${allChecked ? 'checked' : ''} ${someChecked ? 'data-indeterminate="1"' : ''}>
              <span class="pb-folder-icon">📁</span>
              <span>${_esc(folderName)}</span>
              <span class="pb-tree-count">${allIds.length} файл.</span>
            </label>
          </div>
          ${renderNode(child, depth + 1)}`;
      }
      // потом файлы
      for (const doc of node.docs) {
        const isChecked = selected.has(doc.document_id);
        const ext = (doc._fileName || '').split('.').pop()?.toLowerCase();
        const icon = ext === 'pdf' ? '📄' : ext === 'md' ? '📝' : '📃';
        html += `
          <div class="pb-tree-file" style="padding-left:${depth * 16}px">
            <label class="pb-tree-file-label">
              <input type="checkbox" class="pb-doc-check" data-idx="${idx}" data-docid="${_esc(doc.document_id)}"
                ${isChecked ? 'checked' : ''}>
              <span class="pb-file-icon">${icon}</span>
              <span class="pb-file-name" title="${_esc(doc.source_path || doc.document_id)}">${_esc(doc._fileName || doc.document_id)}</span>
            </label>
          </div>`;
      }
      return html;
    }

    return `<div class="pb-doc-tree">${renderNode(tree, 0)}</div>`;
  }

  function _allDocIds(node) {
    const ids = node.docs.map(d => d.document_id);
    for (const child of Object.values(node.children)) {
      ids.push(..._allDocIds(child));
    }
    return ids;
  }

  function _selectedCountText(ids) {
    if (!ids.length) return '<span class="pb-hint">Ни одного файла не выбрано</span>';
    return `<span class="pb-sel-ok">✓ Выбрано файлов: ${ids.length}</span>`;
  }

  // ─── step events ──────────────────────────────────────────────────────────────

  function _bindStepEvents(container) {
    // смена типа → перерисовать поля
    container.querySelectorAll('.pb-step-type').forEach(sel => {
      sel.addEventListener('change', e => {
        const idx = parseInt(e.target.dataset.idx);
        _syncStepFromDOM(idx);
        _steps[idx].type = e.target.value;
        _steps[idx].document_ids = undefined;
        _steps[idx].world_id = undefined;
        _steps[idx].campaign_id = undefined;
        _steps[idx].categories = undefined;
        _steps[idx]._docs = undefined;
        _steps[idx]._selectedVault = undefined;
        _renderStepsList();
      });
    });

    // кнопка загрузки документов
    container.querySelectorAll('.pb-load-docs-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const idx = parseInt(btn.dataset.idx);
        _syncStepFromDOM(idx);
        const vaultSel = _modal.querySelector(`.pb-step-vault[data-idx="${idx}"]`);
        const vaultId = vaultSel?.value;
        if (!vaultId) { _showError('Сначала выберите vault'); return; }
        btn.disabled = true; btn.textContent = 'Загрузка…';
        const docs = await _loadDocsForVault(vaultId);
        _steps[idx]._docs = docs;
        _steps[idx]._selectedVault = vaultId;
        btn.disabled = false; btn.textContent = 'Загрузить файлы';
        // обновляем только дерево, не перерисовывая весь список
        const treeWrap = _modal.querySelector(`#pb-doc-tree-${idx}`);
        if (treeWrap) {
          treeWrap.innerHTML = _docTreeHTML(docs, _steps[idx].document_ids || [], idx);
          _bindDocCheckEvents(treeWrap, idx);
          _applyIndeterminate(treeWrap);
        }
        const countEl = _modal.querySelector(`#pb-sel-count-${idx}`);
        if (countEl) countEl.innerHTML = _selectedCountText(_steps[idx].document_ids || []);
      });
    });

    // чекбоксы папок и файлов (при первом рендере если _docs уже есть)
    container.querySelectorAll('.pb-doc-tree').forEach(tree => {
      const idx = parseInt(tree.closest('.pb-step')?.dataset.idx ?? '-1');
      if (idx >= 0) { _bindDocCheckEvents(tree, idx); _applyIndeterminate(tree); }
    });

    // кнопки управления шагами
    container.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const idx    = parseInt(btn.dataset.idx);
        if (action === 'step-delete') { _syncAllSteps(); _steps.splice(idx, 1); _renderStepsList(); }
        if (action === 'step-up')     { _syncAllSteps(); _moveStep(idx, idx - 1); }
        if (action === 'step-down')   { _syncAllSteps(); _moveStep(idx, idx + 1); }
      });
    });
  }

  function _bindDocCheckEvents(treeEl, idx) {
    // файловые чекбоксы
    treeEl.querySelectorAll('.pb-doc-check').forEach(cb => {
      cb.addEventListener('change', () => {
        const docId = cb.dataset.docid;
        let ids = new Set(_steps[idx].document_ids || []);
        cb.checked ? ids.add(docId) : ids.delete(docId);
        _steps[idx].document_ids = [...ids];
        _updateFolderStates(treeEl, idx);
        const countEl = _modal.querySelector(`#pb-sel-count-${idx}`);
        if (countEl) countEl.innerHTML = _selectedCountText(_steps[idx].document_ids);
      });
    });

    // папочные чекбоксы
    treeEl.querySelectorAll('.pb-folder-check').forEach(cb => {
      cb.addEventListener('change', () => {
        let allIds;
        try { allIds = JSON.parse(cb.dataset.docids || '[]'); } catch (e) { allIds = []; }
        let ids = new Set(_steps[idx].document_ids || []);
        if (cb.checked) allIds.forEach(id => ids.add(id));
        else            allIds.forEach(id => ids.delete(id));
        _steps[idx].document_ids = [...ids];
        // синхронизируем дочерние чекбоксы
        const step = cb.closest('.pb-step');
        step?.querySelectorAll('.pb-doc-check').forEach(fc => {
          if (allIds.includes(fc.dataset.docid)) fc.checked = cb.checked;
        });
        _updateFolderStates(treeEl, idx);
        const countEl = _modal.querySelector(`#pb-sel-count-${idx}`);
        if (countEl) countEl.innerHTML = _selectedCountText(_steps[idx].document_ids);
      });
    });
  }

  function _updateFolderStates(treeEl, idx) {
    const selected = new Set(_steps[idx].document_ids || []);
    treeEl.querySelectorAll('.pb-folder-check').forEach(cb => {
      let allIds;
      try { allIds = JSON.parse(cb.dataset.docids || '[]'); } catch (e) { allIds = []; }
      const allChecked  = allIds.length > 0 && allIds.every(id => selected.has(id));
      const someChecked = !allChecked && allIds.some(id => selected.has(id));
      cb.checked = allChecked;
      cb.indeterminate = someChecked;
    });
  }

  function _applyIndeterminate(treeEl) {
    treeEl.querySelectorAll('.pb-folder-check[data-indeterminate="1"]').forEach(cb => {
      cb.indeterminate = true;
    });
  }

  // ─── sync & move ──────────────────────────────────────────────────────────────

  function _syncStepFromDOM(idx) {
    if (!_modal) return;
    const get = sel => _modal.querySelector(`${sel}[data-idx="${idx}"]`);
    const step = _steps[idx];
    step.name          = get('.pb-step-name')?.value?.trim()   || '';
    step.type          = get('.pb-step-type')?.value           || 'book';
    step.role          = get('.pb-step-role')?.value           || 'rules';
    step.system_prompt = get('.pb-step-prompt')?.value?.trim() || '';
    const topk = parseInt(get('.pb-step-topk')?.value);
    step.top_k = isNaN(topk) ? undefined : topk;
    if (step.type === 'world') {
      step.world_id   = get('.pb-step-world')?.value || undefined;
      const cats      = get('.pb-step-categories')?.value || '';
      step.categories = cats.split(',').map(s => s.trim()).filter(Boolean);
      if (!step.categories.length) step.categories = undefined;
    }
    if (step.type === 'campaign') {
      step.campaign_id = get('.pb-step-campaign')?.value?.trim() || undefined;
    }
    // document_ids синхронизируются live через чекбоксы, не перезаписываем
  }

  function _syncAllSteps() { _steps.forEach((_, idx) => _syncStepFromDOM(idx)); }

  function _moveStep(fromIdx, toIdx) {
    if (toIdx < 0 || toIdx >= _steps.length) return;
    [_steps[fromIdx], _steps[toIdx]] = [_steps[toIdx], _steps[fromIdx]];
    _renderStepsList();
  }

  function _addStep() {
    _syncAllSteps();
    _steps.push({ order: _steps.length + 1, type: 'book', name: '', role: 'rules', system_prompt: '', document_ids: [] });
    _renderStepsList();
    _modal?.querySelector('#pb-steps-list')?.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ─── save ─────────────────────────────────────────────────────────────────────

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
      if (s.type === 'book' && (!s.document_ids?.length))
        return _showError(`Шаг ${i+1}: выберите хотя бы один файл`);
      if (s.type === 'world' && !s.world_id)
        return _showError(`Шаг ${i+1}: выберите World`);
      if (s.type === 'campaign' && !s.campaign_id)
        return _showError(`Шаг ${i+1}: введите Campaign ID`);
    }

    const steps = _steps.map(({ _docs, _selectedVault, ...s }, i) => ({ ...s, order: i + 1 }));
    const payload = { name, domain_id: domainId, steps, final_composition: { system_prompt: finalPrompt }, is_active: true };

    const btn = _modal.querySelector('#pb-save-btn');
    btn.disabled = true; btn.textContent = 'Сохранение…';

    try {
      if (_pipeline) {
        await _api.updatePipeline(_pipeline.id, payload);
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

  // ─── helpers ──────────────────────────────────────────────────────────────────

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

  // ─── styles ───────────────────────────────────────────────────────────────────

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
      .pb-step-num { font-weight:600; font-size:0.85rem; }
      .pb-step-actions { display:flex; gap:0.25rem; }
      .pb-step-body { padding:0.75rem; display:flex; flex-direction:column; gap:0.5rem; }
      .form-row { display:flex; gap:0.75rem; flex-wrap:wrap; align-items:flex-start; }
      .form-group { display:flex; flex-direction:column; gap:0.25rem; min-width:100px; }
      .form-group label { font-size:0.8rem; font-weight:500; color:var(--color-text-muted,#888); }
      .pb-textarea { min-height:100px; resize:vertical; font-family:monospace; font-size:0.85rem; }
      .pb-textarea-sm { min-height:60px; resize:vertical; font-family:monospace; font-size:0.82rem; }
      .btn-xs { padding:2px 7px; font-size:0.75rem; }
      .pb-error { color:var(--color-error,#c0392b); font-size:0.85rem; padding:0.4rem 0.75rem; background:var(--color-error-highlight,#fdecea); border-radius:6px; margin-right:auto; }

      /* Document tree */
      .pb-doc-tree-wrap { margin-top: 0.5rem; border: 1px solid var(--color-border,#ddd); border-radius: 6px; overflow: hidden; }
      .pb-doc-tree { max-height: 220px; overflow-y: auto; padding: 0.25rem 0; background: var(--color-surface-2,#fafafa); }
      .pb-tree-empty { padding: 1rem; text-align:center; color:var(--color-text-faint,#bbb); font-size:0.85rem; }
      .pb-tree-folder, .pb-tree-file { padding: 2px 8px; }
      .pb-tree-folder-label, .pb-tree-file-label {
        display: flex; align-items: center; gap: 0.4rem; cursor: pointer;
        padding: 3px 4px; border-radius: 4px; font-size: 0.85rem; user-select: none;
      }
      .pb-tree-folder-label:hover, .pb-tree-file-label:hover { background: var(--color-surface-dynamic,#eee); }
      .pb-tree-folder-label input, .pb-tree-file-label input { cursor: pointer; flex-shrink: 0; }
      .pb-folder-icon, .pb-file-icon { font-size: 0.9rem; flex-shrink: 0; }
      .pb-file-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width: 340px; }
      .pb-tree-count { margin-left: auto; font-size: 0.75rem; color: var(--color-text-faint,#bbb); flex-shrink: 0; }
      .pb-selected-count { padding: 0.35rem 0.6rem; font-size: 0.82rem; }
      .pb-sel-ok { color: var(--color-success, #27ae60); font-weight: 500; }
    `;
    document.head.appendChild(s);
  }

  _injectStyles();
  return { openCreate, openEdit };
})();

window.PipelineBuilder = PipelineBuilder;