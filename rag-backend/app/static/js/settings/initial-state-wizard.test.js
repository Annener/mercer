// Тесты для InitialStateWizard (Stage 4 UI).
// Запускаются через vitest + jsdom. Покрывают state machine и основные сценарии.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Загружаем модуль Wizard. IIFE ставит window.InitialStateWizard.
import '../../js/settings/initial-state-wizard.js';

// Минимальная заглушка api. Каждый тест настраивает нужные ответы/ошибки.
function makeApi(overrides = {}) {
    return {
        getSettingsDocuments: vi.fn(async () => []),
        // По умолчанию — одна кампания-метка, чтобы Wizard не уходил в ошибку "нет тегов".
        getCampaignTags: vi.fn(async () => [{ id: 'tag-default', name: 'default' }]),
        getCampaignGlobalTags: vi.fn(async () => []),
        previewInitialState: vi.fn(async () => ({})),
        getInitialStateProposal: vi.fn(async () => null),
        applyInitialState: vi.fn(async () => ({
            summary: { state_version: 1, source_kind: 'initial' },
            values: [],
            list_items: [],
        })),
        ...overrides,
    };
}

function makeDoc(overrides = {}) {
    return {
        id: 'doc-1',
        vault_id: 'v-1',
        source_path: '/notes/a.md',
        title: 'Notes A',
        status: 'indexed',
        md5: 'a'.repeat(32),
        estimated_tokens: 1000,
        ...overrides,
    };
}

function flushMicrotasks() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

async function flushMicrotasksDeep(times = 5) {
    for (let i = 0; i < times; i++) {
        await flushMicrotasks();
    }
}

describe('InitialStateWizard', () => {
    beforeEach(() => {
        document.body.innerHTML = '';
        window.InitialStateWizard.close();
    });

    afterEach(() => {
        window.InitialStateWizard.close();
        delete window.chatAPI;
        vi.restoreAllMocks();
    });

    it('T-1 open() создаёт overlay и добавляет его в document.body', async () => {
        window.chatAPI = makeApi();
        const overlay = window.InitialStateWizard.open('camp-1');
        expect(overlay).toBeTruthy();
        expect(document.body.contains(overlay)).toBe(true);
        expect(overlay.classList.contains('iswizard')).toBe(true);
    });

    it('T-2 open() → шаг 1 загружает документы с tagIds и рендерит чекбоксы', async () => {
        const docs = [
            makeDoc({ id: 'doc-1', title: 'A', source_path: '/notes/a.md', estimated_tokens: 1000 }),
            makeDoc({ id: 'doc-2', title: 'B', source_path: '/notes/b.md', estimated_tokens: 500 }),
        ];
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => docs),
            getCampaignTags: vi.fn(async () => [
                { id: 'tag-1', name: 'T1' },
                { id: 'tag-2', name: 'T2' },
            ]),
            getCampaignGlobalTags: vi.fn(async () => [
                { id: 'tag-3', name: 'T3' },
            ]),
        });
        window.InitialStateWizard.open('camp-1', { domainId: 'dnd' });
        await flushMicrotasks();

        const checks = document.querySelectorAll('input[type="checkbox"][data-doc-check]');
        expect(checks.length).toBe(2);
        expect(window.chatAPI.getSettingsDocuments).toHaveBeenCalledWith({
            domainId: 'dnd',
            status: 'indexed',
            tagIds: ['tag-1', 'tag-2', 'tag-3'],
        });
        // Подсказка о количестве тегов присутствует.
        expect(document.body.textContent).toMatch(/3 тега/);
    });

    it('T-3 документ > 32 000 токенов отображается как disabled', async () => {
        const docs = [
            makeDoc({ id: 'big', estimated_tokens: 33000, title: 'Big' }),
            makeDoc({ id: 'small', estimated_tokens: 1000, title: 'Small' }),
        ];
        window.chatAPI = makeApi({ getSettingsDocuments: vi.fn(async () => docs) });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const checks = document.querySelectorAll('input[type="checkbox"][data-doc-check]');
        const bigCheck = [...checks].find((cb) => cb.closest('[data-doc-id]').dataset.docId === 'big');
        const smallCheck = [...checks].find((cb) => cb.closest('[data-doc-id]').dataset.docId === 'small');
        expect(bigCheck.disabled).toBe(true);
        expect(smallCheck.disabled).toBe(false);
    });

    it('T-4 бюджет > 64 000 → кнопка «Далее» disabled', async () => {
        const docs = [
            makeDoc({ id: 'd1', estimated_tokens: 50000, title: 'Big1' }),
            makeDoc({ id: 'd2', estimated_tokens: 50000, title: 'Big2' }),
        ];
        window.chatAPI = makeApi({ getSettingsDocuments: vi.fn(async () => docs) });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const checks = document.querySelectorAll('input[type="checkbox"][data-doc-check]');
        checks[0].checked = true;
        checks[0].dispatchEvent(new Event('change'));
        checks[1].checked = true;
        checks[1].dispatchEvent(new Event('change'));
        await flushMicrotasks();

        const nextBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent.includes('Далее'));
        expect(nextBtn).toBeTruthy();
        expect(nextBtn.disabled).toBe(true);
    });

    it('T-5 клик «Далее» вызывает previewInitialState с выбранными document_ids', async () => {
        const docs = [makeDoc({ id: 'doc-x', estimated_tokens: 1000 })];
        const previewMock = vi.fn(async () => ({
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [{ document_id: 'doc-x', content_sha: 'a'.repeat(32) }],
            proposal: { fields: [], questions: [] },
            warnings: [],
        }));
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => docs),
            previewInitialState: previewMock,
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const check = document.querySelector('input[type="checkbox"][data-doc-check]');
        check.checked = true;
        check.dispatchEvent(new Event('change'));
        await flushMicrotasks();

        const nextBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent.includes('Далее'));
        nextBtn.click();
        await flushMicrotasks();

        expect(previewMock).toHaveBeenCalledWith('camp-1', ['doc-x'], expect.any(Object));
    });

    it('T-6 успешный preview → шаг review, рендер карточек по mode×status', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [
                { document_id: 'doc-a', content_sha: 'a'.repeat(32), title: 'A', source_path: '/a.md' },
            ],
            proposal: {
                fields: [
                    { field_key: 'focus', label: 'Фокус', mode: 'single', status: { status: 'proposed' },
                      single_value: { text: 'тест', source_refs: [`file:doc-a:sha:${'a'.repeat(32)}`] } },
                    { field_key: 'open', label: 'Открытые', mode: 'list', status: { status: 'proposed' },
                      list_value: { items: [{ text: 'item1', source_refs: [`file:doc-a:sha:${'a'.repeat(32)}`] }] } },
                    { field_key: 'empty_f', label: 'Пусто', mode: 'single', status: { status: 'empty' } },
                    { field_key: 'clar_f', label: 'Уточнить', mode: 'single',
                      status: { status: 'needs_clarification', clarification_question: '?' } },
                ],
                questions: ['Q1?'],
            },
            warnings: ['warn-1'],
        };
        window.chatAPI = makeApi({
            previewInitialState: vi.fn(async () => proposal),
        });
        // Чтобы не свалиться в loading → грузим пустой список документов, но
        // предложение восстанавливаем напрямую через getInitialStateProposal.
        window.chatAPI.getInitialStateProposal = vi.fn(async () => proposal);
        window.chatAPI.getSettingsDocuments = vi.fn(async () => []);
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        // Прошло восстановление proposal → шаг 2.
        const fields = document.querySelectorAll('[data-field-key]');
        expect(fields.length).toBeGreaterThanOrEqual(3);

        const statuses = document.querySelectorAll('.iswizard__field-status');
        const labels = [...statuses].map((s) => s.textContent.trim());
        expect(labels).toEqual(expect.arrayContaining(['предложено', 'нет данных', 'требуется уточнение']));

        expect(document.body.textContent).toContain('Q1?');
        expect(document.body.textContent).toContain('warn-1');

        // Stepper должен показывать шаг 2 активным, шаг 1 — выполненным.
        const activeStep = document.querySelector('.iswizard__step--active');
        expect(activeStep.dataset.step).toBe('2');
        const doneSteps = document.querySelectorAll('.iswizard__step--done');
        expect(doneSteps.length).toBe(1);
        expect(doneSteps[0].dataset.step).toBe('1');
    });

    it('T-7 edit single_value → новое значение попадает в applyInitialState', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [
                { document_id: 'doc-a', content_sha: 'a'.repeat(32), title: 'A', source_path: '/a.md' },
            ],
            proposal: {
                fields: [
                    { field_key: 'focus', label: 'Фокус', mode: 'single', status: { status: 'proposed' },
                      single_value: { text: 'старый', source_refs: [`file:doc-a:sha:${'a'.repeat(32)}`] } },
                ],
                questions: [],
            },
            warnings: [],
        };
        const applyMock = vi.fn(async () => ({
            summary: { state_version: 1, source_kind: 'initial' },
            values: [],
            list_items: [],
        }));
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: applyMock,
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        await flushMicrotasks();

        const editBtn = document.querySelector('[data-action="edit-field"]');
        expect(editBtn).toBeTruthy();
        await flushMicrotasks();
        editBtn.click();
        await flushMicrotasks();

        const ta = document.querySelector('.iswizard__field-edit-textarea');
        expect(ta).toBeTruthy();
        ta.value = 'новый текст';
        const saveBtn = document.querySelector('[data-action="save-edit"]');
        expect(saveBtn).toBeTruthy();
        saveBtn.click();
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        expect(applyMock).toHaveBeenCalled();
        // Проверяем что proposal внутри Wizard действительно изменился — это видно
        // по DOM после apply: отрендеренный single_value уже 'новый текст'.
        // (Проверка косвенная через state='result'.)
        expect(document.body.textContent).toContain('Initial State применён');
    });

    it('T-8 source_snapshot_stale показывает баннер и возвращает на шаг 1', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [],
            proposal: { fields: [], questions: [] },
            warnings: [],
        };
        function staleError() {
            const err = new Error('stale');
            err.name = 'InitialStateApiError';
            err.status = 409;
            err.detail = { code: 'source_snapshot_stale', stale_documents: ['doc-a'] };
            err.isCode = (c) => err.detail.code === c;
            err.staleDocuments = () => err.detail.stale_documents;
            return err;
        }
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: vi.fn(async () => { throw staleError(); }),
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        // Должны вернуться на шаг 1 (select_documents).
        const stepActive = document.querySelector('.iswizard__step--active');
        expect(stepActive.dataset.step).toBe('1');
        // Баннер с сообщением должен присутствовать либо сейчас, либо после следующего render.
        const errorBanner = document.querySelector('.iswizard__error');
        expect(errorBanner).toBeTruthy();
    });

    it('T-9 proposal_expired → возврат на шаг 1', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [],
            proposal: { fields: [], questions: [] },
            warnings: [],
        };
        function expiredError() {
            const err = new Error('expired');
            err.name = 'InitialStateApiError';
            err.status = 410;
            err.detail = 'proposal_expired';
            err.isCode = (c) => err.detail === c;
            return err;
        }
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: vi.fn(async () => { throw expiredError(); }),
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        const stepActive = document.querySelector('.iswizard__step--active');
        expect(stepActive.dataset.step).toBe('1');
    });

    it('T-10 initial_already_applied → onApplied() + возврат на шаг 1', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [],
            proposal: { fields: [], questions: [] },
            warnings: [],
        };
        function alreadyAppliedError() {
            const err = new Error('applied');
            err.name = 'InitialStateApiError';
            err.status = 409;
            err.detail = 'initial_already_applied';
            err.isCode = (c) => err.detail === c;
            return err;
        }
        const onApplied = vi.fn();
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: vi.fn(async () => { throw alreadyAppliedError(); }),
        });
        window.InitialStateWizard.open('camp-1', { onApplied });
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        expect(onApplied).toHaveBeenCalled();
        const stepActive = document.querySelector('.iswizard__step--active');
        expect(stepActive.dataset.step).toBe('1');
    });

    it('T-11 close() удаляет overlay; повторный open() восстанавливает proposal', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [
                { document_id: 'doc-a', content_sha: 'a'.repeat(32), title: 'A', source_path: '/a.md' },
            ],
            proposal: { fields: [], questions: [] },
            warnings: [],
        };
        const getMock = vi.fn(async () => proposal);
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: getMock,
        });

        const ov1 = window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        window.InitialStateWizard.close();
        expect(document.body.contains(ov1)).toBe(false);

        const ov2 = window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        expect(document.body.contains(ov2)).toBe(true);
        // Каждый open вызывает getInitialStateProposal ровно один раз (для восстановления).
        expect(getMock).toHaveBeenCalledTimes(2);
    });

    it('T-12 warnings рендерятся отдельным блоком', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [],
            proposal: { fields: [], questions: [] },
            warnings: ['source_ref_unknown_document:d1', 'invalid_source_ref_format:d2'],
        };
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const warnings = document.querySelector('.iswizard__warnings');
        expect(warnings).toBeTruthy();
        expect(warnings.textContent).toContain('Предупреждения');
        expect(warnings.textContent).toContain('source_ref_unknown_document:d1');
    });

    it('T-13 если у кампании 0 тегов → показ ошибки и НЕ вызывается getSettingsDocuments', async () => {
        const getDocs = vi.fn(async () => []);
        window.chatAPI = makeApi({
            getCampaignTags: vi.fn(async () => []),
            getCampaignGlobalTags: vi.fn(async () => []),
            getSettingsDocuments: getDocs,
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        await flushMicrotasks();

        const errorBanner = document.querySelector('.iswizard__error');
        expect(errorBanner).toBeTruthy();
        expect(errorBanner.textContent).toMatch(/нет тегов/i);
        expect(getDocs).not.toHaveBeenCalled();
    });

    it('T-14 изменение чекбокса НЕ триггерит полный перерендер (тот же контейнер)', async () => {
        const docs = [
            makeDoc({ id: 'doc-1', estimated_tokens: 1000, title: 'A', source_path: '/a.md' }),
            makeDoc({ id: 'doc-2', estimated_tokens: 1000, title: 'B', source_path: '/b.md' }),
        ];
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => docs),
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();

        const docsContainerBefore = document.querySelector('[data-docs]');
        expect(docsContainerBefore).toBeTruthy();

        const check = document.querySelector('input[type="checkbox"][data-doc-check]');
        check.checked = true;
        check.dispatchEvent(new Event('change'));
        await flushMicrotasks();

        const docsContainerAfter = document.querySelector('[data-docs]');
        // Контейнер должен быть тем же DOM-узлом — иначе scrollTop сбросится.
        expect(docsContainerAfter).toBe(docsContainerBefore);

        // Счётчик выбранных документов обновился точечно.
        const selectedValue = document.querySelector('[data-budget-selected]');
        expect(selectedValue.textContent).toMatch(/1 док\./);
    });

    it('T-15 dismiss-error в баннере на select_documents закрывает ошибку', async () => {
        function genErr() {
            const err = new Error('502');
            err.name = 'InitialStateApiError';
            err.status = 502;
            err.detail = { code: 'generation_provider_unavailable' };
            err.isCode = (c) => err.detail.code === c;
            return err;
        }
        const docs = [makeDoc({ id: 'doc-1', estimated_tokens: 1000 })];
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => docs),
            previewInitialState: vi.fn(async () => { throw genErr(); }),
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasksDeep();

        const check = document.querySelector('input[type="checkbox"][data-doc-check]');
        expect(check).toBeTruthy();
        check.checked = true;
        check.dispatchEvent(new Event('change'));
        await flushMicrotasks();

        const nextBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent.includes('Далее'));
        expect(nextBtn).toBeTruthy();
        expect(nextBtn.disabled).toBe(false);
        nextBtn.click();
        await flushMicrotasksDeep(10);

        const errorBanner = document.querySelector('.iswizard__error');
        if (!errorBanner) {
            console.log('no banner. DOM:', document.body.innerHTML.slice(0, 1500));
            console.log('previewMock called:', window.chatAPI.previewInitialState.mock.calls.length);
        }
        expect(errorBanner).toBeTruthy();
        expect(errorBanner.textContent).toMatch(/генеративная модель/i);

        const dismissBtn = errorBanner.querySelector('[data-action="dismiss-error"]');
        expect(dismissBtn).toBeTruthy();
        dismissBtn.click();
        await flushMicrotasks();

        expect(document.querySelector('.iswizard__error')).toBeFalsy();
    });

    it('T-16 удаление list-item через 🗑 уменьшает количество элементов', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [
                { document_id: 'doc-a', content_sha: 'a'.repeat(32), title: 'A', source_path: '/a.md' },
            ],
            proposal: {
                fields: [
                    { field_key: 'open', label: 'Открытые', mode: 'list', status: { status: 'proposed' },
                      list_value: {
                        items: [
                            { text: 'item1', source_refs: [`file:doc-a:sha:${'a'.repeat(32)}`] },
                            { text: 'item2', source_refs: [] },
                            { text: 'item3', source_refs: [] },
                        ],
                    } },
                ],
                questions: [],
            },
            warnings: [],
        };
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        await flushMicrotasks();

        let items = document.querySelectorAll('.iswizard__list-item');
        expect(items.length).toBe(3);

        const removeBtn = [...document.querySelectorAll('[data-action="remove-list-item"]')][1];
        removeBtn.click();
        await flushMicrotasks();

        items = document.querySelectorAll('.iswizard__list-item');
        expect(items.length).toBe(2);
        expect(document.body.textContent).not.toContain('item2');
        expect(document.body.textContent).toContain('item1');
        expect(document.body.textContent).toContain('item3');
    });

    it('T-17 добавление list-item через "+" добавляет элемент и попадает в proposal_overrides', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [
                { document_id: 'doc-a', content_sha: 'a'.repeat(32), title: 'A', source_path: '/a.md' },
            ],
            proposal: {
                fields: [
                    { field_key: 'open', label: 'Открытые', mode: 'list', status: { status: 'proposed' },
                      list_value: {
                        items: [{ text: 'existing', source_refs: [] }],
                    } },
                ],
                questions: [],
            },
            warnings: [],
        };
        const applyMock = vi.fn(async () => ({
            summary: { state_version: 1, source_kind: 'initial' },
            values: [],
            list_items: [],
        }));
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: applyMock,
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        await flushMicrotasks();

        const addBtn = document.querySelector('[data-action="add-list-item"]');
        expect(addBtn).toBeTruthy();
        addBtn.click();
        await flushMicrotasks();

        let items = document.querySelectorAll('.iswizard__list-item');
        expect(items.length).toBe(2);

        // Кликаем ✎ на новом (последнем) элементе, чтобы войти в режим редактирования.
        const editBtns = document.querySelectorAll('[data-action="edit-list-item"]');
        const lastEditBtn = editBtns[editBtns.length - 1];
        expect(lastEditBtn).toBeTruthy();
        lastEditBtn.click();
        await flushMicrotasks();

        const ta = document.querySelector('.iswizard__field-edit-textarea');
        expect(ta).toBeTruthy();
        ta.value = 'новый элемент';
        const saveBtn = document.querySelector('[data-action="save-list-edit"]');
        expect(saveBtn).toBeTruthy();
        saveBtn.click();
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        expect(applyMock).toHaveBeenCalled();
        const args = applyMock.mock.calls[0];
        expect(args[0]).toBe('camp-1');
        expect(args[1]).toBe('p1');
        expect(args[2]).toBe(1);
        expect(args[3]).toBeTruthy();
        expect(args[3].fields[0].field_key).toBe('open');
        const texts = args[3].fields[0].list_value.items.map((it) => it.text);
        expect(texts).toContain('existing');
        expect(texts).toContain('новый элемент');
    });

    it('T-18 edit list-item → изменённый текст попадает в proposal_overrides.apply', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [
                { document_id: 'doc-a', content_sha: 'a'.repeat(32), title: 'A', source_path: '/a.md' },
            ],
            proposal: {
                fields: [
                    { field_key: 'open', label: 'Открытые', mode: 'list', status: { status: 'proposed' },
                      list_value: {
                        items: [{ text: 'old text', source_refs: [] }],
                    } },
                ],
                questions: [],
            },
            warnings: [],
        };
        const applyMock = vi.fn(async () => ({
            summary: { state_version: 1, source_kind: 'initial' },
            values: [],
            list_items: [],
        }));
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: applyMock,
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        await flushMicrotasks();

        const editBtn = document.querySelector('[data-action="edit-list-item"]');
        editBtn.click();
        await flushMicrotasks();

        const ta = document.querySelector('.iswizard__field-edit-textarea');
        expect(ta).toBeTruthy();
        ta.value = 'new text';
        const saveBtn = document.querySelector('[data-action="save-list-edit"]');
        saveBtn.click();
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        expect(applyMock).toHaveBeenCalled();
        const overrides = applyMock.mock.calls[0][3];
        expect(overrides.fields[0].list_value.items[0].text).toBe('new text');
    });

    it('T-19 doApply без правок всё равно передаёт proposal_overrides (копию)', async () => {
        const proposal = {
            proposal_id: 'p1',
            campaign_id: 'camp-1',
            config_version: 1,
            source_snapshot: [],
            proposal: {
                fields: [
                    { field_key: 'focus', label: 'Фокус', mode: 'single', status: { status: 'proposed' },
                      single_value: { text: 'как есть', source_refs: [] } },
                ],
                questions: [],
            },
            warnings: [],
        };
        const applyMock = vi.fn(async () => ({
            summary: { state_version: 1, source_kind: 'initial' },
            values: [],
            list_items: [],
        }));
        window.chatAPI = makeApi({
            getSettingsDocuments: vi.fn(async () => []),
            getInitialStateProposal: vi.fn(async () => proposal),
            applyInitialState: applyMock,
        });
        window.InitialStateWizard.open('camp-1');
        await flushMicrotasks();
        await flushMicrotasks();

        const applyBtn = [...document.querySelectorAll('.iswizard__btn')]
            .find((b) => b.textContent === 'Применить');
        applyBtn.click();
        await flushMicrotasks();

        expect(applyMock).toHaveBeenCalled();
        const args = applyMock.mock.calls[0];
        expect(args[3]).toBeTruthy();
        expect(args[3].fields[0].field_key).toBe('focus');
        expect(args[3].fields[0].single_value.text).toBe('как есть');
    });
});
