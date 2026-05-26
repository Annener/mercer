// === Markdown Rendering ===
// Настраиваем marked для безопасного рендеринга с highlight.js
if (window.marked) {
    marked.setOptions({
        breaks: true,          // \n превращается в <br>
        gfm: true,             // GitHub Flavored Markdown
        headerIds: false,      // не генерировать id у заголовков
        mangle: false,         // не обфусцировать email
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
        ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|ftp):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
        FORCE_BODY: false,
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Рендерит блок источников под ответом ассистента.
 * sources: [{path, page, vault_id}]
 */
function renderSourcesBlock(sources) {
    if (!sources || sources.length === 0) return '';

    // Группируем по файлу (path), собираем страницы
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

    const items = Array.from(fileMap.values());
    const rows = items.map((item, i) => {
        const fileName = item.path.split('/').pop();
        const pagesLabel = item.pages.length > 0
            ? `стр. ${item.pages.sort((a, b) => a - b).join(', ')}`
            : '';
        const numBadge = `<span class="src-num">${i + 1}</span>`;
        const pageSpan = pagesLabel
            ? `<span class="src-page">${escapeHtml(pagesLabel)}</span>`
            : '';
        return `
            <div class="src-item" title="${escapeHtml(item.path)}">
                ${numBadge}
                <span class="src-name">${escapeHtml(fileName)}</span>
                ${pageSpan}
            </div>`;
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
        
        this.initEventListeners();
    }

    initEventListeners() {
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.messageInput.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 150) + 'px';
        });
    }

    async loadChat(chatId) {
        try {
            this.currentChatId = chatId;
            const data = await chatAPI.getChat(chatId);
            
            this.chatTitle.textContent = data.chat.title;
            this.inputArea.style.display = 'flex';
            this.welcomeMessage.style.display = 'none';
            
            this.clearMessages();
            
            for (const message of data.messages) {
                this.addMessage(message.role, message.content);
            }
            
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

        // Очищаем инпут только если не повторная отправка
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
            this.addMessage('system', `Ошибка: ${error.message}`);
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
        let pendingSources = null; // источники из SSE
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
                        if (parsed.token) {
                            if (!assistantMessage) {
                                assistantMessage = this.addMessage('assistant', '');
                            }
                            fullContent += parsed.token;
                            pendingContent = fullContent;
                            this.scheduleMarkdownRender(assistantMessage, () => pendingContent);
                        } else if (parsed.sources) {
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
            assistantMessage.innerHTML = renderMarkdown(fullContent);
            // Если LLM недоступен, добавляем кнопку повтора
            if (this._isLlmUnavailable(fullContent)) {
                this._appendRetryButton(assistantMessage);
            }
        }

        // Блок источников — добавляем к тому же DOM-элементу сообщения
        if (assistantMessage && pendingSources && pendingSources.length > 0) {
            const sourcesHtml = renderSourcesBlock(pendingSources);
            if (sourcesHtml) {
                assistantMessage.insertAdjacentHTML('beforeend', sourcesHtml);
            }
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
                element.innerHTML = renderMarkdown(text);
                this.scrollToBottom();
            }
        });
    }

    handleJSONResponse(response) {
        if (response.role === 'assistant' && response.state) {
            // Clarification response
            this.addMessage('clarification', response.content);
        } else if (response.content) {
            const msgEl = this.addMessage('assistant', response.content);
            if (this._isLlmUnavailable(response.content)) {
                this._appendRetryButton(msgEl);
            }
        }
    }

    _isLlmUnavailable(text) {
        return text && text.includes('LLM service unavailable');
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
     */
    addMessage(role, content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message message-${role}`;
        
        if (role === 'assistant' || role === 'clarification') {
            messageDiv.innerHTML = renderMarkdown(content);
        } else {
            messageDiv.textContent = content;
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
    window.chatManager = new ChatManager();
});
