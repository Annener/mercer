# Spec-06: Pipelines & Worlds UI

Перед выполнением прочитай `Spec-00-Architecture-Overview.md`, `Spec-05a` (API методы, sidebar кэш), `Spec-05b` (основной UI), `Spec-04c` (SSE‑события пайплайнов).

**Зависит от:** `Spec-05a` (`api.lockPipeline`, `api.getWorlds`, `api.toggleCampaign`, `api.getPipelines`), `Spec-04c` (SSE‑события).

**Цель:** Обновить основной чат-интерфейс: добавить выбор мира/кампаний в sidebar, прогресс‑бар выполнения пайплайна, отображение группированных источников, возможность зафиксировать pipeline для чата.

## Контекст

**Прочитать перед реализацией:**
- `rag-backend/static/js/sidebar.js` — текущий `SidebarManager`
- `rag-backend/static/js/chat.js` — `ChatManager`, SSE‑парсер, рендеринг сообщений
- `rag-backend/static/index.html` — разметка sidebar и области чата
- `rag-backend/static/css/chat.css` — стили

## Задачи

### 1. Обновить `js/sidebar.js`

**Добавить выбор мира и кампаний.**

После выбора домена (`selectDomain`) загрузить список vault'ов через `api.getSettingsVaults()`. Если есть хотя бы один vault, взять первый (или выбрать активный) и загрузить миры через `api.getWorlds(vaultId)`.

**HTML‑структура (добавить в sidebar):**

```html
<div class="world-selector" id="world-selector" style="display: none;">
    <div class="sidebar-section-label">Мир</div>
    <select id="world-select">
        <option value="">Без мира</option>
    </select>
    <div class="campaigns-list" id="campaigns-list"></div>
</div>
```

**Логика:**
- При выборе мира из `<select id="world-select">`:
  - Сохранить `this.currentWorldId` (значение `world_id` или пустую строку).
  - Загрузить кампании через `api.getWorldCampaigns(worldId)`.
  - Отрендерить список кампаний: каждая кампания — строка с названием, toggle‑кнопкой (Вкл/Выкл) и, возможно, индикатором активности.
  - При переключении toggle вызывать `api.toggleCampaign(worldId, campaignId)`.
- При создании нового чата (`createChat`) передавать `world_id: this.currentWorldId || null`.

**Кэширование:** сохранять выбранный мир в localStorage или в памяти менеджера, чтобы при перезагрузке страницы восстанавливать выбор (опционально, но желательно).

### 2. Обновить `js/chat.js`

#### 2.1 Исправить баг в `extractCitedIndices()`

Найти функцию `extractCitedIndices(text)` и исправить регулярное выражение:

```javascript
// Было (неправильно):
const regex = /[(\d+)]/g;

// Должно быть:
const regex = /\[(\d+)\]/g;
```

После исправления функция будет корректно извлекать числа из `[1]`, `[2]`, `[42]`.

#### 2.2 Расширить SSE‑парсер для поддержки нового формата

В методе `sendMessage` (или где обрабатывается стрим) парсить события.

**Алгоритм:**

```javascript
let streamDone = false;
for await (const chunk of response.body) {
    const lines = chunk.split('\n');
    for (const line of lines) {
        if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
                streamDone = true;
                continue;  // не break, чтобы не пропустить sources в том же чанке
            }
            try {
                const event = JSON.parse(data);
                if (event.type) {
                    // Новый формат (Pipeline)
                    switch (event.type) {
                        case 'pipeline_selected':
                            this.showPipelineBadge(event);
                            break;
                        case 'progress':
                            this.updateProgressBar(event.step, event.total, event.step_name);
                            break;
                        case 'step_done':
                            this.markStepDone(event.step);
                            break;
                        case 'token':
                            this.appendToken(event.content);
                            break;
                        case 'sources':
                            if (event.grouped_by_step) {
                                this.appendGroupedSources(event.step_groups);
                            } else {
                                this.appendSources(event.sources);
                            }
                            break;
                        case 'error':
                            this.showError(event.message);
                            break;
                    }
                } else {
                    // Старый формат (Planner)
                    if (event.token !== undefined) this.appendToken(event.token);
                    if (event.sources) this.appendSources(event.sources);
                }
            } catch (e) {
                console.warn('Failed to parse SSE event', e);
            }
        }
    }
}
if (streamDone) this.finalizeMessage();
```

**Методы, которые нужно добавить в `ChatManager`:**

- `showPipelineBadge(data)` — добавить в DOM сообщения бейдж с информацией о выбранном пайплайне (pipeline name, mode, reasoning).
- `updateProgressBar(step, total, stepName)` — рендерить прогресс‑бар (например, сегментированный индикатор выполнения с подписями шагов).
- `markStepDone(step)` — отметить шаг как выполненный (изменить цвет сегмента).
- `appendGroupedSources(stepGroups)` — отрендерить источники, сгруппированные по шагам (см. ниже).

#### 2.3 Реализовать `appendGroupedSources(stepGroups)`

Формат `stepGroups` описан в Spec-00 (раздел 7.1). Каждая группа имеет `step`, `step_name`, `sources`.

**HTML:**

```html
<div class="sources-grouped">
    <div class="sources-label">Источники по шагам</div>
    ${stepGroups.map(group => `
        <details class="sources-group" ${group.step === 1 ? 'open' : ''}>
            <summary>Шаг ${group.step}: ${group.step_name} (${group.sources.length} ист.)</summary>
            <div class="sources-list">
                ${group.sources.map(src => `
                    <div class="src-item">
                        <span class="src-path">${this.escapeHtml(src.path)}</span>
                        ${src.page ? `<span class="src-page">стр. ${src.page}</span>` : ''}
                        <span class="src-vault">${src.vault_id}</span>
                    </div>
                `).join('')}
            </div>
        </details>
    `).join('')}
</div>
```

**Санитизация:** использовать `escapeHtml` для `src.path` и `src.vault_id`.

#### 2.4 Добавить контекстную панель чата (Pipeline selection & lock)

**HTML (добавить в `index.html` над областью сообщений):**

```html
<div class="chat-context-bar hidden" id="chat-context-bar">
    <span class="context-world" id="context-world">
        🌍 <span id="world-name"></span>
    </span>
    <span class="context-divider">|</span>
    <span class="context-pipeline">
        Pipeline:
        <select id="pipeline-select">
            <option value="">Авто</option>
        </select>
        <button id="lock-pipeline-btn" class="btn-icon" title="Зафиксировать pipeline">🔓</button>
    </span>
</div>
```

**Логика в `ChatManager`:**

- При загрузке чата (`loadChat`) получить список активных пайплайнов для домена чата через `api.getPipelines(domainId)`.
- Заполнить `<select id="pipeline-select">` опциями: `""` → «Авто», остальные — `pipeline_id` / `name`.
- Если у чата есть `locked_pipeline_id` (поле из ответа `GET /chat/{id}`), выбрать соответствующий пайплайн в селекте, установить кнопку в состояние `🔒` (зафиксировано) и **заблокировать** селект (disabled).
- Если `locked_pipeline_id` нет — кнопка `🔓`, селект активен.

**Обработчики:**

- `change` на селекте: если выбран конкретный пайплайн (не "Авто"), показать кнопку `🔒` активной, иначе скрыть/сделать неактивной. При смене значения **не отправлять** запрос на сервер автоматически — только по клику на кнопку "зафиксировать".
- Клик на `#lock-pipeline-btn`:
  - Если текущее состояние «не зафиксировано» (селект выбран конкретный пайплайн) → вызвать `api.lockPipeline(chatId, selectedPipelineId)`. После успеха: установить `locked_pipeline_id` в локальном состоянии, сменить иконку на `🔒`, заблокировать селект.
  - Если состояние «зафиксировано» → вызвать `api.lockPipeline(chatId, null)`. После успеха: снять блокировку, иконка `🔓`, селект разблокирован.

**Отображение мира:**
- Если у чата есть `world_id`, показать блок `#chat-context-bar` и в `#world-name` отобразить название мира (получить из кэша sidebar или через отдельный запрос). Если мира нет — скрыть блок или не показывать иконку мира.

### 3. Обновить `index.html`

- Добавить контейнер для контекстной панели (как выше).
- Подключить обновлённые `chat.js` и `sidebar.js`.
- Убедиться, что элементы с id `world-selector`, `world-select`, `campaigns-list`, `chat-context-bar` присутствуют.

### 4. Обновить `css/chat.css`

Добавить стили:
- `.chat-context-bar` — горизонтальная панель, фон, отступы.
- `.pipeline-badge` — метка над сообщением ассистента.
- `.pipeline-progress` — контейнер прогресс‑бара (например, Flex с цветными блоками).
- `.sources-grouped`, `.sources-group`, `.sources-group summary` — стили для сворачиваемых групп.
- `.campaign-item` — элемент списка кампаний в sidebar (точка статуса, toggle switch).
- `.context-pipeline select:disabled` — стили для заблокированного селекта.

### 5. Обновить `js/db_management.js` (если использует устаревшие вызовы)

- Заменить хардкодные названия доменов на использование `window.sidebarManager.domainCache` (аналогично `formatDomainName`).

## Финальный контракт

- В sidebar можно выбрать мир и включить/выключить кампании.
- При создании нового чата выбранный мир передаётся в API.
- SSE‑парсер `chat.js` обрабатывает оба формата (старый и новый) и корректно рендерит группированные источники.
- Работает прогресс‑бар пайплайна и бейдж.
- Можно зафиксировать pipeline для чата (lock) через контекстную панель.

## Критерии приёмки

- [ ] После выбора домена в sidebar отображается блок выбора мира (если есть vault'ы).
- [ ] Выбор мира загружает список кампаний, toggle кампаний работает.
- [ ] При создании нового чата в запросе `POST /chat/create` присутствует `world_id` (если выбран).
- [ ] При загрузке чата с `world_id` контекстная панель показывает название мира.
- [ ] При загрузке чата с `locked_pipeline_id` селект заблокирован, иконка `🔒`, кнопка переключает на разблокировку.
- [ ] Без `locked_pipeline_id` кнопка фиксирует выбранный пайплайн, после чего селект блокируется.
- [ ] SSE‑события нового формата рендерят прогресс‑бар и группированные источники.
- [ ] SSE‑события старого формата продолжают работать (планировщик).
- [ ] Исправлен баг `extractCitedIndices` — цитаты `[1]`, `[2]` корректно выделяются.
- [ ] В консоли нет ошибок при переключении миров, отправке сообщений, фиксации пайплайнов.
