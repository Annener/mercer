// === Markdown Rendering ===
// Настраиваем marked для безопасного рендеринга с highlight.js
if (window.marked) {
    marked.setOptions({
        breaks: true,          // \n превращается в <br>
        gfm: true,             // GitHub Flavored Markdown
        headerIds: false,      // не генерировать id у заголовков
        mangle: false,         // не обфускировать email
    });
    // Используем highlight.js для блоков кода
    const renderer = new marked.Renderer();
    renderer.code = function (code, language) {
        // marked v12 передаёт объект {text, lang}, v11 — два аргумента
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

/**
 * Преобразует GitHub-стиль callouts ([!NOTE], [!TIP] и т.д.) в хуманный блокцитат.
 * marked не понимает GH-callout-синтаксис и рендерит `[!NOTE]` как простой текст.
 */
const CALLOUT_LABELS = { NOTE: 'Заметка', TIP: 'Совет', IMPORTANT: 'Важно', WARNING: 'Предупреждение', CAUTION: 'Осторожно' };
function preprocessMarkdown(text) {
    if (!text) return text;
    // Стрипаем [!TYPE] в начале блокцитата и заменяем на хуманный заголовок
    return text.replace(/^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/gm, (_, type) => {
        const label = CALLOUT_LABELS[type] || type;
        return `> **${label}:** `;
    });
}

/**
 * Превращает markdown-текст в безопасный HTML.
 * Для user-сообщений не используем (там plain text).
 */
function renderMarkdown(text) {
    if (!text) return '';
    if (!window.marked || !window.DOMPurify) {
        // Fallback если CDN не загрузился
        return escapeHtml(text).replace(/\n/g, '<br>');
    }
    const rawHtml = marked.parse(preprocessMarkdown(text));
    // DOMPurify: разрешаем эмоджи (unicode) и target для ссылок
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

/**
 * Извлекает номера цитат [N] использованных в тексте ответа LLM.
 * Возвращает Set<number> с 1-based индексами.
 */
function extractCitedIndices(text) {
    if (!text) return new Set();
    const cited = new Set();
    // Ищем все [N] и [N, M, ...] в тексте
    // ВАЖНО: экранируем квадратные скобки в regex!
    const re = /\[(\d+)\]/g;
    let m;
    while ((m = re.exec(text)) !== null) {
        cited.add(parseInt(m[1], 10));
    }
    return cited;
}

/**
 * Рендерит блок источников под ответом ассистента.
 * sources: [{path, page, vault_id}] — полный список retrieved.
 * answerText: финальный текст ответа LLM (для фильтрации по цитатам).
 * Показывает только источники реально процитированные в ответе ([1], [2], ...).
 * Нумерация в блоке совпадает с нумерацией в тексте.
 */
function renderSourcesBlock(sources, answerText) {
    if (!sources || sources.length === 0) return '';
    // Группируем по файлу (path), собираем страницы — итоговый список 1-based
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
    // Фильтруем: показываем только те источники, на которые LLM сослался
    const cited = extractCitedIndices(answerText);
    const items = cited.size > 0
        ? allItems.filter((_, i) => cited.has(i + 1))
        : allItems; // если LLM не вставил ни одной цитаты — показываем все
    if (items.length === 0) return '';
    const rows = items.map((item, i) => {
        const fileName = item.path.split('/').pop();
        const pagesLabel = item.pages.length > 0
            ? `стр. ${item.pages.sort((a, b) => a - b).join(', ')}`
            : '';
        const numBadge = `<span class="src-num">${i + 1}</span>`;
        const pageSpan = pagesLabel
            ? `<span class="src-page">${escapeHtml(pagesLabel)}</span>`
            : '';
        return `<div class="src-item" title="${escapeHtml(item.path)}">${numBadge}<span class="src-name">${escapeHtml(fileName)}</span>${pageSpan}</div>`;
    }).join('');
    return `<div class="sources-block"><div class="sources-label">Источники</div><div class="sources-list">${rows}</div></div>`;
}

// === Chat Manager ===
class ChatManager {
    constructor() {
        this.currentChatId = null;
        this.isStreaming = false;
        this._renderScheduled = false;
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
        if (!content || !this.currentChatId || this.isStreaming) {
            return;
        }

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
            // Обработка ошибки LLM
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
        let pendingContent = '';  // буфер для debounced рендера
        let pendingSources = null; // источник из SSE
        let pendingGroupedSources = null;
        let streamDone = false;

        try {
            while (!streamDone) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const data = line.slice(6).trim();

                    // [DONE] — ставим флаг, но НЕ break: в том же чанке могут быть sources
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
                                fullContent += `\n\u2753 ${parsed.question || parsed.content || ''}`;
                                pendingContent = fullContent;
                                this.scheduleMarkdownRender(assistantMessage, () => pendingContent);
                            }
                            if (parsed.type === 'error') this.addMessage('system', parsed.message || 'Pipeline error');
                        }
                        // B05 fix: удалена мёртвая ветка `else if (parsed.token)` —
                        // бэкенд шлёт только {type:"token",content}, формат {token} не используется
                        else if (parsed.sources) {
                            pendingSources = parsed.sources;
                        }
                    } catch (e) {
                        // игнорируем
                    }
                }
            }
        } catch (error) {
            console.error('Stream error:', error);
            if (!assistantMessage) {
                this.addMessage('system', 'Ошибка при получении ответа');
            }
        }

        // Финальный рендер после завершения стрима
        if (assistantMessage && fullContent) {
            this.renderAssistantMarkdown(assistantMessage, fullContent);
            // Если LLM недоступен, добавляем кнопку повтора
            if (this._isLlmUnavailable(fullContent)) {
                this._appendRetryButton(assistantMessage);
            }
        }

        // Блок источников — только те источники, на которые LLM реально сослался ([1], [2]...)
        if (assistantMessage && pendingSources && pendingSources.length > 0) {
            const sourcesHtml = renderSourcesBlock(pendingSources, fullContent);
            if (sourcesHtml) {
                assistantMessage.insertAdjacentHTML('beforeend', sourcesHtml);
            }
        }
        if (assistantMessage && pendingGroupedSources) {
            assistantMessage.insertAdjacentHTML('beforeend', this.renderGroupedSources(pendingGroupedSources));
        }

        this.scrollToBottom();

        if (window.sidebarManager) {
            await window.sidebarManager.loadChats();
            try {
                const chatData = await chatAPI.getChat(this.currentChatId);
                this.chatTitle.textContent = chatData.chat.title;
            } catch (e) { /* ignore */ }
        }
    }

    async setupContextBar(chat) {
        if (!this.contextBar) return;
        // B02 fix: chat.world_id → chat.domain_id (поля world_id нет в модели Chat и контракте)
        const hasContext = Boolean(chat.domain_id);
        this.contextBar.classList.toggle('hidden', !hasContext);
        if (this.worldName) {
            this.worldName.textContent = chat.domain_id ? `Домен: ${chat.domain_id}` : '';
        }
        if (!this.pipelineSelect) return;
        // Передаём campaign_id чтобы бэкенд фильтровал пайплайны по кампании [iter2]
        const pipelines = await chatAPI.getPipelines(chat.domain_id, chat.campaign_id || null);
        this.pipelineSelect.innerHTML = '<option value="">Авто</option>';
        for (const pipeline of (pipelines || []).filter(p => p.is_active)) {
            const option = document.createElement('option');
            option.value = pipeline.pipeline_id;
            option.textContent = pipeline.name;
            this.pipelineSelect.appendChild(option);
        }
        // Если locked_pipeline_id больше не в текущем списке (смена кампании) — игнорируем
        const lockedId = chat.locked_pipeline_id || '';
        const lockedExists = !lockedId || Boolean(this.pipelineSelect.querySelector(`option[value="${lockedId}"]`));
        const effectiveLocked = lockedExists ? lockedId : '';
        this.pipelineSelect.value = effectiveLocked;
        this.pipelineSelect.disabled = Boolean(effectiveLocked);
        if (this.lockPipelineBtn) this.lockPipelineBtn.textContent = effectiveLocked ? '🔒' : '🔓';
    }

    async togglePipelineLock() {
        if (!this.currentChatId || !this.pipelineSelect) return;
        const locked = Boolean(this.currentChat?.locked_pipeline_id);
        const pipelineId = locked ? null : (this.pipelineSelect.value || null);
        await chatAPI.lockPipeline(this.currentChatId, pipelineId);
        const data = await chatAPI.getChat(this.currentChatId);
        this.currentChat = data.chat;
        await this.setupContextBar(data.chat);
    }

    showPipelineBadge(messageEl, data) {
        messageEl.insertAdjacentHTML('beforeend', `
            <div class="pipeline-badge">${escapeHtml(data.pipeline_name || data.pipeline_id)} · ${escapeHtml(data.mode || 'auto')}</div>
        `);
    }

    updateProgressBar(messageEl, step, total, stepName) {
        let bar = messageEl.querySelector('.pipeline-progress');
        if (!bar) {
            bar = document.createElement('div');
            bar.className = 'pipeline-progress';
            messageEl.appendChild(bar);
        }
        bar.innerHTML = Array.from({ length: total }, (_, i) => `
            <span class="pipeline-step ${i + 1 < step ? 'done' : i + 1 === step ? 'active' : ''}" data-step="${i + 1}">${i + 1}</span>
        `).join('') + `<em>${escapeHtml(stepName || '')}</em>`;
    }

    markStepDone(messageEl, step) {
        messageEl.querySelector(`.pipeline-step[data-step="${step}"]`)?.classList.add('done');
    }

    renderGroupedSources(stepGroups) {
        return `
            <div class="sources-grouped">
                <div class="sources-label">Источники по шагам</div>
                ${(stepGroups || []).map(group => `
                    <details class="sources-group" ${group.step === 1 ? 'open' : ''}>
                        <summary>Шаг ${group.step}: ${escapeHtml(group.step_name)} (${group.sources.length})</summary>
                        <div class="sources-list">
                            ${group.sources.map(src => `
                                <div class="src-item">
                                    <span class="src-name">${escapeHtml(src.path || '')}</span>
                                    ${src.page ? `<span class="src-page">стр. ${src.page}</span>` : ''}
                                    <span class="src-vault">${escapeHtml(src.vault_id || '')}</span>
                                </div>
                            `).join('')}
                        </div>
                    </details>
                `).join('')}
            </div>`;
    }

    /**
     * Debounced рендер markdown во время streaming через requestAnimationFrame.
     * Не перерисовываем DOM на каждый токен — только с частотой экрана (~60fps).
     */
    scheduleMarkdownRender(element, contentGetter) {
        if (this._renderScheduled) return;
        this._renderScheduled = true;
        requestAnimationFrame(() => {
            this._renderScheduled = false;
            const text = contentGetter();
            if (text) {
                this.renderAssistantMarkdown(element, text);
                this.scrollToBottom();
            }
        });
    }

    renderAssistantMarkdown(element, text) {
        const prefix = Array.from(element.querySelectorAll('.pipeline-badge, .pipeline-progress'))
            .map((node) => node.outerHTML)
            .join('');
        element.innerHTML = prefix + renderMarkdown(text);
    }

    /**
     * Обработка JSON-ответа для /send и /clarify.
     *
     * C02 fix (регрессия B07):
     *   ClarificationResponse: { message_id, role, content, clarification_id, stage }
     *   Полей `state` и `question` в схеме нет — проверка response.state && response.question
     *   никогда не срабатывала, clarification показывался как обычный ответ.
     *   Исправлено на: проверяем response.clarification_id (не null/undefined).
     *   clarificationId передаётся в addMessage чтобы UI мог потом отправить через submitClarification.
     */
    handleJSONResponse(response) {
        if (response.clarification_id) {
            // Clarification response — передаём clarification_id в addMessage
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

    /**
     * Добавляет сообщение в DOM.
     * - user: plain text (безопасно, без markdown)
     * - assistant/clarification: рендерится как markdown
     * - system: plain text
     * clarificationId: если передан — сохраняется в data-атрибут для submitClarification
     */
    addMessage(role, content, clarificationId = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${role}`;
        
        if (role === 'assistant' || role === 'clarification') {
            messageDiv.innerHTML = renderMarkdown(content);
        } else {
            messageDiv.textContent = content;
        }

        if (clarificationId) {
            messageDiv.dataset.clarificationId = clarificationId;
        }
        
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
        return messageDiv;
    }

    clearMessages() {
        const messages = this.messagesContainer.querySelectorAll('.message, .typing-indicator');
        messages.forEach(msg => msg.remove());
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
