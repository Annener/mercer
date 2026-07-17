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

// SVG иконка «стоп» для кнопки прерывания генерации
const STOP_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>`;

// Специальное значение-сентинел для режима «Без пайплайна».
const PIPELINE_NONE_ID = '__none__';

// ============================================================
// Pipeline inline-карточки (Этап 10)
// ============================================================

/**
 * Рендерит карточку подтверждения запуска пайплайна.
 */
function createConfirmCard(chatId, pipelineName, reasoning, confirmToken, onStream) {
    const card = document.createElement('div');
    card.className = 'pipeline-card pipeline-card--confirm';
    card.dataset.confirmToken = confirmToken;

    card.innerHTML = `
        <div class="pipeline-card__header">
            <span class="pipeline-card__icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
                </svg>
            </span>
            <span class="pipeline-card__title">Запустить пайплайн</span>
            <span class="pipeline-card__name">${escapeHtml(pipelineName)}</span>
        </div>
        ${reasoning ? `<div class="pipeline-card__reasoning">${escapeHtml(reasoning)}</div>` : ''}
        <div class="pipeline-card__actions">
            <button class="pipeline-card__btn pipeline-card__btn--confirm" type="button">Запустить</button>
            <button class="pipeline-card__btn pipeline-card__btn--cancel" type="button">Отмена</button>
        </div>
    `;

    const setDone = (label, mod) => {
        card.querySelector('.pipeline-card__actions').innerHTML =
            `<span class="pipeline-card__status pipeline-card__status--${mod}">${escapeHtml(label)}</span>`;
        card.classList.add('pipeline-card--done');
    };

    card.querySelector('.pipeline-card__btn--confirm').addEventListener('click', async () => {
        setDone('Запускается…', 'running');
        try {
            const result = await chatAPI.pipelineConfirm(chatId, confirmToken, 'confirm');
            if (result instanceof ReadableStream) {
                setDone('Выполняется', 'running');
                await onStream(result);
            } else {
                setDone('Запущен', 'ok');
            }
        } catch (e) {
            setDone(`Ошибка: ${e.message}`, 'error');
        }
    });

    card.querySelector('.pipeline-card__btn--cancel').addEventListener('click', async () => {
        setDone('Отменён', 'cancelled');
        try {
            await chatAPI.pipelineConfirm(chatId, confirmToken, 'cancel');
        } catch (_) { /* Игнорируем ошибки отмены */ }
    });

    return card;
}

/**
 * Рендерит карточку validation (human-in-the-loop пауза).
 */
function createValidationCard(chatId, stepName, content, options, resumeToken, onStream) {
    const card = document.createElement('div');
    card.className = 'pipeline-card pipeline-card--validation';
    card.dataset.resumeToken = resumeToken;

    const optionsHtml = (options && options.length > 0)
        ? options.map(opt =>
            `<button class="pipeline-card__option" type="button" data-value="${escapeHtml(opt)}">${escapeHtml(opt)}</button>`
          ).join('')
        : '';

    card.innerHTML = `
        <div class="pipeline-card__header">
            <span class="pipeline-card__icon pipeline-card__icon--validation" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
            </span>
            <span class="pipeline-card__title">Требуется подтверждение</span>
            <span class="pipeline-card__step-name">${escapeHtml(stepName || '')}</span>
        </div>
        ${content ? `<div class="pipeline-card__content">${renderMarkdown(content)}</div>` : ''}
        ${optionsHtml ? `<div class="pipeline-card__options">${optionsHtml}</div>` : ''}
        <div class="pipeline-card__actions">
            ${!optionsHtml ? `<button class="pipeline-card__btn pipeline-card__btn--confirm" type="button">Продолжить</button>` : ''}
            <button class="pipeline-card__btn pipeline-card__btn--cancel" type="button">Отменить пайплайн</button>
        </div>
    `;

    const setDone = (label, mod) => {
        card.querySelector('.pipeline-card__actions').innerHTML =
            `<span class="pipeline-card__status pipeline-card__status--${mod}">${escapeHtml(label)}</span>`;
        card.querySelectorAll('.pipeline-card__option').forEach(btn => {
            btn.disabled = true;
            btn.classList.add('is-disabled');
        });
        card.classList.add('pipeline-card--done');
    };

    const doResume = async (feedback) => {
        const preview = feedback ? feedback.slice(0, 40) : 'Продолжить';
        setDone(`✓ ${preview}`, 'ok');
        try {
            const result = await chatAPI.pipelineResume(chatId, resumeToken, 'resume', feedback);
            if (result instanceof ReadableStream) {
                await onStream(result);
            }
        } catch (e) {
            const actionsEl = card.querySelector('.pipeline-card__actions');
            if (actionsEl) {
                actionsEl.innerHTML = `<span class="pipeline-card__status pipeline-card__status--error">Ошибка: ${escapeHtml(e.message)}</span>`;
            }
        }
    };

    card.querySelectorAll('.pipeline-card__option').forEach(btn => {
        btn.addEventListener('click', () => {
            card.querySelectorAll('.pipeline-card__option').forEach(b => b.classList.remove('is-selected'));
            btn.classList.add('is-selected');
            doResume(btn.dataset.value);
        });
    });

    card.querySelector('.pipeline-card__btn--confirm')?.addEventListener('click', () => {
        doResume(null);
    });

    card.querySelector('.pipeline-card__btn--cancel').addEventListener('click', async () => {
        setDone('Пайплайн отменён', 'cancelled');
        try {
            await chatAPI.pipelineResume(chatId, resumeToken, 'cancel');
        } catch (_) { /* ignore */ }
    });

    return card;
}

/**
 * Вставляет статусную строку (pipeline_resumed / pipeline_cancelled).
 */
function createPipelineStatusLine(type, data) {
    const el = document.createElement('div');
    if (type === 'pipeline_resumed') {
        const preview = data.user_feedback_preview ? ` — «${escapeHtml(data.user_feedback_preview)}»` : '';
        el.className = 'pipeline-status-line pipeline-status-line--resumed';
        el.textContent = `▶ Пайплайн продолжен${preview}`;
    } else {
        el.className = 'pipeline-status-line pipeline-status-line--cancelled';
        el.textContent = `✕ Пайплайн отменён${data.step_name ? ` на шаге «${escapeHtml(data.step_name)}»` : ''}`;
    }
    return el;
}

// ============================================================
// Full Document Mode — панель выбора документов
// ============================================================

/**
 * Создаёт DOM-элемент панели выбора документов.
 * Вставляется в ленту чата при получении SSE-события full_document_selection_required.
 *
 * @param {string} chatId
 * @param {Array} candidates     — массив DocumentCandidate
 * @param {Function} onStream   — (ReadableStream) => Promise<void>
 * @returns {HTMLElement}
 */
function createFullDocPanel(chatId, candidates, onStream) {
    const panel = document.createElement('div');
    panel.className = 'fulldoc-panel';

    // Заголовок
    panel.innerHTML = `
        <div class="fulldoc-panel__header">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            Выберите документы для полной отправки
        </div>
        <p class="fulldoc-panel__subtitle">Найдены релевантные документы. Отметьте те, которые нужно передать в модель целиком:</p>
        <div class="fulldoc-panel__list" id="fulldoc-list-${chatId}"></div>
        <div class="fulldoc-panel__total" id="fulldoc-total-${chatId}">Выбрано: <strong>0</strong> токенов</div>
        <div class="fulldoc-panel__actions">
            <button class="fulldoc-panel__btn fulldoc-panel__btn--confirm" type="button">Продолжить с выбранными</button>
            <button class="fulldoc-panel__btn fulldoc-panel__btn--skip" type="button">Продолжить без полных документов</button>
        </div>
    `;

    const listEl   = panel.querySelector(`#fulldoc-list-${chatId}`);
    const totalEl  = panel.querySelector(`#fulldoc-total-${chatId}`);
    const confirmBtn = panel.querySelector('.fulldoc-panel__btn--confirm');
    const skipBtn    = panel.querySelector('.fulldoc-panel__btn--skip');

    // Рендерим кандидатов
    for (const c of candidates) {
        const item = document.createElement('label');
        item.className = 'fulldoc-doc-item';

        const tokensText = c.estimated_tokens != null
            ? `~${c.estimated_tokens.toLocaleString()} токенов`
            : '';
        const alreadySentBadge = c.already_sent
            ? `<span class="fulldoc-doc-item__badge">уже загружен</span>`
            : '';

        item.innerHTML = `
            <input type="checkbox" value="${escapeHtml(c.document_id)}" data-tokens="${c.estimated_tokens || 0}">
            <span class="fulldoc-doc-item__title" title="${escapeHtml(c.source_path || c.title)}">${escapeHtml(c.title || c.document_id)}</span>
            ${tokensText ? `<span class="fulldoc-doc-item__tokens">${escapeHtml(tokensText)}</span>` : ''}
            ${alreadySentBadge}
        `;
        listEl.appendChild(item);
    }

    // Обновляем счётчик токенов
    const updateTotal = () => {
        let total = 0;
        listEl.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
            total += parseInt(cb.dataset.tokens || '0', 10);
        });
        totalEl.innerHTML = `Выбрано: <strong>${total.toLocaleString()}</strong> токенов`;
    };
    listEl.addEventListener('change', updateTotal);

    // Блокируем кнопки + чекбоксы, ставим done-класс
    const lockPanel = () => {
        confirmBtn.disabled = true;
        skipBtn.disabled = true;
        listEl.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.disabled = true; });
        panel.style.opacity = '0.65';
    };

    const doConfirm = async (selectedIds) => {
        lockPanel();
        try {
            const result = await chatAPI.fullDocConfirm(chatId, selectedIds);
            if (result instanceof ReadableStream) {
                await onStream(result);
            }
        } catch (e) {
            // Восстанавливаем кнопки при ошибке
            confirmBtn.disabled = false;
            skipBtn.disabled = false;
            listEl.querySelectorAll('input[type="checkbox"]').forEach(cb => { cb.disabled = false; });
            panel.style.opacity = '1';
            const errLine = document.createElement('div');
            errLine.className = 'pipeline-status-line pipeline-status-line--cancelled';
            errLine.textContent = `Ошибка: ${e.message}`;
            panel.appendChild(errLine);
        }
    };

    confirmBtn.addEventListener('click', () => {
        const selected = Array.from(
            listEl.querySelectorAll('input[type="checkbox"]:checked')
        ).map(cb => cb.value);
        doConfirm(selected);
    });

    skipBtn.addEventListener('click', () => {
        doConfirm([]);
    });

    return panel;
}

// === Chat Manager ===
class ChatManager {
    constructor() {
        this.currentChatId = null;
        this.isStreaming = false;
        this._renderScheduled = false;
        this._streamingDone = false;
        this._abortController = null;
        this._streamEnabled = true;
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
        this.updateModeBtn = document.getElementById('update-mode-btn');
        this.processingStatusEl = document.getElementById('processing-status');
        this.fulldocCheckbox = document.getElementById('fulldoc-checkbox');
        this.currentChat = null;
        this._lastUserMessage = null;
        this.initEventListeners();
        this.pendingBanner = new PendingFilesBanner('chat-banner-area');
        this._loadStreamSetting();
    }

    async _loadStreamSetting() {
        try {
            const params = await chatAPI.getSettingsParams();
            const val = params['chat.stream_answers'];
            this._streamEnabled = (val === true || val === 'true');
        } catch (e) {
            console.warn('chat.js: could not load stream_answers setting, defaulting to true', e);
        }
    }

    // -------------------------------------------------------
    // Processing status indicator
    // -------------------------------------------------------

    showProcessingStatus(text) {
        if (!this.processingStatusEl) return;
        this.processingStatusEl.innerHTML =
            `<span class="processing-status__dots"><span></span><span></span><span></span></span>` +
            `<span class="processing-status__text">${escapeHtml(text)}</span>`;
        this.processingStatusEl.classList.remove('hidden');
    }

    hideProcessingStatus() {
        if (!this.processingStatusEl) return;
        this.processingStatusEl.classList.add('hidden');
        this.processingStatusEl.innerHTML = '';
    }

    // -------------------------------------------------------
    // Stop / Send button toggle
    // -------------------------------------------------------

    _setStopMode() {
        this._abortController = new AbortController();
        if (this.sendBtn) {
            this.sendBtn.classList.add('btn-stop');
            this.sendBtn.setAttribute('aria-label', 'Остановить генерацию');
            this.sendBtn.title = 'Остановить генерацию';
            this.sendBtn.innerHTML = `${STOP_ICON}<span>Стоп</span>`;
            this.sendBtn.disabled = false;
        }
        return this._abortController.signal;
    }

    _resetToSendMode() {
        this._abortController = null;
        if (this.sendBtn) {
            this.sendBtn.classList.remove('btn-stop');
            this.sendBtn.removeAttribute('aria-label');
            this.sendBtn.title = '';
            this.sendBtn.innerHTML = 'Отправить';
            this.sendBtn.disabled = false;
        }
    }

    initEventListeners() {
        this.sendBtn?.addEventListener('click', () => {
            if (this.isStreaming && this._abortController) {
                this._abortController.abort();
            } else {
                this.sendMessage();
            }
        });
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
        this.pipelineSelect?.addEventListener('change', () => {
            if (this.pipelineSelect) {
                this.pipelineSelect.dataset.selectedPipelineId = this.pipelineSelect.value;
            }
        });

        // Full Document Mode toggle
        this.fulldocCheckbox?.addEventListener('change', async (e) => {
            if (!this.currentChatId || !this.currentChat) return;
            const enabled = e.target.checked;
            try {
                // Передаём campaign_id если он есть (бэкенд ребяет обязательное поле)
                await chatAPI.setFullDocMode(
                    this.currentChatId,
                    enabled,
                    this.currentChat.campaign_id || null,
                );
                // Обновляем локальный объект чата
                if (this.currentChat) this.currentChat.full_document_mode_enabled = enabled;
            } catch (err) {
                console.error('setFullDocMode failed:', err);
                // Откатываем чекбокс при ошибке
                e.target.checked = !enabled;
            }
        });

        // Update Mode button
        this.updateModeBtn?.addEventListener('click', () => {
            if (!this.currentChatId) return;
            // Если панель уже открыта — не открывать вторую
            if (this.messagesContainer.querySelector('.um-panel')) return;
            const panel = createUpdateModePanel(this.currentChatId);
            this.messagesContainer.appendChild(panel);
            this.scrollToBottom();
        });
    }

    async loadChat(chatId) {
        try {
            this.currentChatId = chatId;
            await this._loadStreamSetting();
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
        this.isStreaming = true;
        const signal = this._setStopMode();
        try {
            const stream = this._streamEnabled;
            const response = await chatAPI.sendMessage(
                this.currentChatId,
                content,
                stream,
                stream ? signal : null,
            );
            if (response instanceof ReadableStream) {
                await this.handleStreamResponse(response, signal);
            } else {
                this.handleJSONResponse(response);
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                // пользователь нажал «Стоп»
            } else if (error.message.includes('LLM service unavailable') || error.status === 503 || error.message.includes('generation model')) {
                this.addMessage('system', 'Генеративная модель не настроена или недоступна. Перейдите в Настройки → Генеративные модели.');
            } else {
                console.error('Failed to send message:', error);
                this.addMessage('system', `Ошибка: ${error.message}`);
            }
        } finally {
            this.isStreaming = false;
            this._resetToSendMode();
            this.hideProcessingStatus();
        }
    }

    /**
     * Обработчик SSE-стрима.
     * Добавлена обработка чанка:
     *   full_document_selection_required → createFullDocPanel()
     *
     * @param {ReadableStream} stream
     * @param {AbortSignal|null} signal
     */
    async handleStreamResponse(stream, signal = null) {
        const reader = stream.getReader();
        const decoder = new TextDecoder();
        let assistantMessage = null;
        let fullContent = '';
        let pendingContent = '';
        let pendingSources = null;
        let pendingGroupedSources = null;
        let streamDone = false;
        this._streamingDone = false;

        const handleNestedStream = async (nestedStream) => {
            this.isStreaming = true;
            try {
                await this.handleStreamResponse(nestedStream, signal);
            } finally {
                this.isStreaming = false;
            }
        };

        try {
            while (!streamDone) {
                if (signal && signal.aborted) break;

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
                            const needsAssistant = ![
                                'pipeline_confirm_required',
                                'validation_required',
                                'pipeline_resumed',
                                'pipeline_cancelled',
                                'step_status',
                                'full_document_selection_required',
                            ].includes(parsed.type);
                            if (needsAssistant && !assistantMessage) {
                                assistantMessage = this.addMessage('assistant', '');
                            }

                            if (parsed.type === 'step_status') {
                                this.showProcessingStatus(parsed.text || '');
                            }

                            if (parsed.type === 'pipeline_selected') {
                                if (!assistantMessage) assistantMessage = this.addMessage('assistant', '');
                                this.showPipelineBadge(assistantMessage, parsed);
                            }

                            if (parsed.type === 'pipeline_confirm_required') {
                                const card = createConfirmCard(
                                    this.currentChatId,
                                    parsed.pipeline_name || '',
                                    parsed.reasoning || '',
                                    parsed.confirm_token,
                                    handleNestedStream
                                );
                                this.messagesContainer.appendChild(card);
                                this.scrollToBottom();
                            }

                            if (parsed.type === 'validation_required') {
                                const card = createValidationCard(
                                    this.currentChatId,
                                    parsed.step_name || '',
                                    parsed.content || '',
                                    parsed.options || [],
                                    parsed.resume_token,
                                    handleNestedStream
                                );
                                this.messagesContainer.appendChild(card);
                                this.scrollToBottom();
                            }

                            if (parsed.type === 'pipeline_resumed' || parsed.type === 'pipeline_cancelled') {
                                const statusLine = createPipelineStatusLine(parsed.type, parsed);
                                this.messagesContainer.appendChild(statusLine);
                                this.scrollToBottom();
                            }

                            // Full Document Mode: пауза для выбора документов
                            if (parsed.type === 'full_document_selection_required') {
                                this.hideProcessingStatus();
                                const panel = createFullDocPanel(
                                    this.currentChatId,
                                    parsed.candidates || [],
                                    handleNestedStream
                                );
                                this.messagesContainer.appendChild(panel);
                                this.scrollToBottom();
                            }

                            if (parsed.type === 'progress') this.updateProgressBar(assistantMessage, parsed.step, parsed.total, parsed.step_name);
                            if (parsed.type === 'step_done') this.markStepDone(assistantMessage, parsed.step);
                            if (parsed.type === 'token') {
                                this.hideProcessingStatus();
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
                                this.hideProcessingStatus();
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
            if (error.name !== 'AbortError') {
                console.error('Stream error:', error);
                if (!assistantMessage) this.addMessage('system', 'Ошибка при получении ответа');
            }
        } finally {
            try { reader.cancel(); } catch (_) { /* ignore */ }
        }

        this._streamingDone = true;

        if (assistantMessage && fullContent) {
            this.renderAssistantMarkdown(assistantMessage, fullContent);
            if (this._isLlmUnavailable(fullContent)) {
                this._appendRetryButton(assistantMessage);
            }
        }

        if (assistantMessage && pendingGroupedSources) {
            const sourcesHtml = renderGroupedSources(pendingGroupedSources, fullContent);
            if (sourcesHtml) assistantMessage.insertAdjacentHTML('beforeend', sourcesHtml);
        } else if (assistantMessage && pendingSources && pendingSources.length > 0) {
            const sourcesHtml = renderSourcesBlock(pendingSources, fullContent);
            if (sourcesHtml) assistantMessage.insertAdjacentHTML('beforeend', sourcesHtml);
        }

        this.scrollToBottom();

        if (!(signal && signal.aborted) && window.sidebarManager) {
            await window.sidebarManager.loadChats();
            try {
                const chatData = await chatAPI.getChat(this.currentChatId);
                this.currentChat = chatData.chat;
                this.chatTitle.textContent = chatData.chat.title;
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

        // Синхронизируем тоглер Full Document Mode
        if (this.fulldocCheckbox) {
            this.fulldocCheckbox.checked = Boolean(chat.full_document_mode_enabled);
        }

        // Update Mode button: показываем только для чатов с кампанией
        if (this.updateModeBtn) {
            const hasCampaign = Boolean(chat.campaign_id);
            this.updateModeBtn.classList.toggle('hidden', !hasCampaign);
        }

        if (!this.pipelineSelect) return;
        const pipelines = await chatAPI.getPipelines(chat.domain_id, chat.campaign_id || null);
        this.pipelineSelect.innerHTML = '<option value="">Авто</option>';

        const noneOpt = document.createElement('option');
        noneOpt.value = PIPELINE_NONE_ID;
        noneOpt.textContent = 'Без пайплайна';
        this.pipelineSelect.appendChild(noneOpt);

        for (const pipeline of (pipelines || []).filter(p => p.is_active)) {
            const option = document.createElement('option');
            option.value = pipeline.pipeline_id;
            option.textContent = pipeline.name;
            this.pipelineSelect.appendChild(option);
        }

        const lockedId = chat.locked_pipeline_id || '';

        let lockedOptionExists = false;
        if (lockedId) {
            for (const opt of this.pipelineSelect.options) {
                if (opt.value === lockedId) {
                    lockedOptionExists = true;
                    break;
                }
            }
        }

        if (lockedId && lockedId !== PIPELINE_NONE_ID && !lockedOptionExists) {
            const hiddenOpt = document.createElement('option');
            hiddenOpt.value = lockedId;
            hiddenOpt.textContent = lockedId;
            hiddenOpt.dataset.inactive = 'true';
            this.pipelineSelect.appendChild(hiddenOpt);
            lockedOptionExists = true;
        }

        const effectiveLocked = lockedId && lockedOptionExists ? lockedId : '';

        this.pipelineSelect.dataset.selectedPipelineId = effectiveLocked || '';
        this.pipelineSelect.value = effectiveLocked;
        this.pipelineSelect.disabled = Boolean(effectiveLocked);

        if (this.lockPipelineBtn) {
            this.lockPipelineBtn.classList.toggle('is-locked', Boolean(effectiveLocked));
            this.lockPipelineBtn.setAttribute('aria-label', effectiveLocked ? 'Разблокировать пайплайн' : 'Зафиксировать пайплайн');
            this.lockPipelineBtn.setAttribute('title', effectiveLocked ? 'Пайплайн зафиксирован. Нажмите, чтобы отменить.' : 'Нажмите, чтобы зафиксировать выбранный пайплайн');
            this.lockPipelineBtn.innerHTML = effectiveLocked === PIPELINE_NONE_ID
                ? `${LOCK_ICON_CLOSED}<span>Без пайплайна</span>`
                : effectiveLocked
                    ? `${LOCK_ICON_CLOSED}<span>Авто: выкл</span>`
                    : `${LOCK_ICON_OPEN}<span>Авто</span>`;
        }

        if (this.pendingBanner) {
            this.pendingBanner.setDomain(chat.domain_id || null);
        }
    }

    async togglePipelineLock() {
        if (!this.currentChatId || !this.pipelineSelect) return;

        const currentlyLocked = Boolean(this.currentChat?.locked_pipeline_id);
        const selectedPipelineId = this.pipelineSelect.value || null;

        if (!currentlyLocked && !selectedPipelineId) return;

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

    scheduleMarkdownRender(element, contentGetter) {
        if (this._renderScheduled || this._streamingDone) return;
        this._renderScheduled = true;
        requestAnimationFrame(() => {
            this._renderScheduled = false;
            if (this._streamingDone) return;
            const text = contentGetter();
            if (text) {
                this.renderAssistantMarkdown(element, text);
                this.scrollToBottom();
            }
        });
    }

    renderAssistantMarkdown(element, text) {
        const existingSources = element.querySelector('.sources-block');
        const sourcesHtml = existingSources ? existingSources.outerHTML : '';
        const prefix = Array.from(element.querySelectorAll('.pipeline-badge, .pipeline-progress'))
            .map(node => node.outerHTML).join('');
        element.innerHTML = prefix + renderMarkdown(text);
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
        this.messagesContainer.querySelectorAll(
            '.message, .typing-indicator, .pipeline-card, .pipeline-status-line, .fulldoc-panel, .um-panel'
        ).forEach(msg => msg.remove());
    }

    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    reset() {
        if (this.pendingBanner) {
            this.pendingBanner.destroy();
        }
        this.hideProcessingStatus();
        this.currentChatId = null;
        this.clearMessages();
        this.inputArea.style.display = 'none';
        this.welcomeMessage.style.display = 'block';
        this.chatTitle.textContent = 'Выберите чат или создайте новый';
        // Сбрасываем тоглер при сбросе
        if (this.fulldocCheckbox) this.fulldocCheckbox.checked = false;
        // Скрываем кнопку Update Mode
        if (this.updateModeBtn) this.updateModeBtn.classList.add('hidden');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (!window.chatAPI) {
        console.error('chatAPI not available — ChatManager will not initialize');
        return;
    }
    window.chatManager = new ChatManager();
});
