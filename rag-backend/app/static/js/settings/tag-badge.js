/**
 * tag-badge.js
 * ─────────────────────────────────────────────────────────────────────────
 * Единственная точка сборки HTML для тегов-бейджей во всём приложении.
 *
 * tagBadgeHtml(tag, opts?) → строка HTML
 *
 * tag: { id, name, color? }
 *
 * opts:
 *   context   'panel' | 'file' | 'modal' | 'dir' | 'campaign-own' | 'campaign-global'
 *             Определяет CSS-модификатор и поведение (размер, hover).
 *             По умолчанию: 'panel'.
 *
 *   active    true | false | null
 *             true  → тег назначен (непрозрачный, кликабельный для снятия)
 *             false → тег НЕ назначен (пониженная прозрачность, кликабельный для назначения)
 *             null  → состояние не применимо (просто показываем)
 *
 *   removable true → добавляет «×» и data-remove-tag атрибут
 *             Используется в campaign-own / campaign-global
 *
 *   dataAttrs объект { 'data-foo': 'bar', ... } — произвольные data-атрибуты
 *
 *   extraClass строка дополнительных CSS-классов
 */
function tagBadgeHtml(tag, opts = {}) {
    const {
        context    = 'panel',
        active     = null,
        removable  = false,
        dataAttrs  = {},
        extraClass = '',
    } = opts;

    const id    = String(tag.id);
    const name  = _escHtml(tag.name);
    const color = tag.color || 'var(--color-primary)';

    // ── CSS-классы ────────────────────────────────────────────────────────
    const classes = ['badge', `badge--${context}`];
    if (active === true)  classes.push('badge--active');
    if (active === false) classes.push('badge--inactive');
    if (removable)        classes.push('badge--removable');
    if (extraClass)       classes.push(extraClass);

    // ── Inline-стиль: только цвет фона и текста ──────────────────────────
    // Всё остальное (padding, font-size, cursor, opacity, transform, shadow)
    // задаётся в settings.css через классы.
    const style = `background:${color};color:${_textColor(color)};`;

    // ── Data-атрибуты ─────────────────────────────────────────────────────
    const dataStr = Object.entries(dataAttrs)
        .map(([k, v]) => `${k}="${_escHtml(String(v))}"`)
        .join(' ');

    // ── Содержимое ────────────────────────────────────────────────────────
    const label   = removable ? `${name} <span class="badge-x" aria-hidden="true">×</span>` : name;

    return `<span class="${classes.join(' ')}" style="${style}" data-tag-id="${id}" ${dataStr}>${label}</span>`;
}

/**
 * Определяет цвет текста (белый или тёмный) исходя из яркости фона.
 * Работает с hex (#rrggbb / #rgb) и CSS-переменными.
 * Для CSS-переменных всегда возвращает white — они обрабатываются в CSS.
 */
function _textColor(color) {
    if (!color || color.startsWith('var(')) return 'white';
    const hex = color.replace('#', '');
    const full = hex.length === 3
        ? hex.split('').map(c => c + c).join('')
        : hex;
    if (full.length !== 6) return 'white';
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    // WCAG luminance approximation
    const lum = 0.299 * r + 0.587 * g + 0.114 * b;
    return lum > 160 ? '#2c3e50' : 'white';
}

/** Минимальный HTML-эскейп для вставки в атрибуты и текст. */
function _escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
