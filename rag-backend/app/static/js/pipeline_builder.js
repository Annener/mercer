/**
 * PipelineBuilder — DAG-редактор pipeline'ов на Vis.js Network
 * Этап 9 pipeline-redesign
 *
 * Зависимости:
 *   - window.chatAPI (api.js)
 *   - Vis.js Network (загружается динамически из CDN)
 *
 * Цветовая кодировка:
 *   __start__  → серый    (#9ea3aa)
 *   retrieval  → синий    (#4A90D9)
 *   validation → оранжевый (#E8943A)
 *   __final__  → фиолетовый (#9B59B6)
 */

const PipelineBuilder = (() => {

  // ── константы ────────────────────────────────────────────────────────────────

  // fix: убран двойной dist/dist в пути CSS (был 404 → vis не применял стили)
  const VIS_CSS_CDN  = 'https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.css';
  const VIS_JS_CDN   = 'https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.js';

  const NODE_COLORS = {
    __start__:  { background: '#9ea3aa', border: '#6b7280', font: { color: '#fff' } },
    retrieval:  { background: '#4A90D9', border: '#2563EB', font: { color: '#fff' } },
    validation: { background: '#E8943A', border: '#C2691A', font: { color: '#fff' } },
    __final__:  { background: '#9B59B6', border: '#7D3C98', font: { color: '#fff' } },
  };

  const STEP_ROLES = ['methodology','lore','campaign_context','character_sheet','session_log','rules'];
  const ROLE_LABELS = {
    methodology:'Методология', lore:'Лор', campaign_context:'Контекст кампании',
    character_sheet:'Лист персонажа', session_log:'Лог сессии', rules:'Правила',
  };

  // ── состояние ────────────────────────────────────────────────────────────────

  let _api        = null;
  let _modal      = null;
  let _pipeline   = null;   // объект из API (или null при создании)
  let _steps      = [];     // array of PipelineStep (новая схема)
  let _finalPrompt = '';
  let _domains    = [];
  let _vaults     = [];
  let _tags       = [];
  let _onSave     = null;

  let _network    = null;   // экземпляр Vis.js Network
  let _nodes      = null;   // Vis DataSet
  let _edges      = null;   // Vis DataSet
  let _selectedId = null;   // выбранный узел

  let _visLoaded  = false;

  // ── public API ───────────────────────────────────────────────────────────────

  async function openCreate(api, onSave) {
    _api = api; _onSave = onSave; _pipeline = null;
    _steps = []; _finalPrompt = '';
    await _loadReferences();
    await _ensureVis();
    _renderModal();
  }

  async function openEdit(api, pipelineData, onSave) {
    _api = api; _onSave = onSave; _pipeline = pipelineData;
    _steps = _normalizeSteps(pipelineData.steps || []);
    _finalPrompt = pipelineData.final_composition?.system_prompt || '';
    await _loadReferences(pipelineData.domain_id, pipelineData.campaign_id);
    await _ensureVis();
    _renderModal();
  }

  // ── загрузка Vis.js ──────────────────────────────────────────────────────────

  function _ensureVis() {
    if (_visLoaded && window.vis) return Promise.resolve();
    return new Promise((resolve, reject) => {
      // CSS
      if (!document.getElementById('vis-css')) {
        const link = document.createElement('link');
        link.id = 'vis-css'; link.rel = 'stylesheet'; link.href = VIS_CSS_CDN;
        document.head.appendChild(link);
      }
      // JS
      if (window.vis) { _visLoaded = true; resolve(); return; }
      const script = document.createElement('script');
      script.src = VIS_JS_CDN;
      script.onload = () => { _visLoaded = true; resolve(); };
      script.onerror = () => reject(new Error('Vis.js не загрузился'));
      document.head.appendChild(script);
    });
  }

  // ── нормализация шагов старого формата ──────────────────────────────────────

  function _normalizeSteps(rawSteps) {
    // Если шаги уже в новом формате (есть step_id) — используем как есть
    if (rawSteps.length === 0) return [];
    if (rawSteps[0].step_id !== undefined) {
      return rawSteps.map(s => ({ ...s }));
    }
    // Старый формат: конвертируем order → after_step_ids
    const sorted = [...rawSteps].sort((a, b) => (a.order || 0) - (b.order || 0));
    return sorted.map((s, i) => ({
      step_id:         s.name ? _slugify(s.name) : `step_${i + 1}`,
      type:            s.type === 'validation' ? 'validation' : 'retrieval',
      name:            s.name || `Шаг ${i + 1}`,
      system_prompt:   s.system_prompt || '',
      after_step_ids:  i === 0 ? [] : [sorted[i-1].name ? _slugify(sorted[i-1].name) : `step_${i}`],
      top_k:           s.top_k || null,
      tag_ids:         s.tag_ids || [],
      role:            s.role || 'rules',
      output_format:   s.output_format || 'text',
      validation_prompt: s.validation_prompt || null,
      options:         s.options || null,
    }));
  }

  // ── загрузка справочников ─────────────────────────────────────────────────────

  async function _loadReferences(domainId = null, campaignId = null) {
    try {
      const resp = await _api.getDomains();
      _domains = (Array.isArray(resp) ? resp : (resp.domains || [])).filter(d => d.enabled !== false);
    } catch { _domains = []; }
    try {
      const v = await _api.getSettingsVaults();
      _vaults = Array.isArray(v) ? v : [];
    } catch { _vaults = []; }
    _tags = [];
    const effectiveDomainId = domainId
      || (_vaults.find(v => v.is_active) || _vaults[0])?.domain_id || null;
    if (effectiveDomainId) {
      try {
        const tagsResp = await _api.getTags(effectiveDomainId, campaignId || null);
        if (Array.isArray(tagsResp)) _tags = tagsResp;
        else if (tagsResp?.global_tags || tagsResp?.by_campaign) {
          _tags = [...(tagsResp.global_tags||[]), ...Object.values(tagsResp.by_campaign||{}).flat()];
        } else _tags = tagsResp?.tags || [];
      } catch { _tags = []; }
    }
  }

  // ── modal HTML ────────────────────────────────────────────────────────────────

  function _renderModal() {
    if (_modal) _modal.remove();
    _injectStyles();
    _modal = document.createElement('div');
    _modal.className = 'modal modal-lg pb-overlay';
    _modal.innerHTML = `
      <div class="pb-wrapper">
        <div class="pb-header">
          <span class="pb-title">${_pipeline ? '✏️ ' + _esc(_pipeline.name) : '✨ Новый pipeline'}</span>
          <div class="pb-header-meta">
            <input id="pb-name"   class="input pb-input-inline" placeholder="Название pipeline"
              value="${_esc(_pipeline?.name || '')}">
            ${!_pipeline ? `<input id="pb-id" class="input pb-input-inline" placeholder="ID (slug)" value="">` : ''}
            <select id="pb-domain" class="input pb-input-inline">
              <option value="">— домен —</option>
              ${_domains.map(d => `<option value="${_esc(d.domain_id)}" ${d.domain_id === (_pipeline?.domain_id||'') ? 'selected' : ''}>${_esc(d.display_name)}</option>`).join('')}
            </select>
          </div>
          <button class="btn btn-sm" id="pb-close-btn" title="Закрыть">✕</button>
        </div>

        <div class="pb-body">
          <!-- Граф -->
          <div class="pb-graph-panel">
            <div class="pb-toolbar">
              <button class="btn btn-sm btn-primary" id="pb-add-step-btn">+ Шаг</button>
              <button class="btn btn-sm" id="pb-validate-btn">✓ Валидировать</button>
              <button class="btn btn-sm" id="pb-fit-btn" title="Вписать граф">⛶</button>
              <span class="pb-hint" id="pb-graph-hint">Кликните на узел для редактирования</span>
            </div>
            <div id="pb-graph" class="pb-graph-container"></div>
            <div id="pb-validate-msg" class="pb-validate-msg" style="display:none"></div>
          </div>

          <!-- Боковая панель редактирования -->
          <div class="pb-sidebar" id="pb-sidebar" style="display:none">
            <div class="pb-sidebar-header">
              <span id="pb-sidebar-title">Редактирование шага</span>
              <button class="btn btn-xs" id="pb-sidebar-close">✕</button>
            </div>
            <div class="pb-sidebar-body" id="pb-sidebar-body"></div>
          </div>
        </div>

        <div class="pb-footer">
          <div id="pb-error" class="pb-error" style="display:none"></div>
          <button class="btn" id="pb-cancel-btn">Отмена</button>
          <button class="btn btn-primary" id="pb-save-btn">💾 Сохранить</button>
        </div>
      </div>
    `;
    document.body.appendChild(_modal);
    _bindModalEvents();
    // fix: двойной rAF гарантирует что flex-layout посчитан до инициализации vis.Network
    requestAnimationFrame(() => requestAnimationFrame(() => _initGraph()));
  }

  // ── события modal ─────────────────────────────────────────────────────────────

  function _bindModalEvents() {
    const q = sel => _modal.querySelector(sel);
    q('#pb-close-btn')?.addEventListener('click', _close);
    q('#pb-cancel-btn')?.addEventListener('click', _close);
    q('#pb-save-btn')?.addEventListener('click', _save);
    q('#pb-add-step-btn')?.addEventListener('click', _addStep);
    q('#pb-validate-btn')?.addEventListener('click', _validateDAG);
    q('#pb-fit-btn')?.addEventListener('click', () => _network?.fit({ animation: true }));
    q('#pb-sidebar-close')?.addEventListener('click', () => _deselectNode());
    q('#pb-domain')?.addEventListener('change', async (e) => {
      const newDomainId = e.target.value || null;
      if (newDomainId) { await _loadReferences(newDomainId); }
    });
    // Закрыть по клику на overlay
    _modal.addEventListener('click', (e) => {
      if (e.target === _modal) _close();
    });
  }

  // ── Vis.js граф ───────────────────────────────────────────────────────────────

  function _initGraph() {
    const container = _modal?.querySelector('#pb-graph');
    if (!container || !window.vis) return;

    _nodes = new vis.DataSet();
    _edges = new vis.DataSet();

    // Виртуальный Start-узел
    _nodes.add({
      id: '__start__', label: '▶ START', title: 'Начало пайплайна',
      ...NODE_COLORS.__start__,
      shape: 'box', font: { color: '#fff', size: 13, face: 'monospace' },
      fixed: false,
    });

    // FinalComposition-узел
    _nodes.add({
      id: '__final__', label: '⚡ FINAL\nComposition',
      title: 'FinalComposition — финальный ответ',
      ...NODE_COLORS.__final__,
      shape: 'box', font: { color: '#fff', size: 12 },
    });

    // Добавляем шаги
    _steps.forEach(s => _addNodeForStep(s));

    // Рёбра: START → стартовые шаги
    _rebuildEdges();

    const options = {
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD',
          sortMethod: 'directed',
          nodeSpacing: 180,
          levelSeparation: 110,
          treeSpacing: 200,
        },
      },
      physics: { enabled: false },
      interaction: { dragNodes: false, tooltipDelay: 200, hover: true },
      nodes: {
        shape: 'box',
        borderWidth: 2,
        margin: { top: 10, right: 14, bottom: 10, left: 14 },
        font: { size: 13 },
        chosen: { node: (values) => { values.borderWidth = 3; } },
      },
      edges: {
        arrows: { to: { enabled: true, scaleFactor: 0.8 } },
        color: { color: '#9ea3aa', hover: '#4A90D9', highlight: '#4A90D9' },
        smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.4 },
        width: 2,
      },
      manipulation: { enabled: false },
    };

    _network = new vis.Network(container, { nodes: _nodes, edges: _edges }, options);

    _network.on('click', (params) => {
      if (params.nodes.length > 0) {
        _selectNode(params.nodes[0]);
      } else {
        _deselectNode();
      }
    });

    // Fit после рендера
    _network.once('afterDrawing', () => {
      _network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
    });
  }

  function _addNodeForStep(step) {
    if (!_nodes) return;
    const colorKey = step.type === 'validation' ? 'validation' : 'retrieval';
    const colors = NODE_COLORS[colorKey];
    const label = `${step.name || step.step_id}\n[${step.type}]`;
    _nodes.add({
      id: step.step_id,
      label,
      title: `ID: ${step.step_id}`,
      background: colors.background,
      border: colors.border,
      color: { background: colors.background, border: colors.border, hover: { background: colors.background, border: '#1d4ed8' } },
      font: { color: colors.font.color, size: 13 },
      shape: 'box',
    });
  }

  function _rebuildEdges() {
    if (!_edges || !_nodes) return;
    _edges.clear();

    const allIds = new Set(_steps.map(s => s.step_id));
    const hasParent = new Set();

    // Рёбра между шагами
    _steps.forEach(step => {
      (step.after_step_ids || []).forEach(parentId => {
        if (allIds.has(parentId) || parentId === '__start__') {
          _edges.add({ from: parentId === '__start__' ? '__start__' : parentId, to: step.step_id, id: `${parentId}->${step.step_id}` });
          hasParent.add(step.step_id);
        }
      });
    });

    // Стартовые шаги → START
    _steps.forEach(step => {
      if (!hasParent.has(step.step_id)) {
        _edges.add({ from: '__start__', to: step.step_id, id: `__start__->${step.step_id}` });
      }
    });

    // Листья → FINAL (шаги без потомков)
    const hasChildren = new Set(_steps.flatMap(s => s.after_step_ids || []));
    _steps.forEach(step => {
      if (!hasChildren.has(step.step_id)) {
        _edges.add({ from: step.step_id, to: '__final__', id: `${step.step_id}->__final__` });
      }
    });

    // Если нет шагов → START → FINAL
    if (_steps.length === 0) {
      _edges.add({ from: '__start__', to: '__final__', id: '__start__->__final__' });
    }

    // Перестроить hierarchical layout
    if (_network) {
      _network.setOptions({ layout: { hierarchical: { enabled: true } } });
      setTimeout(() => _network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } }), 100);
    }
  }

  // ── выбор узла ────────────────────────────────────────────────────────────────

  function _selectNode(nodeId) {
    _selectedId = nodeId;
    const sidebar  = _modal?.querySelector('#pb-sidebar');
    const sbTitle  = _modal?.querySelector('#pb-sidebar-title');
    const sbBody   = _modal?.querySelector('#pb-sidebar-body');
    if (!sidebar || !sbTitle || !sbBody) return;

    sidebar.style.display = 'flex';

    if (nodeId === '__start__') {
      sbTitle.textContent = '▶ START';
      sbBody.innerHTML = '<p class="pb-sidebar-info">Виртуальный стартовый узел. Шаги без родителей автоматически подключаются к нему.</p>';
      return;
    }

    if (nodeId === '__final__') {
      sbTitle.textContent = '⚡ FinalComposition';
      sbBody.innerHTML = _finalCompositionForm();
      _bindFinalForm();
      return;
    }

    const step = _steps.find(s => s.step_id === nodeId);
    if (!step) return;
    sbTitle.textContent = `Шаг: ${step.name || step.step_id}`;
    sbBody.innerHTML = _stepForm(step);
    _bindStepForm(step);
  }

  function _deselectNode() {
    _selectedId = null;
    const sidebar = _modal?.querySelector('#pb-sidebar');
    if (sidebar) sidebar.style.display = 'none';
    _network?.unselectAll();
  }

  // ── форма FinalComposition ────────────────────────────────────────────────────

  function _finalCompositionForm() {
    return `
      <div class="form-group">
        <label>System prompt финальной композиции
          <span class="pb-hint">{STEP_ID.result} {STEP_ID.key} {query}</span>
        </label>
        <textarea id="pbs-final-prompt" class="input pb-textarea" rows="8"
          placeholder="Используй результаты шагов:\n{step1.result}\n\nОтветь на: {query}"
        >${_esc(_finalPrompt)}</textarea>
      </div>
    `;
  }

  function _bindFinalForm() {
    _modal?.querySelector('#pbs-final-prompt')?.addEventListener('input', (e) => {
      _finalPrompt = e.target.value;
    });
  }

  // ── форма шага ────────────────────────────────────────────────────────────────

  function _stepForm(step) {
    const isValidation = step.type === 'validation';
    const roleOptions  = STEP_ROLES.map(r =>
      `<option value="${r}" ${step.role === r ? 'selected' : ''}>${ROLE_LABELS[r] || r}</option>`
    ).join('');
    const tagOptions = _tags.map(t =>
      `<option value="${_esc(String(t.id))}" ${(step.tag_ids||[]).map(String).includes(String(t.id)) ? 'selected' : ''}>${_esc(t.name)}</option>`
    ).join('');
    const allStepIds = _steps.filter(s => s.step_id !== step.step_id).map(s => s.step_id);
    const afterOptions = allStepIds.map(id =>
      `<option value="${_esc(id)}" ${(step.after_step_ids||[]).includes(id) ? 'selected' : ''}>${_esc(id)}</option>`
    ).join('');

    return `
      <div class="form-group">
        <label>ID шага (slug)</label>
        <input id="pbs-step-id" class="input" value="${_esc(step.step_id)}"
          placeholder="analyze" pattern="[a-z0-9_]+">
      </div>
      <div class="form-group">
        <label>Название</label>
        <input id="pbs-name" class="input" value="${_esc(step.name)}" placeholder="Поиск правил">
      </div>
      <div class="form-group">
        <label>Тип</label>
        <select id="pbs-type" class="input">
          <option value="retrieval" ${!isValidation ? 'selected' : ''}>retrieval</option>
          <option value="validation" ${isValidation ? 'selected' : ''}>validation</option>
        </select>
      </div>
      <div class="form-group">
        <label>Зависит от (after_step_ids)
          <span class="pb-hint">Ctrl/Cmd — множественный выбор; пусто = стартовый шаг</span>
        </label>
        <select id="pbs-after" class="input" multiple size="3" style="min-height:64px">
          ${afterOptions || '<option disabled>Нет других шагов</option>'}
        </select>
      </div>

      <!-- retrieval fields -->
      <div id="pbs-retrieval-fields" ${isValidation ? 'style="display:none"' : ''}>
        <div class="form-group">
          <label>Роль</label>
          <select id="pbs-role" class="input">${roleOptions}</select>
        </div>
        <div class="form-row">
          <div class="form-group" style="flex:1">
            <label>Top-K</label>
            <input id="pbs-topk" type="number" class="input" min="1" max="100"
              value="${step.top_k || ''}" placeholder="10">
          </div>
          <div class="form-group" style="flex:1">
            <label>Output format</label>
            <select id="pbs-outfmt" class="input">
              <option value="text" ${step.output_format !== 'json' ? 'selected' : ''}>text</option>
              <option value="json" ${step.output_format === 'json' ? 'selected' : ''}>json</option>
            </select>
          </div>
        </div>
        <div class="form-group">
          <label>Теги
            <span class="pb-hint">Ctrl/Cmd — множественный выбор</span>
          </label>
          <select id="pbs-tags" class="input" multiple size="4" style="min-height:80px">
            ${tagOptions || '<option disabled>Теги не найдены</option>'}
          </select>
        </div>
      </div>

      <!-- validation fields -->
      <div id="pbs-validation-fields" ${!isValidation ? 'style="display:none"' : ''}>
        <div class="form-group">
          <label>Validation prompt</label>
          <textarea id="pbs-val-prompt" class="input pb-textarea-sm" rows="3"
            placeholder="Подтвердите результат: {prev_step.result}">${_esc(step.validation_prompt||'')}</textarea>
        </div>
        <div class="form-group">
          <label>Варианты ответа (options)
            <span class="pb-hint">По одному на строку; пусто → свободный ввод</span>
          </label>
          <textarea id="pbs-options" class="input pb-textarea-sm" rows="3"
            placeholder="Принять\nОтклонить">${_esc((step.options||[]).join('\n'))}</textarea>
        </div>
      </div>

      <div class="form-group">
        <label>System prompt шага
          <span class="pb-hint">{STEP_ID.result} {STEP_ID.key} {query}</span>
        </label>
        <textarea id="pbs-prompt" class="input pb-textarea" rows="5"
          placeholder="Ты — ассистент. Используй контекст: {query}">${_esc(step.system_prompt||'')}</textarea>
      </div>

      <div class="pb-sidebar-actions">
        <button class="btn btn-sm btn-primary" id="pbs-add-child-btn">+ Дочерний шаг</button>
        <button class="btn btn-sm btn-danger" id="pbs-delete-btn">✕ Удалить шаг</button>
      </div>
    `;
  }

  function _bindStepForm(step) {
    const q = sel => _modal?.querySelector(sel);

    // type переключает секции
    q('#pbs-type')?.addEventListener('change', (e) => {
      const isVal = e.target.value === 'validation';
      q('#pbs-retrieval-fields').style.display  = isVal ? 'none'  : '';
      q('#pbs-validation-fields').style.display = isVal ? ''      : 'none';
      _syncStepFromSidebar(step);
      _refreshNodeColor(step);
    });

    // Живое обновление имени в графе
    q('#pbs-name')?.addEventListener('input', () => {
      _syncStepFromSidebar(step);
      _nodes?.update({ id: step.step_id, label: `${step.name || step.step_id}\n[${step.type}]` });
      const sbTitle = _modal?.querySelector('#pb-sidebar-title');
      if (sbTitle) sbTitle.textContent = `Шаг: ${step.name || step.step_id}`;
    });

    // step_id изменение
    q('#pbs-step-id')?.addEventListener('blur', () => {
      const newId = (q('#pbs-step-id')?.value || '').trim().toLowerCase().replace(/\s+/g, '_');
      if (!newId || newId === step.step_id) return;
      if (_steps.some(s => s.step_id === newId)) {
        _showError(`step_id "${newId}" уже существует`);
        q('#pbs-step-id').value = step.step_id;
        return;
      }
      _renameStepId(step.step_id, newId);
      step.step_id = newId;
      _selectedId  = newId;
    });

    // Сохранить изменения при любом событии ввода
    ['#pbs-role','#pbs-topk','#pbs-outfmt','#pbs-after','#pbs-tags',
     '#pbs-prompt','#pbs-val-prompt','#pbs-options'].forEach(sel => {
      q(sel)?.addEventListener('change', () => _syncStepFromSidebar(step));
    });
    ['#pbs-prompt','#pbs-val-prompt','#pbs-options'].forEach(sel => {
      q(sel)?.addEventListener('input', () => _syncStepFromSidebar(step));
    });

    // after_step_ids → rebuild edges
    q('#pbs-after')?.addEventListener('change', () => {
      _syncStepFromSidebar(step);
      _rebuildEdges();
    });

    // + Дочерний шаг
    q('#pbs-add-child-btn')?.addEventListener('click', () => {
      _syncStepFromSidebar(step);
      _addChildStep(step.step_id);
    });

    // Удалить
    q('#pbs-delete-btn')?.addEventListener('click', () => {
      _syncStepFromSidebar(step);
      _deleteStep(step.step_id);
    });
  }

  function _syncStepFromSidebar(step) {
    const q = sel => _modal?.querySelector(sel);
    step.name          = q('#pbs-name')?.value?.trim()   || step.name;
    step.type          = q('#pbs-type')?.value           || step.type;
    step.system_prompt = q('#pbs-prompt')?.value?.trim() || '';
    step.role          = q('#pbs-role')?.value           || step.role;
    const topk = parseInt(q('#pbs-topk')?.value);
    step.top_k         = isNaN(topk) ? null : topk;
    step.output_format = q('#pbs-outfmt')?.value || 'text';
    // after_step_ids
    const afterSel = q('#pbs-after');
    step.after_step_ids = afterSel
      ? Array.from(afterSel.selectedOptions).map(o => o.value)
      : [];
    // tag_ids
    const tagSel = q('#pbs-tags');
    step.tag_ids = tagSel ? Array.from(tagSel.selectedOptions).map(o => o.value) : [];
    // validation fields
    step.validation_prompt = q('#pbs-val-prompt')?.value?.trim() || null;
    const optTxt = q('#pbs-options')?.value?.trim();
    step.options = optTxt ? optTxt.split('\n').map(s => s.trim()).filter(Boolean) : null;
  }

  function _refreshNodeColor(step) {
    const colorKey = step.type === 'validation' ? 'validation' : 'retrieval';
    const colors   = NODE_COLORS[colorKey];
    _nodes?.update({
      id: step.step_id,
      color: { background: colors.background, border: colors.border },
      font: { color: colors.font.color },
      label: `${step.name || step.step_id}\n[${step.type}]`,
    });
  }

  // ── управление шагами ─────────────────────────────────────────────────────────

  function _addStep() {
    const stepId = `step_${Date.now()}`;
    const newStep = {
      step_id: stepId, type: 'retrieval', name: 'Новый шаг',
      system_prompt: '', after_step_ids: [],
      top_k: null, tag_ids: [], role: 'rules',
      output_format: 'text', validation_prompt: null, options: null,
    };
    _steps.push(newStep);
    _addNodeForStep(newStep);
    _rebuildEdges();
    _network?.selectNodes([stepId]);
    _selectNode(stepId);
  }

  function _addChildStep(parentId) {
    const stepId = `step_${Date.now()}`;
    const newStep = {
      step_id: stepId, type: 'retrieval', name: 'Дочерний шаг',
      system_prompt: '', after_step_ids: [parentId],
      top_k: null, tag_ids: [], role: 'rules',
      output_format: 'text', validation_prompt: null, options: null,
    };
    _steps.push(newStep);
    _addNodeForStep(newStep);
    _rebuildEdges();
    _deselectNode();
    _network?.selectNodes([stepId]);
    _selectNode(stepId);
  }

  function _deleteStep(stepId) {
    if (stepId === '__start__' || stepId === '__final__') return;
    // Убрать ссылки из after_step_ids других шагов
    _steps.forEach(s => {
      s.after_step_ids = (s.after_step_ids || []).filter(id => id !== stepId);
    });
    _steps = _steps.filter(s => s.step_id !== stepId);
    _nodes?.remove(stepId);
    _rebuildEdges();
    _deselectNode();
  }

  function _renameStepId(oldId, newId) {
    _steps.forEach(s => {
      s.after_step_ids = (s.after_step_ids || []).map(id => id === oldId ? newId : id);
    });
    _nodes?.update({ id: oldId, id: newId, title: `ID: ${newId}` });
    // Vis не поддерживает переименование id в DataSet напрямую — пересоздаём узел
    const step = _steps.find(s => s.step_id === newId);
    if (step) {
      const nodeData = _nodes?.get(oldId);
      _nodes?.remove(oldId);
      _addNodeForStep(step);
      _rebuildEdges();
    }
  }

  // ── валидация DAG ─────────────────────────────────────────────────────────────

  function _validateDAG() {
    const errors = [];
    const ids = new Set(_steps.map(s => s.step_id));

    // Уникальность step_id
    const seen = new Set();
    _steps.forEach(s => {
      if (seen.has(s.step_id)) errors.push(`Дублирующийся step_id: "${s.step_id}"`);
      seen.add(s.step_id);
    });

    // Self-loop
    _steps.forEach(s => {
      if ((s.after_step_ids||[]).includes(s.step_id))
        errors.push(`Шаг "${s.step_id}" ссылается сам на себя`);
    });

    // Несуществующие after_step_ids
    _steps.forEach(s => {
      (s.after_step_ids||[]).forEach(dep => {
        if (!ids.has(dep)) errors.push(`Шаг "${s.step_id}": зависимость "${dep}" не существует`);
      });
    });

    // Обязательные поля
    _steps.forEach(s => {
      if (!s.name) errors.push(`Шаг "${s.step_id}": не заполнено имя`);
      if (!s.system_prompt) errors.push(`Шаг "${s.step_id}": не заполнен system prompt`);
    });

    // Цикл (упрощённый DFS)
    const hasCycle = _detectCycle();
    if (hasCycle) errors.push('Обнаружен цикл в графе!');

    // FinalComposition
    if (!_finalPrompt.trim()) errors.push('FinalComposition: не заполнен system prompt');

    const msgEl = _modal?.querySelector('#pb-validate-msg');
    if (!msgEl) return;
    if (errors.length === 0) {
      msgEl.innerHTML = '<span class="pb-validate-ok">✓ DAG валиден</span>';
    } else {
      msgEl.innerHTML = '<span class="pb-validate-err">Ошибки:</span><ul>' +
        errors.map(e => `<li>${_esc(e)}</li>`).join('') + '</ul>';
    }
    msgEl.style.display = 'block';
    setTimeout(() => { if (msgEl) msgEl.style.display = 'none'; }, 8000);
    return errors.length === 0;
  }

  function _detectCycle() {
    const WHITE = 0, GRAY = 1, BLACK = 2;
    const color = {};
    _steps.forEach(s => { color[s.step_id] = WHITE; });
    const adj = {};
    _steps.forEach(s => { adj[s.step_id] = []; });
    _steps.forEach(s => {
      (s.after_step_ids||[]).forEach(dep => {
        if (adj[dep]) adj[dep].push(s.step_id);
      });
    });
    function dfs(v) {
      color[v] = GRAY;
      for (const u of (adj[v]||[])) {
        if (color[u] === GRAY) return true;
        if (color[u] === WHITE && dfs(u)) return true;
      }
      color[v] = BLACK;
      return false;
    }
    return _steps.some(s => color[s.step_id] === WHITE && dfs(s.step_id));
  }

  // ── сохранение ────────────────────────────────────────────────────────────────

  async function _save() {
    // Синхронизировать открытую форму бокового панели
    if (_selectedId && _selectedId !== '__start__' && _selectedId !== '__final__') {
      const step = _steps.find(s => s.step_id === _selectedId);
      if (step) _syncStepFromSidebar(step);
    }

    const name     = _modal?.querySelector('#pb-name')?.value?.trim();
    const domainId = _modal?.querySelector('#pb-domain')?.value;

    if (!name)         return _showError('Введите название pipeline');
    if (!domainId)     return _showError('Выберите домен');
    if (!_finalPrompt.trim()) return _showError('Заполните system prompt FinalComposition');
    if (_steps.length === 0) return _showError('Добавьте хотя бы один шаг');

    const valid = _validateDAG();
    if (valid === false) return _showError('Исправьте ошибки DAG перед сохранением');

    // Финальные шаги — без старых полей order/is_final
    const steps = _steps.map(s => {
      const base = {
        step_id:        s.step_id,
        type:           s.type,
        name:           s.name,
        system_prompt:  s.system_prompt,
        after_step_ids: s.after_step_ids || [],
        output_format:  s.output_format || 'text',
      };
      if (s.type === 'retrieval') {
        base.top_k    = s.top_k   || null;
        base.tag_ids  = s.tag_ids || [];
        base.role     = s.role    || null;
      } else {
        base.validation_prompt = s.validation_prompt || null;
        base.options           = s.options           || null;
      }
      return base;
    });

    const payload = {
      name,
      domain_id:         domainId,
      steps,
      final_composition: { system_prompt: _finalPrompt.trim() },
      is_active:         true,
    };

    const btn = _modal?.querySelector('#pb-save-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Сохранение…'; }

    try {
      if (_pipeline) {
        await _api.updatePipeline(_pipeline.pipeline_id, payload);
      } else {
        payload.pipeline_id = _modal?.querySelector('#pb-id')?.value?.trim() || `pipeline_${Date.now()}`;
        await _api.createPipeline(payload);
      }
      _close();
      if (_onSave) await _onSave();
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = '💾 Сохранить'; }
      _showError('Ошибка сохранения: ' + (err.message || String(err)));
    }
  }

  // ── helpers ───────────────────────────────────────────────────────────────────

  function _close() {
    if (_network) { _network.destroy(); _network = null; }
    _modal?.remove(); _modal = null;
    _nodes = null; _edges = null;
  }

  function _showError(msg) {
    const el = _modal?.querySelector('#pb-error');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => { if (el) el.style.display = 'none'; }, 6000);
  }

  function _esc(str) {
    if (str == null) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _slugify(str) {
    return str.toLowerCase().trim().replace(/\s+/g,'_').replace(/[^a-z0-9_]/g,'');
  }

  // ── стили ─────────────────────────────────────────────────────────────────────

  function _injectStyles() {
    if (document.getElementById('pb-styles')) return;
    const s = document.createElement('style');
    s.id = 'pb-styles';
    s.textContent = `
      .pb-overlay {
        position: fixed; inset: 0; z-index: 1000;
        display: flex; align-items: center; justify-content: center;
        background: rgba(0,0,0,0.55);
      }
      .pb-wrapper {
        background: var(--color-surface, #fff);
        border-radius: 12px;
        width: 96vw; max-width: 1140px;
        height: 88vh; max-height: 860px;
        display: flex; flex-direction: column;
        box-shadow: 0 12px 48px rgba(0,0,0,0.32);
        overflow: hidden;
      }
      /* header */
      .pb-header {
        display: flex; align-items: center; gap: 0.75rem;
        padding: 0.75rem 1.25rem;
        border-bottom: 1px solid var(--color-border, #ddd);
        background: var(--color-surface, #fff);
        flex-shrink: 0;
      }
      .pb-title { font-weight: 700; font-size: 1rem; white-space: nowrap; }
      .pb-header-meta { display: flex; gap: 0.5rem; flex: 1; min-width: 0; }
      .pb-input-inline {
        padding: 0.3rem 0.6rem; font-size: 0.85rem;
        border: 1px solid var(--color-border,#ddd);
        border-radius: 6px; background: var(--color-surface,#fff);
        color: var(--color-text,#222); min-width: 0; flex: 1;
      }
      /* body */
      .pb-body {
        flex: 1; display: flex; min-height: 0; overflow: hidden;
      }
      /* graph panel */
      /* fix: добавлен min-height: 0 — без него flex-column не передаёт высоту дочерним элементам */
      .pb-graph-panel {
        flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden;
        border-right: 1px solid var(--color-border,#ddd);
      }
      .pb-toolbar {
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.5rem 0.75rem;
        border-bottom: 1px solid var(--color-border,#ddd);
        flex-shrink: 0;
      }
      /* fix: добавлен min-height: 0 и position: relative — vis.js требует оба для корректного canvas */
      .pb-graph-container {
        flex: 1; min-height: 0; position: relative;
        background: var(--color-surface-offset, #f8f8f8);
      }
      .pb-validate-msg {
        padding: 0.5rem 0.75rem; font-size: 0.82rem;
        background: var(--color-surface,#fff);
        border-top: 1px solid var(--color-border,#ddd);
        max-height: 120px; overflow-y: auto;
        flex-shrink: 0;
      }
      .pb-validate-ok  { color: var(--color-success, #437a22); font-weight: 600; }
      .pb-validate-err { color: var(--color-error, #a12c7b); font-weight: 600; }
      .pb-validate-msg ul { margin: 0.3rem 0 0 1rem; padding: 0; }
      .pb-validate-msg li { margin-bottom: 0.2rem; }
      /* sidebar */
      .pb-sidebar {
        width: 320px; min-width: 280px; max-width: 360px;
        display: flex; flex-direction: column;
        overflow: hidden; flex-shrink: 0;
      }
      .pb-sidebar-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 0.6rem 1rem;
        border-bottom: 1px solid var(--color-border,#ddd);
        font-weight: 600; font-size: 0.9rem;
        background: var(--color-surface,#fff); flex-shrink: 0;
      }
      .pb-sidebar-body {
        flex: 1; overflow-y: auto; padding: 0.75rem 1rem;
        display: flex; flex-direction: column; gap: 0.6rem;
      }
      .pb-sidebar-info {
        font-size: 0.85rem; color: var(--color-text-muted,#888);
        padding: 0.5rem 0;
      }
      .pb-sidebar-actions {
        display: flex; gap: 0.5rem; margin-top: 0.5rem; padding-top: 0.5rem;
        border-top: 1px solid var(--color-border,#ddd);
      }
      /* footer */
      .pb-footer {
        display: flex; align-items: center; justify-content: flex-end;
        gap: 0.5rem; padding: 0.75rem 1.25rem;
        border-top: 1px solid var(--color-border,#ddd);
        background: var(--color-surface,#fff); flex-shrink: 0;
      }
      .pb-error {
        color: var(--color-error, #a12c7b); font-size: 0.85rem;
        padding: 0.35rem 0.65rem;
        background: var(--color-error-highlight, #fdecea);
        border-radius: 6px; margin-right: auto;
      }
      /* form helpers */
      .form-row { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: flex-start; }
      .form-group { display: flex; flex-direction: column; gap: 0.2rem; min-width: 80px; }
      .form-group label { font-size: 0.78rem; font-weight: 500; color: var(--color-text-muted,#888); }
      .pb-hint { font-size: 0.73rem; font-weight: 400; color: var(--color-text-faint,#bbb);
                 text-transform: none; letter-spacing: 0; margin-left: 0.35rem; }
      .pb-textarea    { min-height: 90px; resize: vertical; font-family: monospace; font-size: 0.83rem; }
      .pb-textarea-sm { min-height: 56px; resize: vertical; font-family: monospace; font-size: 0.81rem; }
      .btn-danger { background: var(--color-error-highlight,#fdecea); color: var(--color-error,#a12c7b); border: 1px solid var(--color-error,#a12c7b); }
      .btn-danger:hover { background: var(--color-error,#a12c7b); color: #fff; }
    `;
    document.head.appendChild(s);
  }

  return { openCreate, openEdit };
})();

window.PipelineBuilder = PipelineBuilder;
