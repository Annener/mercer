// Логика sidebar

// Safe localStorage wrapper — falls back to in-memory when access is denied
const _storage = (() => {
    try {
        localStorage.setItem('__test__', '1');
        localStorage.removeItem('__test__');
        return {
            getItem:    (k)    => localStorage.getItem(k),
            setItem:    (k, v) => localStorage.setItem(k, v),
            removeItem: (k)    => localStorage.removeItem(k),
        };
    } catch (_) {
        const mem = {};
        return {
            getItem:    (k)    => (k in mem ? mem[k] : null),
            setItem:    (k, v) => { mem[k] = String(v); },
            removeItem: (k)    => { delete mem[k]; },
        };
    }
})();

class SidebarManager {
    constructor() {
        this.chatList = document.getElementById('chat-list');
        this.newChatBtn = document.getElementById('new-chat-btn');
        this.renameModal = document.getElementById('rename-modal');
        this.renameInput = document.getElementById('rename-input');
        this.renameConfirmBtn = document.getElementById('rename-confirm-btn');
        this.renameCancelBtn = document.getElementById('rename-cancel-btn');

        this.domainSelector = document.getElementById('domain-select');
        // Исправлены ID: campaign-selector / campaign-select (из index.html)
        this.campaignSelectorBlock = document.getElementById('campaign-selector');
        this.campaignSelect = document.getElementById('campaign-select');

        this.currentRenameChatId = null;
        this.domains = [];
        this.domainCache = {};
        this.currentDomain = _storage.getItem('currentDomain') || null;
        // currentVaultId удалён — привязка через domain_id [iter2]
        // BUG FIX #3: используем null вместо пустой строки для безопасной передачи в createChat
        const storedCampaignId = _storage.getItem('currentCampaignId');
        this.currentCampaignId = storedCampaignId || null;

        this.initEventListeners();
        this.loadDomains();
    }

    initEventListeners() {
        this.newChatBtn?.addEventListener('click', () => this.createChatForCurrentDomain());

        this.renameConfirmBtn?.addEventListener('click', () => this.confirmRename());
        this.renameCancelBtn?.addEventListener('click', () => this.hideRenameModal());

        this.domainSelector?.addEventListener('change', (e) => {
            this.switchDomain(e.target.value);
        });

        this.campaignSelect?.addEventListener('change', (e) => {
            // Игнорируем изменения если селектор заблокирован (чат уже привязан к кампании)
            if (this.campaignSelect.disabled) return;
            // BUG FIX #3: сохраняем null вместо пустой строки при выборе «общего режима»
            this.currentCampaignId = e.target.value || null;
            if (this.currentCampaignId) {
                _storage.setItem('currentCampaignId', this.currentCampaignId);
            } else {
                _storage.removeItem('currentCampaignId');
            }
        });

        this.renameModal?.addEventListener('click', (e) => {
            if (e.target === this.renameModal) this.hideRenameModal();
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.chat-dropdown') && !e.target.closest('.chat-item-menu-toggle')) {
                this.closeAllDropdowns();
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllDropdowns();
                this.hideRenameModal();
            }
        });
    }

    async loadDomains() {
        try {
            const data = await chatAPI.getDomains();
            // BUG FIX #7: унифицирован парсинг ответа — поддерживаем оба формата:
            // прямой массив [] или объект { domains: [] }
            this.domains = Array.isArray(data) ? data : (data.domains || []);
            this.domainCache = {};
            for (const domain of this.domains) {
                this.domainCache[domain.domain_id] = domain.display_name || domain.domain_id;
            }
            this.renderDomainOptions();

            if (this.currentDomain && this.domains.some(d => d.domain_id === this.currentDomain)) {
                this.domainSelector.value = this.currentDomain;
            } else if (this.domains.length > 0) {
                this.currentDomain = this.domains[0].domain_id;
                if (this.domainSelector) this.domainSelector.value = this.currentDomain;
                _storage.setItem('currentDomain', this.currentDomain);
            } else {
                this.currentDomain = null;
            }

            await this.loadChats();
            await this.loadCampaignsForDomain();
        } catch (error) {
            console.error('Failed to load domains:', error);
            if (this.chatList) {
                this.chatList.innerHTML = '<div class="empty-state">Не удалось загрузить домены</div>';
            }
        }
    }

    renderDomainOptions() {
        if (!this.domainSelector) return;
        this.domainSelector.innerHTML = '';

        if (this.domains.length === 0) {
            const opt = document.createElement('option');
            opt.textContent = 'Нет доменов';
            opt.disabled = true;
            this.domainSelector.appendChild(opt);
            return;
        }

        for (const domain of this.domains) {
            if (domain.domain_id === 'default') continue;
            const opt = document.createElement('option');
            opt.value = domain.domain_id;
            // BUG FIX #8: formatDomainName больше не вызывается с 'default' —
            // строка continue выше уже её отсеивает, поэтому null-ветка в formatDomainName удалена.
            let label = this.formatDomainName(domain.domain_id);
            if (domain.has_vault === false || domain.vault_enabled === false) {
                label += domain.has_vault === false ? ' (без хранилища)' : ' (хранилище отключено)';
            }
            opt.textContent = label;
            this.domainSelector.appendChild(opt);
        }
    }

    formatDomainName(domainId) {
        // BUG FIX #8: удалена мёртвая ветка 'default' —
        // в renderDomainOptions есть continue для 'default', так что сюда он никогда не попадёт.
        // Сохранен для возможного вызова из других мест и возвращает прочитаемый лейбл.
        const specialNames = { 'dnd': 'D&D', 'work': 'Работа' };
        if (specialNames[domainId]) return specialNames[domainId];
        return this.domainCache[domainId] || domainId.toUpperCase();
    }

    async switchDomain(domainId) {
        if (domainId === this.currentDomain) return;
        this.currentDomain = domainId;
        _storage.setItem('currentDomain', domainId);
        // BUG FIX #3: сбрасываем в null, не в ''
        this.currentCampaignId = null;
        _storage.removeItem('currentCampaignId');
        // Снимаем блокировку селектора при смене домена
        this.unlockCampaign();
        if (window.chatManager) window.chatManager.reset();
        this.closeAllDropdowns();
        await this.loadChats();
        await this.loadCampaignsForDomain();
    }

    getCurrentDomainInfo() {
        return this.domains.find(d => d.domain_id === this.currentDomain) || null;
    }

    async loadChats() {
        if (!this.chatList) return;
        try {
            const data = await chatAPI.listChats(this.currentDomain);
            this.renderChatList(data.chats || []);
        } catch (error) {
            console.error('Failed to load chats:', error);
            this.chatList.innerHTML = '<div class="empty-state">Не удалось загрузить беседы</div>';
        }
    }

    renderChatList(chats) {
        if (!this.chatList) return;
        this.chatList.innerHTML = '';

        if (!chats || chats.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.style.cssText = 'color:#95a5a6;padding:20px 10px;text-align:center;font-size:13px;';
            empty.textContent = 'Нет бесед в этом домене';
            this.chatList.appendChild(empty);
            return;
        }

        for (const chat of chats) {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            chatItem.dataset.chatId = chat.chat_id;

            if (window.chatManager && window.chatManager.currentChatId === chat.chat_id) {
                chatItem.classList.add('active');
            }

            chatItem.innerHTML = `
                <div class="chat-item-title" title="${this.escapeHtml(chat.title)}">${this.escapeHtml(chat.title)}</div>
                <button class="chat-item-menu-toggle" title="Меню">⋮</button>
                <div class="chat-dropdown" data-chat-id="${this.escapeHtml(chat.chat_id)}">
                    <button class="chat-dropdown-item rename-btn">Переименовать</button>
                    <button class="chat-dropdown-item danger delete-btn">Удалить</button>
                </div>
            `;

            chatItem.addEventListener('click', (e) => {
                if (!e.target.closest('.chat-item-menu-toggle') && !e.target.closest('.chat-dropdown')) {
                    this.closeAllDropdowns();
                    this.selectChat(chat.chat_id);
                }
            });

            const toggleBtn = chatItem.querySelector('.chat-item-menu-toggle');
            const dropdown = chatItem.querySelector('.chat-dropdown');

            toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = dropdown.classList.contains('open');
                this.closeAllDropdowns();
                if (!isOpen) {
                    dropdown.classList.add('open');
                    toggleBtn.classList.add('open');
                }
            });

            chatItem.querySelector('.rename-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                this.closeAllDropdowns();
                this.showRenameModal(chat.chat_id, chat.title);
            });

            chatItem.querySelector('.delete-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                this.closeAllDropdowns();
                this.deleteChat(chat.chat_id);
            });

            this.chatList.appendChild(chatItem);
        }
    }

    async selectChat(chatId) {
        if (!this.chatList) return;
        this.chatList.querySelectorAll('.chat-item').forEach(item => item.classList.remove('active'));
        const chatItem = this.chatList.querySelector(`[data-chat-id="${chatId}"]`);
        if (chatItem) chatItem.classList.add('active');
        if (window.chatManager) {
            await window.chatManager.loadChat(chatId);
            // Блокируем селектор кампании только если в чате есть сообщения И есть campaign_id.
            // Пустой чат (нет сообщений) — селектор остаётся разблокированным,
            // даже если у чата уже прописан campaign_id на бэкенде.
            const chat = window.chatManager.currentChat;
            const hasMessages = this._chatHasMessages();
            if (chat && chat.campaign_id && hasMessages) {
                this.lockCampaignToChat(String(chat.campaign_id));
            } else {
                // Пустой чат или нет кампании — показываем кампанию из чата (если есть),
                // но не блокируем: пользователь ещё может её поменять.
                if (chat && chat.campaign_id) {
                    const select = this.campaignSelect;
                    if (select && select.querySelector(`option[value="${chat.campaign_id}"]`)) {
                        select.value = String(chat.campaign_id);
                        this.currentCampaignId = String(chat.campaign_id);
                    }
                }
                this.unlockCampaign();
            }
        }
    }

    /**
     * Возвращает true если в текущем чате есть хотя бы одно сообщение.
     * Считает по DOM: любой .message в контейнере сообщений.
     */
    _chatHasMessages() {
        if (!window.chatManager) return false;
        const container = window.chatManager.messagesContainer;
        if (!container) return false;
        return container.querySelectorAll('.message').length > 0;
    }

    async createChatForCurrentDomain() {
        if (!this.currentDomain) {
            alert('Выберите домен');
            return;
        }
        try {
            // BUG FIX #3: передаём null (не пустую строку) — createChat корректно сериализует null в JSON
            const response = await chatAPI.createChat(
                this.currentDomain,
                this.currentCampaignId || null
            );
            await this.loadChats();
            await this.selectChat(response.chat_id);
            // Новый чат всегда без сообщений — принудительно снимаем блокировку
            // (selectChat мог заблокировать если у чата уже проставлен campaign_id на бэкенде)
            this.unlockCampaign();
        } catch (error) {
            console.error('Failed to create chat:', error);
            alert('Не удалось создать беседу');
        }
    }

    async loadCampaignsForDomain() {
        const block = this.campaignSelectorBlock;
        const select = this.campaignSelect;
        if (!block || !select) return;

        if (!this.currentDomain) {
            block.style.display = 'none';
            return;
        }

        try {
            const campaigns = await chatAPI.getCampaigns(this.currentDomain);
            const campArr = Array.isArray(campaigns) ? campaigns : (campaigns.campaigns || []);

            if (!campArr.length) {
                block.style.display = 'none';
                return;
            }

            select.innerHTML = '<option value="">— общий режим —</option>';
            for (const c of campArr) {
                const opt = document.createElement('option');
                // D14 fix: CampaignRead возвращает поле `id`, не `campaign_id`.
                // Ранее c.campaign_id === undefined → все option имели value="undefined"
                // → currentCampaignId никогда не совпадал → createChat всегда слал campaign_id: null.
                opt.value = String(c.id);
                opt.textContent = c.name;
                select.appendChild(opt);
            }

            // D14 fix: то же поле `id` для поиска совпадения
            if (this.currentCampaignId && campArr.some(c => String(c.id) === this.currentCampaignId)) {
                select.value = this.currentCampaignId;
            } else {
                // BUG FIX #3: сбрасываем в null, не в ''
                this.currentCampaignId = null;
                select.value = '';
            }

            block.style.display = 'block';

        } catch (error) {
            console.warn('Failed to load campaigns for sidebar:', error.message);
            block.style.display = 'none';
        }
    }

    /**
     * Блокирует селектор кампании, отображая кампанию привязанную к текущему чату.
     * Вызывается при открытии чата у которого есть campaign_id И есть сообщения,
     * а также после первого ответа в новом чате с кампанией.
     *
     * FIX: теперь синхронизирует this.currentCampaignId с campaignId чата,
     * чтобы createChatForCurrentDomain() брал правильное значение при создании
     * нового чата после просмотра заблокированного.
     *
     * BUG FIX (race condition): если <option> с нужным campaignId ещё не добавлена
     * в DOM (loadCampaignsForDomain не успел отработать) — создаём временную опцию.
     * Она будет перезаписана при следующем вызове loadCampaignsForDomain.
     */
    lockCampaignToChat(campaignId) {
        const select = this.campaignSelect;
        if (!select) return;
        // Если <option> ещё нет в DOM — создаём временную, чтобы select.value корректно встал.
        // Это происходит когда lockCampaignToChat вызывается из chat.js раньше, чем
        // loadCampaignsForDomain успевает заполнить список (race condition после первого ответа бота).
        if (!select.querySelector(`option[value="${campaignId}"]`)) {
            const tempOpt = document.createElement('option');
            tempOpt.value = campaignId;
            tempOpt.textContent = campaignId; // временный лейбл — перезапишется loadCampaignsForDomain
            tempOpt.dataset.temp = 'true';
            select.appendChild(tempOpt);
        }
        select.value = campaignId;
        // Синхронизируем внутреннее состояние с кампанией чата
        this.currentCampaignId = campaignId;
        _storage.setItem('currentCampaignId', campaignId);
        this.applyLockStyle(true);
    }

    /**
     * Снимает блокировку селектора кампании.
     * Вызывается при создании нового чата, смене домена,
     * а также при открытии пустого чата (без сообщений).
     */
    unlockCampaign() {
        this.applyLockStyle(false);
    }

    /**
     * Применяет/снимает визуальную блокировку селектора кампании.
     * locked=true  → disabled + пониженная прозрачность + title с подсказкой
     * locked=false → enabled + полная прозрачность
     */
    applyLockStyle(locked) {
        const select = this.campaignSelect;
        if (!select) return;
        select.disabled = locked;
        select.style.opacity = locked ? '0.6' : '';
        select.title = locked
            ? 'Кампания закреплена за чатом и не может быть изменена'
            : '';
    }

    showRenameModal(chatId, currentTitle) {
        if (!this.renameModal || !this.renameInput) return;
        this.currentRenameChatId = chatId;
        this.renameInput.value = currentTitle;
        this.renameModal.style.display = 'flex';
        this.renameInput.focus();
        this.renameInput.select();
    }

    hideRenameModal() {
        if (!this.renameModal) return;
        this.renameModal.style.display = 'none';
        this.currentRenameChatId = null;
    }

    async confirmRename() {
        const newTitle = this.renameInput.value.trim();
        if (!newTitle || !this.currentRenameChatId) return;
        try {
            await chatAPI.renameChat(this.currentRenameChatId, newTitle);
            this.hideRenameModal();
            await this.loadChats();
            if (window.chatManager && window.chatManager.currentChatId === this.currentRenameChatId) {
                window.chatManager.chatTitle.textContent = newTitle;
            }
        } catch (error) {
            console.error('Failed to rename chat:', error);
            alert('Не удалось переименовать чат');
        }
    }

    async deleteChat(chatId) {
        if (!confirm('Вы уверены, что хотите удалить эту беседу?')) return;
        try {
            await chatAPI.deleteChat(chatId);
            await this.loadChats();
            if (window.chatManager && window.chatManager.currentChatId === chatId) {
                window.chatManager.reset();
                // При удалении активного чата снимаем блокировку
                this.unlockCampaign();
            }
        } catch (error) {
            console.error('Failed to delete chat:', error);
            alert('Не удалось удалить чат');
        }
    }

    closeAllDropdowns() {
        document.querySelectorAll('.chat-dropdown.open').forEach(d => d.classList.remove('open'));
        document.querySelectorAll('.chat-item-menu-toggle.open').forEach(b => b.classList.remove('open'));
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (!window.chatAPI) {
        console.error('chatAPI not available — SidebarManager will not initialize');
        return;
    }
    window.sidebarManager = new SidebarManager();
});
