# Spec-05a: Settings UI Foundation

Перед выполнением прочитай `Spec-00-Architecture-Overview.md` и убедись, что бэкенд API (`/settings/*`) полностью реализован (Spec-02b, 02c, 04c).

**Зависит от:** `Spec-02b` (API настроек), `Spec-02c` (API vault'ов, миров, пайплайнов), `Spec-04c` (API пайплайнов).

**Цель:** Создать базовую инфраструктуру страницы настроек в UI: добавить кнопку переключения, контейнер, статусную плашку, обновить `api.js` всеми необходимыми методами, создать каркас `settings.js`.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/static/index.html` — текущая разметка
- `rag-backend/static/js/api.js` — класс `ChatAPI`
- `rag-backend/static/js/sidebar.js` — существующий менеджер сайдбара
- `rag-backend/static/css/chat.css` — стили

## Задачи

### 1. Обновить `js/api.js`

Добавить все методы для работы с `/settings/*` эндпоинтами. **Особое внимание:** метод `lockPipeline(chatId, pipelineId)` обязателен для Spec-06.

**Полный список методов (все возвращают `Promise`):**

```javascript
// Status & params
getSettingsStatus()
getSettingsParams()
updateSettingsParam(key, value)
resetSettingsParams()

// Domains
getDomains()
createDomain(data)
updateDomain(id, data)
deleteDomain(id)
getDomainPrompts(id)
updateDomainPrompt(id, type, content)
getDomainFields(id)
updateDomainFields(id, fields)

// Generation models
getGenerationModels()
createGenerationModel(data)
updateGenerationModel(id, data)
deleteGenerationModel(id)
activateGenerationModel(id)
checkGenerationModel(id)

// Embedding models
getEmbeddingModels()
createEmbeddingModel(data)
updateEmbeddingModel(id, data)
deleteEmbeddingModel(id)
checkEmbeddingModel(id)

// Vaults
getSettingsVaults()
createVault(data)
updateVault(id, data)
deleteVault(id)
toggleVault(id)

// Worlds (без delete)
getWorlds(vaultId)
createWorld(data)
updateWorld(worldId, data)
getWorldCampaigns(worldId)
createCampaign(worldId, data)
updateCampaign(worldId, campaignId, data)
toggleCampaign(worldId, campaignId)

// Pipelines
getPipelines(domainId)
createPipeline(data)
updatePipeline(id, data)   // id = UUID строки
deletePipeline(id)         // soft delete
activatePipeline(id)

// Chat pipeline lock
lockPipeline(chatId, pipelineId)  // PUT /chat/{id}/pipeline
```

**Важно:** Методы `deleteWorld` и `deleteCampaign` **не создавать** — их нет в API.

### 2. Обновить `index.html`

**Добавить кнопку настроек** в шапку или sidebar (рядом с existing controls):

```html
<button id="settings-btn" class="btn-icon" title="Настройки платформы">⚙️</button>
```

**Добавить контейнер страницы настроек** (изначально скрыт):

```html
<div id="settings-page" class="hidden">
    <div class="settings-header">
        <h2>Настройки платформы</h2>
        <button id="back-to-chat-btn" class="btn-outline">← Назад к чатам</button>
    </div>
    <div class="settings-tabs">
        <button data-tab="domains">Домены</button>
        <button data-tab="vaults">Vault'ы</button>
        <button data-tab="gen-models">Генеративные модели</button>
        <button data-tab="emb-models">Embedding-модели</button>
        <button data-tab="params">Параметры</button>
        <button data-tab="pipelines">Pipelines</button>
        <button data-tab="worlds">Миры</button>
    </div>
    <div id="settings-content"></div>
</div>
```

**Добавить блок статусной плашки** над полем ввода чата:

```html
<div id="status-banner" class="hidden"></div>
```

**Подключить новый скрипт** после `api.js` и `sidebar.js`:

```html
<script src="/static/js/settings.js"></script>
```

### 3. Создать `js/settings.js`

Класс `SettingsManager`. Базовый каркас:

```javascript
class SettingsManager {
    constructor(api) {
        this.api = api;
        this.currentTab = 'domains';
        this.init();
    }

    async init() {
        this.attachEventListeners();
        await this.loadTab(this.currentTab);
        await this.updateStatusBanner();
    }

    attachEventListeners() {
        // Кнопка открытия настроек
        const settingsBtn = document.getElementById('settings-btn');
        settingsBtn?.addEventListener('click', () => this.show());

        // Кнопка назад
        const backBtn = document.getElementById('back-to-chat-btn');
        backBtn?.addEventListener('click', () => this.hide());

        // Вкладки
        document.querySelectorAll('.settings-tabs button').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                if (tab) this.loadTab(tab);
            });
        });
    }

    show() {
        document.getElementById('settings-page')?.classList.remove('hidden');
        document.querySelector('.chat-container')?.classList.add('hidden');
    }

    hide() {
        document.getElementById('settings-page')?.classList.add('hidden');
        document.querySelector('.chat-container')?.classList.remove('hidden');
        this.updateStatusBanner(); // обновить плашку после возврата
    }

    async loadTab(tabId) {
        this.currentTab = tabId;
        const container = document.getElementById('settings-content');
        if (!container) return;
        container.innerHTML = '<div class="loading">Загрузка...</div>';
        try {
            let html = '';
            switch(tabId) {
                case 'domains':
                    html = await this.renderDomainsTab();
                    break;
                case 'vaults':
                    html = await this.renderVaultsTab();
                    break;
                // остальные вкладки будут добавлены в 05b и 05c
                default:
                    html = '<div class="placeholder">Скоро будет реализовано</div>';
            }
            container.innerHTML = html;
            this.attachTabEventHandlers(tabId);
        } catch (err) {
            container.innerHTML = `<div class="error">Ошибка: ${err.message}</div>`;
        }
    }

    async updateStatusBanner() {
        try {
            const status = await this.api.getSettingsStatus();
            const banner = document.getElementById('status-banner');
            if (!banner) return;
            const messages = [];
            if (!status.has_active_generation_model) messages.push('🔴 Не настроена генеративная модель. Чат недоступен.');
            if (!status.has_active_embedding_model) messages.push('🟡 Не настроена embedding-модель. Индексация невозможна.');
            if (!status.has_vaults) messages.push('ℹ️ Создайте vault и добавьте документы для работы с RAG.');
            if (!status.pdf_sidecar_available) messages.push('ℹ️ PDF Sidecar недоступен. PDF будут обработаны через pdfminer.');
            if (messages.length > 0) {
                banner.innerHTML = messages.join('<br>');
                banner.classList.remove('hidden');
            } else {
                banner.classList.add('hidden');
            }
            // Блокировка поля ввода чата при отсутствии генеративной модели
            const chatInput = document.querySelector('.chat-input textarea');
            if (chatInput) {
                chatInput.disabled = !status.has_active_generation_model;
                if (!status.has_active_generation_model) chatInput.placeholder = 'Генеративная модель не настроена';
            }
        } catch (err) {
            console.error('Failed to update status banner', err);
        }
    }

    // Заглушки для рендеринга вкладок (будут реализованы в 05b)
    async renderDomainsTab() { return '<div>Domains tab</div>'; }
    async renderVaultsTab() { return '<div>Vaults tab</div>'; }
    async attachTabEventHandlers(tabId) {}
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    window.settingsManager = new SettingsManager(window.chatAPI);
});
```

### 4. Обновить `js/sidebar.js`

Добавить кэширование доменов для использования в `formatDomainName` (удалить хардкод). При загрузке приложения вызвать `api.getDomains()` и сохранить в `this.domainCache`.

```javascript
async loadDomains() {
    const domains = await this.api.getDomains();
    this.domainCache = {};
    for (const d of domains) {
        this.domainCache[d.domain_id] = d.display_name;
    }
    // ... остальная логика
}

formatDomainName(domainId) {
    if (domainId === 'default') return null; // не показывать
    return this.domainCache[domainId] || domainId.toUpperCase();
}
```

## Финальный контракт

- `api.js` содержит все методы для `settings/*` (включая `lockPipeline`).
- `index.html` имеет кнопку настроек, страницу settings, блок статусной плашки.
- `settings.js` создан, умеет показывать/скрывать страницу, переключать вкладки, обновлять статусную плашку.
- `sidebar.js` использует кэш доменов из API.
- После этого Spec UI настроек переключается, статусная плашка работает, поле ввода чата блокируется при отсутствии генеративной модели.

## Критерии приёмки

- [ ] Кнопка «Настройки» открывает страницу настроек, скрывая чат.
- [ ] Кнопка «Назад к чатам» возвращает чат.
- [ ] Вкладки переключаются без ошибок в консоли.
- [ ] Статусная плашка отображается при проблемах и скрывается, когда всё нормально.
- [ ] При `has_active_generation_model: false` поле ввода чата заблокировано.
- [ ] `api.lockPipeline` метод существует и вызывает `PUT /chat/{id}/pipeline`.
- [ ] `sidebar.formatDomainName` использует кэш из API, не хардкодит `dnd`/`work`.
