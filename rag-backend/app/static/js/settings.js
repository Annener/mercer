class SettingsManager {
  constructor(api) {
    this.api = api;
    this.currentTab = 'domains';
    this._initialized = false;
    this.init();
  }

  async init() {
    try {
      this.attachEventListeners();
      await this.loadTab(this.currentTab);
      await this.updateStatusBanner();
      this._initialized = true;
    } catch (error) {
      console.error('SettingsManager init failed:', error);
    }
  }

  attachEventListeners() {
    const settingsBtn = document.getElementById('settings-btn');
    const backBtn = document.getElementById('back-to-chat-btn');
    if (settingsBtn) settingsBtn.addEventListener('click', () => this.show());
    else console.warn('settings-btn not found');
    if (backBtn) backBtn.addEventListener('click', () => this.hide());

    document.querySelectorAll('.settings-tabs button').forEach(button => {
      button.addEventListener('click', () => this.loadTab(button.dataset.tab));
    });
  }

  show() {
    document.querySelector('.app-container')?.classList.add('hidden');
    document.getElementById('settings-page')?.classList.remove('hidden');
    this.loadTab(this.currentTab);
  }

  hide() {
    document.getElementById('settings-page')?.classList.add('hidden');
    document.querySelector('.app-container')?.classList.remove('hidden');
    this.updateStatusBanner();
  }

  _tabMap() {
    return {
      'domains':    'renderDomainsTab',
      'vaults':     'renderVaultsTab',
      'gen-models': 'renderGenerationModelsTab',
      'emb-models': 'renderEmbeddingModelsTab',
      'params':     'renderParamsTab',
      'pipelines':  'renderPipelinesTab',
      'worlds':     'renderWorldsTab',
    };
  }

  async loadTab(tabId) {
    if (!tabId) return;
    this.currentTab = tabId;

    document.querySelectorAll('.settings-tabs button').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });

    const container = document.getElementById('settings-content');
    if (!container) return;
    container.innerHTML = '<div class="loading">Загрузка...</div>';

    try {
      const methodName = this._tabMap()[tabId];
      container.innerHTML = methodName
        ? await this[methodName]()
        : '<div class="placeholder"></div>';
      this.attachTabEventHandlers(tabId);
    } catch (error) {
      container.innerHTML = `<div class="error">${this.escapeHtml(error.message)}</div>`;
    }
  }

  attachTabEventHandlers(tabId) {
    const content = document.getElementById('settings-content');

    // --- Dropdown меню ---
    content?.querySelectorAll('.card-menu-toggle').forEach((button) => {
      button.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        const menu = button.nextElementSibling;
        const isOpen = menu.classList.contains('open');
        content.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
        if (!isOpen) menu.classList.add('open');
      });
    });

    content?.querySelectorAll('.card-menu').forEach((menu) => {
      menu.addEventListener('click', (e) => e.stopPropagation());
    });

    if (this._closeMenusHandler) {
      document.removeEventListener('click', this._closeMenusHandler);
    }
    this._closeMenusHandler = () => {
      content?.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
    };
    document.addEventListener('click', this._closeMenusHandler);

    // --- Обычные action-обработчики (ИСКЛЮЧАЕМ card-menu-item) ---
    content?.querySelectorAll('[data-action]:not(.card-menu-item)').forEach((button) => {
      button.addEventListener('click', () => this.handleAction(button.dataset.action, button.dataset.id, button));
    });

    // --- card-menu-item обрабатываются отдельно ---
    content?.querySelectorAll('.card-menu-item[data-action]').forEach((button) => {
      button.addEventListener('click', (e) => {
        e.stopPropagation();
        content.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
        this.handleAction(button.dataset.action, button.dataset.id, button);
      });
    });

    content?.querySelectorAll('[data-param]').forEach((input) => {
      const saveParam = async () => {
        let value = input.type === 'checkbox' ? input.checked : input.value;
        await this.api.updateSettingsParam(input.dataset.param, value);
        if (input.dataset.param === 'pdf_sidecar.url') await this.updateStatusBanner();
      };
      if (input.type === 'checkbox') input.addEventListener('change', saveParam);
      else input.addEventListener('blur', saveParam);
    });
  }

  async handleAction(action, id, button) {
    try {
      if (action === 'new-domain') await this.showDomainModal();
      if (action === 'edit-domain') await this.showDomainModal(id);
      if (action === 'edit-prompts') await this.showPromptsModal(id);
      if (action === 'delete-domain' && confirm('Удалить домен?')) await this.api.deleteDomain(id);
      if (action === 'new-vault') await this.showVaultModal();
      if (action === 'edit-vault') await this.showVaultModal(id);
      if (action === 'toggle-vault') await this.api.toggleVault(id);
      if (action === 'delete-vault' && confirm('Удалить vault и его векторы?')) await this.api.deleteVault(id);
      if (action === 'new-gen') await this.showGenerationModelModal();
      if (action === 'edit-gen') await this.showGenerationModelModal(id);
      if (action === 'check-gen') alert(JSON.stringify(await this.api.checkGenerationModel(id), null, 2));
      if (action === 'activate-gen') await this.api.activateGenerationModel(id);
      if (action === 'delete-gen' && confirm('Удалить модель?')) await this.api.deleteGenerationModel(id);
      if (action === 'new-emb') await this.showEmbeddingModelModal();
      if (action === 'edit-emb') await this.showEmbeddingModelModal(id);
      if (action === 'check-emb') alert(JSON.stringify(await this.api.checkEmbeddingModel(id), null, 2));
      if (action === 'delete-emb' && confirm('Удалить embedding-модель?')) await this.api.deleteEmbeddingModel(id);
      if (action === 'reset-params' && confirm('Сбросить все параметры?')) {
        await this.api.resetSettingsParams();
        await this.loadTab(this.currentTab);
        await this.updateStatusBanner();
        return;
      }
      if (action === 'edit-pipeline') await this.showPipelineEditModal(id);
      if (action === 'default-param') await this.api.updateSettingsParam(id, SETTINGS_DEFAULTS[id] ?? '');
      if (action === 'new-pipeline') await this.showPipelineModal();
      if (action === 'activate-pipeline') await this.api.activatePipeline(id);
      if (action === 'deactivate-pipeline') await this.api.deactivatePipeline(id);
      if (action === 'delete-pipeline' && confirm('Удалить pipeline? Это действие необратимо.')) {
        await this.api.deletePipeline(id);
      }
      if (action === 'new-world') await this.showWorldModal();
      if (action === 'toggle-world') await this.api.updateWorld(id, { is_active: button.dataset.active !== '1' });
      if (action === 'edit-world') await this.showWorldModal(id);
      if (action === 'delete-world' && confirm(`Удалить мир «${button.dataset.name}»? Это также удалит все связанные кампании.`)) await this.api.deleteWorld(id);
      await this.loadTab(this.currentTab);
      await this.updateStatusBanner();
    } catch (error) {
      alert(error.message);
    }
  }

  async updateStatusBanner() {
    try {
      const status = await this.api.getSettingsStatus();
      const banner = document.getElementById('status-banner');
      if (!banner) return;

      const messages = [];
      if (!status.has_active_generation_model) messages.push('Не выбрана модель генерации. Чат недоступен.');
      if (!status.has_active_embedding_model)  messages.push('Нет активной embedding-модели. RAG недоступен.');
      if (!status.has_vaults)                  messages.push('Нет ни одного vault. RAG недоступен.');
      if (!status.pdf_sidecar_available)        messages.push('PDF Sidecar недоступен. Загрузка PDF работает через pdfminer.');

      banner.innerHTML = messages
        .map(msg => `<div>${this.escapeHtml(msg)}</div>`)
        .join('');
      banner.classList.toggle('hidden', messages.length === 0);

      const chatInput = document.getElementById('message-input');
      if (chatInput) {
        chatInput.disabled = !status.has_active_generation_model;
        if (!status.has_active_generation_model) {
          chatInput.placeholder = 'Сначала настройте модель генерации';
        }
      }
    } catch (error) {
      console.error('Failed to update status banner:', error);
    }
  }

  escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}
const settingsManager = new SettingsManager(chatAPI);