const SETTINGS_DEFAULTS = {
    'retrieval.enabled': true,
    'retrieval.top_k': 10,
    'retrieval.reranker_enabled': false,
    'chunking.chunk_size': 2000,
    'chunking.overlap': 64,
    'chunking.entity_aware_mode': true,
    'chat.max_clarification_turns': 3,
    'chat.stream_answers': true,
    'chat.auto_title': true,
    'reranker.enabled': false,
    'reranker.provider': null,
    'reranker.base_url': null,
    'reranker.model_name': null,
    'pdf_sidecar.url': 'http://host.docker.internal:8765',
    'pdf_sidecar.timeout_seconds': 180,
    'pdf_sidecar.fallback_to_pdfminer': true,
};

const ParamsTabMixin = {
    getParamType(key) {
        const boolKeys = [
            'retrieval.enabled',
            'retrieval.reranker_enabled',
            'reranker.enabled',
            'chat.stream_answers',
            'chat.auto_title',
            'chunking.entity_aware_mode',
            'pdf_sidecar.fallback_to_pdfminer',
        ];
        return boolKeys.includes(key) ? 'bool' : 'string';
    },

    async renderParamsTab() {
        const params = await this.api.getSettingsParams();
        const sortedKeys = Object.keys(params).sort();
        const descriptions = {
            'retrieval.enabled':                { label: 'RAG включён', desc: 'Включает поиск по базе знаний при ответе. Если выключить — ИИ отвечает только из своей памяти.' },
            'retrieval.top_k':                  { label: 'Top-K результатов', desc: 'Сколько фрагментов документов передавать ИИ при каждом запросе. Рекомендуется 5–15.' },
            'retrieval.reranker_enabled':       { label: 'Reranker включён', desc: 'Включает дополнительную модель переранжирования результатов поиска.' },
            'chunking.chunk_size':              { label: 'Размер чанка', desc: 'Максимальное количество символов в одном фрагменте документа при индексации. Рекомендуется 1000–3000.' },
            'chunking.overlap':                 { label: 'Перекрытие чанков', desc: 'Сколько символов повторяется между соседними чанками. Рекомендуется 32–128.' },
            'chunking.entity_aware_mode':       { label: 'Режим осведомлённости об объектах', desc: 'При нарезке учитывает границы сущностей (персонажи, места). Улучшает качество для D&D текстов.' },
            'chat.max_clarification_turns':     { label: 'Макс. уточняющих вопросов', desc: 'Сколько раз ИИ может переспросить перед ответом. 0 — отвечает сразу.' },
            'chat.stream_answers':              { label: 'Стриминг ответов', desc: 'Ответ появляется постепенно, слово за словом. Если выключить — появится весь сразу.' },
            'chat.auto_title':                  { label: 'Авто-название чата', desc: 'Автоматически придумывает название для нового чата.' },
            'reranker.enabled':                 { label: 'Reranker активен', desc: 'Глобальный переключатель reranker-модели.' },
            'reranker.provider':                { label: 'Провайдер reranker', desc: 'Тип сервиса reranker. Поддерживается: openai_compatible.' },
            'reranker.base_url':                { label: 'URL reranker API', desc: 'Адрес сервера reranker. Например: http://localhost:8080.' },
            'reranker.model_name':              { label: 'Модель reranker', desc: 'Название модели reranker на сервере.' },
            'pdf_sidecar.url':                  { label: 'URL PDF-Sidecar', desc: 'Адрес вспомогательного сервиса для извлечения текста из PDF. Например: http://host.docker.internal:8765.' },
            'pdf_sidecar.timeout_seconds':      { label: 'Таймаут PDF-Sidecar (сек)', desc: 'Сколько секунд ждать ответа от PDF-Sidecar.' },
            'pdf_sidecar.fallback_to_pdfminer': { label: 'Fallback на PDF-miner', desc: 'Если PDF-Sidecar недоступен — использовать встроенный pdfminer.' },
        };
        return `
            <div class="settings-toolbar">
                <button class="btn btn-secondary" data-action="reset-params">Сбросить все параметры</button>
            </div>
            <div class="settings-params-fullwidth">
                ${sortedKeys.map(key => {
                    const isBool = this.getParamType(key) === 'bool';
                    const currentValue = params[key];
                    const info = descriptions[key] || { label: key, desc: '' };
                    const inputHtml = isBool
                        ? `<input type="checkbox" data-param="${this.escapeHtml(key)}" ${(currentValue === true || currentValue === 'true') ? 'checked' : ''}>`
                        : `<input data-param="${this.escapeHtml(key)}" value="${this.escapeHtml(currentValue ?? '')}" style="width:100%; max-width:340px; box-sizing:border-box;">`;
                    return `
                        <div class="settings-param-row">
                            <div class="settings-param-info">
                                <strong>${this.escapeHtml(info.label)}</strong>
                                <span class="settings-param-desc">${this.escapeHtml(info.desc)}</span>
                                <span class="settings-param-key">${this.escapeHtml(key)}</span>
                            </div>
                            <div class="settings-param-control">
                                ${inputHtml}
                                <button class="btn btn-sm btn-primary" data-action="save-param" data-id="${this.escapeHtml(key)}">Сохранить</button>
                                <button class="btn btn-sm btn-secondary" data-action="default-param" data-id="${this.escapeHtml(key)}">По умолчанию</button>
                            </div>
                        </div>`;
                }).join('')}
            </div>`;
    },
};

Object.assign(SettingsManager.prototype, ParamsTabMixin);
