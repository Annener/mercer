// === Markdown Rendering ===
// Настраиваем marked для безопасного рендеринга с highlight.js
if (window.marked) {
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false,
    });
    const renderer = new marked.Renderer();
    renderer.code = function (code, language) {
        const text = typeof code === 'object' ? code.text : code;
        const lang = typeof code === 'object' ? code.lang : language;
        const validLang = lang && window.hljs && window.hljs.getLanguage(lang) ? lang : null;
        let highlighted;
        try {
            highlighted = validLang
                ? window.hljs.highlight(text, { language: validLang }).value
                : window.hljs.highlightAuto(text).value;
        } catch (e) {
            highlighted = escapeHtml(text);
        }
        const langLabel = validLang ? `<span class="code-lang">${validLang}</span>` : '';
        return `<pre class="code-block">${langLabel}<code class="hljs">${highlighted}</code></pre>`;
    };
    marked.use({ renderer });
}

const CALLOUT_LABELS = { NOTE: 'Заметка', TIP: 'Совет', IMPORTANT: 'Важно', WARNING: 'Предупреждение', CAUTION: 'Осторожно' };
function preprocessMarkdown(text) {
    if (!text) return text;
    return text.replace(/^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/gm, (_, type) => {
        const label = CALLOUT_LABELS[type] || type;
        return `> **${label}:** `;
    });
}

function renderMarkdown(text) {
    if (!text) return '';
    if (!window.marked || !window.DOMPurify) {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }
    const rawHtml = marked.parse(preprocessMarkdown(text));
    return DOMPurify.sanitize(rawHtml, {
        ADD_ATTR: ['target'],
        FORBID_TAGS: ['script', 'style', 'iframe'],
        ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|ftp):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
        FORCE_BODY: false,
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function extractCitedIndices(text) {
    if (!text) return new Set();
    const cited = new Set();
    const re = /\[(\d+)\]/g;
    let m;
    while ((m = re.exec(text)) !== null) {
        cited.add(parseInt(m[1], 10));
    }
    return cited;
}

function renderSourcesBlock(sources, answerText) {
    if (!sources || sources.length === 0) return '';
    const fileMap = new Map();
    for (const s of sources) {
        const key = s.path;
        if (!fileMap.has(key)) {
            fileMap.set(key, { path: s.path, vault_id: s.vault_id, pages: [] });
        }
        if (s.page != null) {
            fileMap.get(key).pages.push(s.page);
        }
    }
    const allItems = Array.from(fileMap.values());
    const cited = extractCitedIndices(answerText);
    const items = cited.size > 0 ? allItems.filter((_, i) => cited.has(i + 1)) : allItems;
    if (items.length === 0) return '';
    const rows = items.map((item, i) => {
        const fileName = item.path.split('/').pop();
        const pagesLabel = item.pages.length > 0 ? `стр. ${item.pages.sort((a, b) => a - b).join(', ')}` : '';
        const numBadge = `<span class="src-num">${i + 1}</span>`;
        const pageSpan = pagesLabel ? `<span class="src-page">${escapeHtml(pagesLabel)}</span>` : '';
        return `<div class="src-item" title="${escapeHtml(item.path)}">${numBadge}<span class="src-name">${escapeHtml(fileName)}</span>${pageSpan}</div>`;
    }).join('');
    return `<div class="sources-block"><div class="sources-label">Источники</div><div class="sources-list">${rows}</div></div>`;
}

/**
 * Рендерит блок источников из grouped_by_step формата.
 * Разворачивает все шаги в единый нумерованный список.
 * Нумерация совпадает с [N] в тексте ответа LLM.
 */
function renderGroupedSources(stepGroups, answerText) {
    if (!stepGroups || stepGroups.length === 0) return '';
    const seen = new Map();
    const allItems = [];
    for (const group of stepGroups) {
        for (const src of (group.sources || [])) {
            const key = `${src.path}\x00${src.page ?? ''}`;
            if (!seen.has(key)) {
                const num = allItems.length + 1;
                seen.set(key, num);
                allItems.push({ path: src.path, page: src.page, vault_id: src.vault_id, num });
            }
        }
    }
    if (allItems.length === 0) return '';
    const cited = extractCitedIndices(answerText);
    const items = cited.size > 0 ? allItems.filter(item => cited.has(item.num)) : allItems;
    if (items.length === 0) return '';
    const rows = items.map(item => {
        const fileName = (item.path || '').split('/').pop() || item.path;
        const pagesLabel = item.page != null ? `стр. ${item.page}` : '';
        const numBadge = `<span class="src-num">${item.num}</span>`;
        const pageSpan = pagesLabel ? `<span class="src-page">${escapeHtml(pagesLabel)}</span>` : '';
        return `<div class="src-item" title="${escapeHtml(item.path || '')}">${numBadge}<span class="src-name">${escapeHtml(fileName)}</span>${pageSpan}</div>`;
    }).join('');
    return `<div class="sources-block"><div class="sources-label">Источники</div><div class="sources-list">${rows}</div></div>`;
}

// SVG иконки для кнопки блокировки пайплайна
const LOCK_ICON_CLOSED = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>`;
const LOCK_ICON_OPEN = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>`;

// === Chat Manager ===
class ChatManager {
    constructor() {
        this.currentChatId = null;
        this.isStreaming = false;
        this._renderScheduled = false;
        this._streamingDone = false; // флаг: стрим завершён, RAF не должен перезаписывать
        this.messagesContainer = document.getElementById('messages-container');
        this.inputArea = document.getElementById('input-area');
        this.messageInput = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.chatTitle = document.getElementById('chat-title');
        this.welcomeMessage = document.getElementById('welcome-message');
        this.contextBar = document.getElementById('chat-context-bar');
        this.worldName = document.getElementById('world-name');
        this.pipelineSelect = document.getElementById('pipeline-select');
        this.lockPipelineBtn = document.getElementById('lock-pipeline-btn');
        this.currentChat = null;
        this._lastUserMessage = null;
        this.initEventListeners();
    }

    initEventListeners() {
        this.sendBtn?.addEventListener('click', () => this.sendMessage());
        this.messageInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        this.messageInput?.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 150) + 'px';
        });
        this.lockPipelineBtn?.addEventListener('click', () => this.togglePipelineLock());
    }

    async loadChat(chatId) {
        try {
            this.currentChatId = chatId;
            const data = await chatAPI.getChat(chatId);
            this.currentChat = data.chat;
            this.chatTitle.textContent = data.chat.title;
            this.inputArea.style.display = 'flex';
            this.welcomeMessage.style.display = 'none';
            this.clearMessages();
            for (const message of data.messages) {
                this.addMessage(message.role, message.content);
            }
            await this.setupContextBar(data.chat);
            this.scrollToBottom();
        } catch (error) {
            console.error('Failed to load chat:', error);
            alert('Не удалось загрузить чат');
        }
    }

    async sendMessage(overrideContent = null) {
        const content = overrideContent || this.messageInput.value.trim();
        if (!content || !this.currentChatId || this.isStreaming) return;
        if (!overrideContent) {
            this.messageInput.value = '';
            this.messageInput.style.height = 'auto';
        }
        this.addMessage('user', content);
        this._lastUserMessage = content;
        this.sendBtn.disabled = true;
        this.isStreaming = true;
        try {
            const response = await chatAPI.sendMessage(this.currentChatId, content, true);
            if (response instanceof ReadableStream) {
                await this.handleStreamResponse(response);
            } else {
                this.handleJSONResponse(response);
            }
        } catch (error) {
            console.error('Failed to send message:', error);
            if (error.message.includes('LLM service unavailable') || error.status === 503 || error.message.includes('generation model')) {
                this.addMessage('system', 'Генеративная модель не настроена или недоступна. Перейдите в Настройки → Генеративные модели.');
            } else {
                this.addMessage('system', `Ошибка: ${error.message}`);
            }
        } finally {
            this.sendBtn.disabled = false;
            this.isStreaming = false;
        }
    }

    async handleStreamResponse(stream) {
        const reader = stream.getReader();
        const decoder = new TextDecoder();
        let assistantMessage = null;
        let fullContent = '';
        let pendingContent = '';
        let pendingSources = null;
        let pendingGroupedSources = null;
        let streamDone = false;
        this._streamingDone = false;

        try {
            while (!streamDone) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const data = line.slice(6).trim();
                    if (data === '[DONE]') {
                        streamDone = true;
                        continue;
                    }
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.type) {
                            if (!assistantMessage) assistantMessage = this.addMessage('assistant', '');
                            if (parsed.type === 'pipeline_selected') this.showPipelineBadge(assistantMessage, parsed);
                            if (parsed.type === 'progress') this.updateProgressBar(assistantMessage, parsed.step, parsed.total, parsed.step_name);
                            if (parsed.type === 'step_done') this.markStepDone(assistantMessage, parsed.step);
                            if (parsed.type === 'token') {
                                fullContent += parsed.content || '';
                                pendingContent = fullContent;
                                this.scheduleMarkdownRender(assistantMessage, () => pendingContent);
                            }
                            if (parsed.type === 'sources' && parsed.grouped_by_step) pendingGroupedSources = parsed.step_groups;
                            if (parsed.type === 'sources' && !parsed.grouped_by_step) pendingSources = parsed.sources;
                            if (parsed.type === 'clarification') {
                                if (assistantMessage && !fullContent) {
                                    assistantMessage.remove();
                                    assistantMessage = null;
                                }
                                this.addMessage('clarification', parsed.question || parsed.content || '', parsed.clarification_id);
                            }
                            if (parsed.type === 'error') this.addMessage('system', parsed.message || 'Pipeline error');
                        } else if (parsed.sources) {
                            pendingSources = parsed.sources;
                        }
                    } catch (e) { /* ignore parse errors */ }
                }
            }
        } catch (error) {
            console.error('Stream error:', error);
            if (!assistantMessage) this.addMessage('system', 'Ошибка при получении ответа');
        }

        // Стрим завершён — запрещаем новые RAF-рендеры чтобы они не стёрли источники
        this._streamingDone = true;

        // Финальный рендер markdown (последний раз, больше не тронем)
        if (assistantMessage && fullContent) {
            this.renderAssistantMarkdown(assistantMessage, fullContent);
            if (this._isLlmUnavailable(fullContent)) {
                this._appendRetryButton(assistantMessage);
            }
        }

        // Добавляем блок источников после финального рендера
        // _streamingDone=true гарантирует что RAF больше не вызовет renderAssistantMarkdown
        if (assistantMessage && pendingGroupedSources) {
            const sourcesHtml = renderGroupedSources(pendingGroupedSources, fullContent);
            if (sourcesHtml) assistantMessage.insertAdjacentHTML('beforeend', sourcesHtml);
        } else if (assistantMessage && pendingSources && pendingSources.length > 0) {
            const sourcesHtml = renderSourcesBlock(pendingSources, fullContent);
            if (sourcesHtml) assistantMessage.insertAdjacentHTML('beforeend', sourcesHtml);
        }

        this.scrollToBottom();

        if (window.sidebarManager) {
            await window.sidebarManager.loadChats();
            try {
                const chatData = await chatAPI.getChat(this.currentChatId);
                this.currentChat = chatData.chat;
                this.chatTitle.textContent = chatData.chat.title;
                // После первого ответа фиксируем кампанию если она есть у чата
                // (актуально для новых чатов: campaign_id появляется только после
                // первого обращения к бэкенду который сохраняет его в БД)
                if (chatData.chat.campaign_id && window.sidebarManager) {
                    window.sidebarManager.lockCampaignToChat(String(chatData.chat.campaign_id));
                }
            } catch (e) { /* ignore */ }
        }
    }

    async setupContextBar(chat) {
        if (!this.contextBar) return;
        const hasContext = Boolean(chat.domain_id);
        this.contextBar.classList.toggle('hidden', !hasContext);
        if (this.worldName) {
            this.worldName.textContent = chat.domain_id ? `Домен: ${chat.domain_id}` : '';
        }
        if (!this.pipelineSelect) return;
        const pipelines = await chatAPI.getPipelines(chat.domain_id, chat.campaign_id || null);
        this.pipelineSelect.innerHTML = '<option value="">Авто</option>';
        for (const pipeline of (pipelines || []).filter(p => p.is_active)) {
            const option = document.createElement('option');
            option.value = pipeline.pipeline_id;
            option.textContent = pipeline.name;
            this.pipelineSelect.appendChild(option);
        }
        const lockedId = chat.locked_pipeline_id || '';
        const lockedExists = !lockedId || Boolean(this.pipelineSelect.querySelector(`option[value="${lockedId}"]`));
        const effectiveLocked = lockedExists ? lockedId : '';
        this.pipelineSelect.value = effectiveLocked;
        this.pipelineSelect.disabled = Boolean(effectiveLocked);
        if (this.lockPipelineBtn) {
            this.lockPipelineBtn.classList.toggle('is-locked', Boolean(effectiveLocked));
            this.lockPipelineBtn.setAttribute('aria-label', effectiveLocked ? 'Разблокировать пайплайн' : 'Зафиксировать пайплайн');
            this.lockPipelineBtn.setAttribute('title', effectiveLocked ? 'Пайплайн зафиксирован. Нажмите, чтобы отменить.' : 'Нажмите, чтобы зафиксировать выбранный пайплайн');
            this.lockPipelineBtn.innerHTML = effectiveLocked
                ? `${LOCK_ICON_CLOSED}<span>Авто: выкл</span>`
                : `${LOCK_ICON_OPEN}<span>Авто</span>`;
        }
    }

    async togglePipelineLock() {
        if (!this.currentChatId || !this.pipelineSelect) return;

        const currentlyLocked = Boolean(this.currentChat?.locked_pipeline_id);

        // Читаем значение селектора СИНХРОННО до любых await —
        // после setupContextBar DOM будет перестроен и значение потеряется
        const selectedPipelineId = this.pipelineSelect.value || null;

        if (!currentlyLocked && !selectedPipelineId) {
            // Нечего фиксировать — пользователь не выбрал пайплайн
            return;
        }

        const pipelineId = currentlyLocked ? null : selectedPipelineId;

        await chatAPI.lockPipeline(this.currentChatId, pipelineId);
        const data = await chatAPI.getChat(this.currentChatId);
        this.currentChat = data.chat;
        await this.setupContextBar(data.chat);
    }

    showPipelineBadge(messageEl, data) {
        messageEl.insertAdjacentHTML('beforeend', `<div class="pipeline-badge">${escapeHtml(data.pipeline_name || data.pipeline_id)} · ${escapeHtml(data.mode || 'auto')}</div>`);
    }

    updateProgressBar(messageEl, step, total, stepName) {
        let bar = messageEl.querySelector('.pipeline-progress');
        if (!bar) {
            bar = document.createElement('div');
            bar.className = 'pipeline-progress';
            messageEl.appendChild(bar);
        }
        bar.innerHTML = Array.from({ length: total }, (_, i) =>
            `<span class="pipeline-step ${i + 1 < step ? 'done' : i + 1 === step ? 'active' : ''}" data-step="${i + 1}">${i + 1}</span>`
        ).join('') + `<em>${escapeHtml(stepName || '')}</em>`;
    }

    markStepDone(messageEl, step) {
        messageEl.querySelector(`.pipeline-step[data-step="${step}"]`)?.classList.add('done');
    }

    /**
     * Debounced markdown-рендер во время стриминга (через RAF, ~60fps).
     * После завершения стрима (_streamingDone=true) новые RAF не запускаются,
     * чтобы не стереть источники добавленные после финального рендера.
     */
    scheduleMarkdownRender(element, contentGetter) {
        if (this._renderScheduled || this._streamingDone) return;
        this._renderScheduled = true;
        requestAnimationFrame(() => {
            this._renderScheduled = false;
            if (this._streamingDone) return; // ещё один стоп
            const text = contentGetter();
            if (text) {
                this.renderAssistantMarkdown(element, text);
                this.scrollToBottom();
            }
        });
    }

    /**
     * Перезаписывает innerHTML элемента сохраняя pipeline-баджи
     * И восстанавливая блок источников если он был добавлен ранее.
     */
    renderAssistantMarkdown(element, text) {
        // Сохраняем блок источников перед перезаписью
        const existingSources = element.querySelector('.sources-block');
        const sourcesHtml = existingSources ? existingSources.outerHTML : '';
        // Сохраняем pipeline-баджи и progress-бар
        const prefix = Array.from(element.querySelectorAll('.pipeline-badge, .pipeline-progress'))
            .map(node => node.outerHTML).join('');
        element.innerHTML = prefix + renderMarkdown(text);
        // Восстанавливаем источники если были
        if (sourcesHtml) element.insertAdjacentHTML('beforeend', sourcesHtml);
    }

    handleJSONResponse(response) {
        if (response.clarification_id) {
            this.addMessage('clarification', response.content, response.clarification_id);
        } else if (response.content) {
            const msgEl = this.addMessage('assistant', response.content);
            if (this._isLlmUnavailable(response.content)) {
                this._appendRetryButton(msgEl);
            }
        }
    }

    _isLlmUnavailable(text) {
        if (!text) return false;
        return text.includes('LLM service unavailable')
            || /llm.*(unavailable|error|timeout|refused)/i.test(text)
            || /model.*not.*found/i.test(text)
            || /generation model.*not configured/i.test(text);
    }

    _appendRetryButton(messageEl) {
        const btn = document.createElement('button');
        btn.className = 'retry-btn';
        btn.textContent = 'Повторить запрос';
        btn.title = 'Повторить последнее сообщение';
        btn.addEventListener('click', () => {
            if (this._lastUserMessage) {
                btn.remove();
                this.sendMessage(this._lastUserMessage);
            }
        });
        messageEl.appendChild(btn);
    }

    addMessage(role, content, clarificationId = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${role}`;
        if (role === 'assistant' || role === 'clarification') {
            messageDiv.innerHTML = renderMarkdown(content);
        } else {
            messageDiv.textContent = content;
        }
        if (clarificationId) messageDiv.dataset.clarificationId = clarificationId;
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
        return messageDiv;
    }

    clearMessages() {
        this.messagesContainer.querySelectorAll('.message, .typing-indicator').forEach(msg => msg.remove());
    }

    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    reset() {
        this.currentChatId = null;
        this.clearMessages();
        this.inputArea.style.display = 'none';
        this.welcomeMessage.style.display = 'block';
        this.chatTitle.textContent = 'Выберите чат или создайте новый';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (!window.chatAPI) {
        console.error('chatAPI not available — ChatManager will not initialize');
        return;
    }
    window.chatManager = new ChatManager();
});
