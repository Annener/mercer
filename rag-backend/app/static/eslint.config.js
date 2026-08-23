import js from '@eslint/js';

const browserGlobals = {
    URLSearchParams: 'readonly',
    AbortController: 'readonly',
    ReadableStream: 'readonly',
    TextDecoder: 'readonly',
    TextEncoder: 'readonly',
    Event: 'readonly',
    EventSource: 'readonly',
    MouseEvent: 'readonly',
    KeyboardEvent: 'readonly',
    CustomEvent: 'readonly',
    WebSocket: 'readonly',
    setTimeout: 'readonly',
    setInterval: 'readonly',
    clearInterval: 'readonly',
    clearTimeout: 'readonly',
    requestAnimationFrame: 'readonly',
    cancelAnimationFrame: 'readonly',
    alert: 'readonly',
    confirm: 'readonly',
    localStorage: 'readonly',
    sessionStorage: 'readonly',
    location: 'readonly',
    navigator: 'readonly',
    history: 'readonly',
    atob: 'readonly',
    btoa: 'readonly',
    FormData: 'readonly',
    Blob: 'readonly',
    File: 'readonly',
    URL: 'readonly',
    crypto: 'readonly',
};

const cdnLibraries = {
    marked: 'readonly',
    DOMPurify: 'readonly',
    hljs: 'readonly',
    vis: 'readonly',
};

const appGlobals = {
    chatAPI: 'writable',
    chatManager: 'writable',
    sidebarManager: 'writable',
    PendingFilesBanner: 'readonly',
    ChatManager: 'readonly',
    SidebarManager: 'readonly',
    SettingsManager: 'readonly',
    createUpdateModePanel: 'readonly',
    restoreUpdateModePanel: 'readonly',
    tagBadgeHtml: 'readonly',
    _textColor: 'readonly',
    _escHtml: 'readonly',
    InitialStateApiError: 'writable',
    InitialStateWizard: 'readonly',
    InitialStateSection: 'readonly',
    StateFieldsSection: 'readonly',
    DomainRail: 'readonly',
    PipelineBuilder: 'readonly',
    _campEditHelpers: 'writable',
};

export default [
    js.configs.recommended,
    {
        languageOptions: {
            ecmaVersion: 2024,
            sourceType: 'module',
            globals: {
                ...browserGlobals,
                ...cdnLibraries,
                ...appGlobals,
                fetch: 'writable',
                window: 'readonly',
                document: 'readonly',
                console: 'readonly',
                globalThis: 'readonly',
            },
        },
        rules: {
            'no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrors: 'none',
            }],
            'no-undef': 'error',
            'no-empty': ['error', { allowEmptyCatch: true }],
            'eqeqeq': ['error', 'always'],
            'prefer-const': 'warn',
        },
    },
    {
        ignores: ['node_modules/**'],
    },
];
