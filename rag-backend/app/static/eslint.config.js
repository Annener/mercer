import js from '@eslint/js';

export default [
    js.configs.recommended,
    {
        languageOptions: {
            ecmaVersion: 2024,
            sourceType: 'module',
            globals: {
                fetch: 'writable',
                window: 'readonly',
                document: 'readonly',
                console: 'readonly',
                globalThis: 'readonly',
            },
        },
        rules: {
            'no-unused-vars': 'warn',
            'no-undef': 'error',
            'eqeqeq': ['error', 'always'],
            'prefer-const': 'warn',
        },
    },
    {
        ignores: ['node_modules/**'],
    },
];
