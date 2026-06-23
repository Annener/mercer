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

// Специальное значение-сентинел для режима "Без пайплайна"
const PIPELINE_NONE_ID = '__none__';

// ============================================================
// Pipeline inline-карточки (Этап 10)
// ============================================================

/**
 * Рендерит карточку подтверждения запуска пайплайна.
 * Вставляется в ленту чата при получении SSE-чанка type=pipeline_confirm_required.
 *
 * @param {string} chatId
 * @param {string} pipelineName
 * @param {string} reasoning   — объяснение от роутера почему выбран пайплайн
 * @param {string} confirmToken
 * @param {Function} onStream  — (ReadableStream) => Promise<void> — обработчик ответного стрима
 * @returns {HTMLElement}
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
 * Вставляется при получении SSE-чанка type=validation_required.
 *
 * @param {string} chatId
 * @param {string} stepName    — имя validation-шага
 * @param {string} content     — validation_prompt для отображения пользователю
 * @param {string[]} options   — список вариантов ответа
 * @param {string} resumeToken
 * @param {Function} onStream  — (ReadableStream) => Promise<void>
 * @returns {HTMLElement}
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
        // Блокируем опции
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
            // Обновляем статус на ошибку, но карточка уже «done» — добавляем подпись
            const actionsEl = card.querySelector('.pipeline-card__actions');
            if (actionsEl) {
                actionsEl.innerHTML = `<span class="pipeline-card__status pipeline-card__status--error">Ошибка: ${escapeHtml(e.message)}</span>`;
            }
        }
    };

    // Клик по варианту ответа
    card.querySelectorAll('.pipeline-card__option').forEach(btn => {
        btn.addEventListener('click', () => {
            // Отмечаем выбранный
            card.querySelectorAll('.pipeline-card__option').forEach(b => b.classList.remove('is-selected'));
            btn.classList.add('is-selected');
            doResume(btn.dataset.value);
        });
    });

    // Кнопка «Продолжить» (без вариантов)
    card.querySelector('.pipeline-card__btn--confirm')?.addEventListener('click', () => {
        doResume(null);
    });

    // Кнопка отмены
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

// === Chat Manager ===
class ChatManager {
    constructor() {
        this.currentChatId = null;
        this.isStreaming = false;
        this._renderScheduled = false;
        this._streamingDone = false; // флаг: стрим завершён, RAF не должен перезаписывать
        this._abortController = null; // текущий AbortController для активной генерации
        // Значение настройки chat.stream_answers (по умолчанию true до загрузки).
        // Обновляется при инициализации и при каждом открытии чата.
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
        this.processingStatusEl = document.getElementById('processing-status');
        this.currentChat = null;
        this._lastUserMessage = null;
        this.initEventListeners();
        // Баннер pending-файлов (step-07)
        this.pendingBanner = new PendingFilesBanner('chat-banner-area');
        // Загружаем настройку стриминга при старте
        this._loadStreamSetting();
    }

    /**
     * Читает chat.stream_answers из /api/settings/params и кэширует в this._streamEnabled.
     * Тихо игнорирует ошибки — при недоступности API ос