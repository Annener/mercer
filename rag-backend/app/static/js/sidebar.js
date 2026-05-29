// Логика sidebar
class SidebarManager {
    constructor() {
        this.chatList = document.getElementById('chat-list');
        this.newChatBtn = document.getElementById('new-chat-btn');
        this.renameModal = document.getElementById('rename-modal');
        this.renameInput = document.getElementById('rename-input');
        this.renameConfirmBtn = document.getElementById('rename-confirm-btn');
        this.renameCancelBtn = document.getElementById('rename-cancel-btn');

        this.domainSelector = document.getElementById('domain-select');
        this.worldSelectorBlock = document.getElementById('world-selector');
        this.worldSelect = document.getElementById('world-select');
        this.campaignsList = document.getElementById('campaigns-list');

        this.currentRenameChatId = null;
        this.domains = [];
        this.domainCache = {};
        this.currentDomain = localStorage.getItem('currentDomain') || null;
        this.currentWorldId = localStorage.getItem('currentWorldId') || '';

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

        this.worldSelect?.addEventListener('change', async (e) => {
            this.currentWorldId = e.target.value;
            localStorage.setItem('currentWorldId', this.currentWorldId);
            await this.loadCampaigns();
        });

        this.renameModal?.addEventListener('click', (e) => {
            if (e.target === this.renameModal) {
                this.hideRenameModal();
            }
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
            this.domains = data.domains || [];
            this.domainCache = {};
            for (const domain of this.domains) {
                // config_api возвращает DomainInfo без display_name — используем domain_id
                this.domainCache[domain.domain_id] = domain.display_name || domain.domain_id;
            }
            this.renderDomainOptions();

            if (this.currentDomain && this.domains.some(d => d.domain_id === this.currentDomain)) {
                this.domainSelector.value = this.currentDomain;
            } else if (this.domains.length > 0) {
                this.currentDomain = this.domains[0].domain_id;
                this.domainSelector.value = this.currentDomain;
                localStorage.setItem('currentDomain', this.currentDomain);
            } else {
                this.currentDomain = null;
            }

            await this.loadChats();
            await this.loadWorlds();
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
            let label = this.formatDomainName(domain.domain_id);
            if (domain.has_vault === false || domain.vault_enabled === false) {
                label += domain.has_vault === false ? ' (без хранилища)' : ' (хранилище отключено)';
            }
            opt.textContent = label;
            this.domainSelector.appendChild(opt);
        }
    }

    formatDomainName(domainId) {
        if (domainId === 'default') return null;
        // Пытаемся взять кэшированное имя; fallback на верхний регистр
        const specialNames = { 'dnd': 'D&D', 'work': 'Работа' };
        if (specialNames[domainId]) return specialNames[domainId];
        return this.domainCache[domainId] || domainId.toUpperCase();
    }

    async switchDomain(domainId) {
        if (domainId === this.currentDomain) return;

        this.currentDomain = domainId;
        localStorage.setItem('currentDomain', domainId);

        if (window.chatManager) {
            window.chatManager.reset();
        }

        this.closeAllDropdowns();
        await this.loadChats();
        await this.loadWorlds();
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
            empty.style.color = '#95a5a6';
            empty.style.padding = '20px 10px';
            empty.style.textAlign = 'center';
            empty.style.fontSize = '13px';
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
        this.chatList.querySelectorAll('.chat-item').forEach(item => {
            item.classList.remove('active');
        });

        const chatItem = this.chatList.querySelector(`[data-chat-id="${chatId}"]`);
        if (chatItem) {
            chatItem.classList.add('active');
        }

        if (window.chatManager) {
            await window.chatManager.loadChat(chatId);
        }
    }

    async createChatForCurrentDomain() {
        if (!this.currentDomain) {
            alert('Выберите домен');
            return;
        }

        try {
            const response = await chatAPI.createChat(null, this.currentDomain, this.currentWorldId || null);
            await this.loadChats();
            await this.selectChat(response.chat_id);
        } catch (error) {
            console.error('Failed to create chat:', error);
            alert('Не удалось создать беседу');
        }
    }

    async loadWorlds() {
        if (!this.worldSelectorBlock || !this.worldSelect) return;
        try {
            const vaults = await chatAPI.getSettingsVaults();
            // Ищем vault ТОЛЬКО для текущего домена, без fallback на любой enabled
            const vault = Array.isArray(vaults)
                ? vaults.find(v => v.domain_id === this.currentDomain && v.enabled)
                : null;

            if (!vault) {
                this.worldSelectorBlock.style.display = 'none';
                return;
            }

            let worlds = [];
            try {
                worlds = await chatAPI.getWorlds(vault.vault_id);
            } catch (worldsError) {
                // Эндпоинт /api/settings/worlds может быть недоступен или вернуть пустой результат
                // Это не критично — просто скрываем world selector
                console.warn('Worlds API unavailable:', worldsError.message);
                this.worldSelectorBlock.style.display = 'none';
                return;
            }

            this.worldSelect.innerHTML = '<option value="">Без мира</option>';
            for (const world of (worlds || [])) {
                const option = document.createElement('option');
                option.value = world.world_id;
                option.textContent = world.name;
                this.worldSelect.appendChild(option);
            }
            this.worldSelect.value = worlds.some(w => w.world_id === this.currentWorldId) ? this.currentWorldId : '';
            this.currentWorldId = this.worldSelect.value;
            this.worldSelectorBlock.style.display = worlds.length ? 'block' : 'none';
            await this.loadCampaigns();
        } catch (error) {
            console.warn('Failed to load worlds:', error.message);
            this.worldSelectorBlock.style.display = 'none';
        }
    }

    async loadCampaigns() {
        if (!this.campaignsList) return;
        this.campaignsList.innerHTML = '';
        if (!this.currentWorldId) return;
        try {
            const campaigns = await chatAPI.getWorldCampaigns(this.currentWorldId);
            if (!campaigns || campaigns.length === 0) return;

            this.campaignsList.innerHTML = campaigns.map(campaign => `
                <button class="campaign-item ${campaign.is_active ? 'active' : ''}" data-id="${this.escapeHtml(campaign.campaign_id)}">
                    ${this.escapeHtml(campaign.name)}
                </button>
            `).join('');
            this.campaignsList.querySelectorAll('.campaign-item').forEach(button => {
                button.addEventListener('click', async () => {
                    try {
                        await chatAPI.toggleCampaign(this.currentWorldId, button.dataset.id);
                        await this.loadCampaigns();
                    } catch (err) {
                        console.warn('Failed to toggle campaign:', err.message);
                        alert(`Ошибка: ${err.message}`);
                    }
                });
            });
        } catch (error) {
            // Эндпоинт кампаний может быть недоступен — это не критично для сайдбара
            console.warn('Failed to load campaigns:', error.message);
        }
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