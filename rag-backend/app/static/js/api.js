// API клиент для работы с backend
class ChatAPI {
    constructor() {
        this.baseUrl = '';
    }

    // === Chat API ===

    async createChat(domainId = null, campaignId = null) {
        const response = await fetch(`${this.baseUrl}/chat/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, campaign_id: campaignId }),
        });
        if (!response.ok) throw new Error(`Failed to create chat: ${response.statusText}`);
        return response.json();
    }

    async listChats(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/chat/list${qs}`);
        if (!response.ok) throw new Error(`Failed to list chats: ${response.statusText}`);
        return response.json();
    }

    async getChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/history`);
        if (!response.ok) throw new Error(`Failed to get chat: ${response.statusText}`);
        return response.json();
    }

    // Алиас для getChat — используется в новом коде
    async getChatHistory(chatId) {
        return this.getChat(chatId);
    }

    async renameChat(chatId, title) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        if (!response.ok) throw new Error(`Failed to rename chat: ${response.statusText}`);
        return response.json();
    }

    // Алиас для renameChat через PUT (новый роут /chat/{id}/title)
    async updateChatTitle(chatId, title) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/title`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        if (!response.ok) {
            // Fallback на старый роут если новый не существует
            return this.renameChat(chatId, title);
        }
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
        // 204 No Content — не вызываем .json()
    }

    async lockPipeline(chatId, pipelineId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/lock_pipeline`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline_id: pipelineId }),
        });
        if (!response.ok) throw new Error(`Failed to lock pipeline: ${response.statusText}`);
        return response.json();
    }

    /**
     * Сохраняет частичный (прерванный) диалог в историю чата.
     * Вызывается фронтом после abort(), если накоплен fullContent.
     * @param {string} chatId
     * @param {string} userContent   — текст вопроса пользователя
     * @param {string} assistantContent — накопленный частичный ответ
     */
    async savePartialMessage(chatId, userContent, assistantContent) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/save_partial`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_content: userContent,
                assistant_content: assistantContent,
            }),
        });
        // Не бросаем исключение при ошибке — это best-effort сохранение
        if (!response.ok) {
            console.warn('savePartialMessage failed:', response.status, response.statusText);
        }
        return response.ok;
    }

    /**
     * @param {string} chatId
     * @param {string} content
     * @param {boolean} stream
     * @param {AbortSignal|null} signal — опциональный сигнал для прерывания запроса
     */
    async sendMessage(chatId, content, stream = true, signal = null) {
        const url = stream
            ? `${this.baseUrl}/chat/${chatId}/send_stream`
            : `${this.baseUrl}/chat/${chatId}/send`;
        // C25-A fix: при stream=true добавляем stream:true в body (SendMessageRequest требует это поле)
        const body = stream ? { content, stream: true } : { content };
        const fetchOptions = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        };
        if (signal) fetchOptions.signal = signal;
        const response = await fetch(url, fetchOptions);
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) { /* ignore */ }
            const err = new Error(errMsg);
            err.status = response.status;
            throw err;
        }
        if (stream) return response.body;
        return response.json();
    }

    async submitClarification(chatId, clarificationId, answers) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/clarify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ clarification_id: clarificationId, answers }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) { /* ignore */ }
            throw new Error(errMsg);
        }
        return response.json();
    }

    // Clarification FSM (новые методы)
    async getClarificationState(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/clarification`);
        if (!response.ok) throw new Error(`Failed to get clarification state: ${response.statusText}`);
        return response.json();
    }

    async updateClarificationState(chatId, data) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/clarification`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update clarification state: ${response.statusText}`);
        return response.json();
    }

    // === Pipeline confirm / resume (Этап 10) ===

    /**
     * POST /chat/{chatId}/pipeline_confirm
     * action: 'confirm' | 'cancel'
     * confirmToken: строка из SSE-чанка pipeline_confirm_required
     *
     * fix: бэк ожидает {confirm_token, confirmed: bool}, не {confirm_token, action}
     */
    async pipelineConfirm(chatId, confirmToken, action) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/pipeline_confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                confirm_token: confirmToken,
                confirmed: action === 'confirm',
            }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) { /* ignore */ }
            throw new Error(errMsg);
        }
        // Ответ может быть StreamingResponse (SSE) или JSON в зависимости от бэка
        const ct = response.headers.get('content-type') || '';
        if (ct.includes('text/event-stream')) return response.body;
        return response.json();
    }

    /**
     * POST /chat/{chatId}/pipeline_resume
     * action: 'resume' | 'cancel'
     * resumeToken: строка из SSE-чанка validation_required
     * feedback: выбранная пользователем опция (только для action='resume')
     *
     * fix: бэк ожидает {resume_token, cancelled: bool, user_feedback}, не {resume_token, action, feedback}
     */
    async pipelineResume(chatId, resumeToken, action, feedback = null) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/pipeline_resume`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                resume_token: resumeToken,
                cancelled: action === 'cancel',
                user_feedback: feedback ?? null,
            }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) { /* ignore */ }
            throw new Error(errMsg);
        }
        const ct = response.headers.get('content-type') || '';
        if (ct.includes('text/event-stream')) return response.body;
        return response.json();
    }

    // === Domain / Campaign / Pipeline API ===

    async getDomains() {
        const response = await fetch(`${this.baseUrl}/config/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    }

    async getCampaigns(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns${qs}`);
        if (!response.ok) throw new Error(`Failed to get campaigns: ${response.statusText}`);
        return response.json();
    }

    async getCampaign(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`);
        if (!response.ok) throw new Error(`Failed to get campaign: ${response.statusText}`);
        return response.json();
    }

    async createCampaign(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create campaign: ${response.statusText}`);
        return response.json();
    }

    async updateCampaign(campaignId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update campaign: ${response.statusText}`);
        return response.json();
    }

    async deleteCampaign(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete campaign: ${response.statusText}`);
        // 204 No Content
    }

    async getCampaignTags(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`);
        if (!response.ok) throw new Error(`Failed to get campaign tags: ${response.statusText}`);
        return response.json();
    }

    async createCampaignTag(campaignId, payload) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed to create campaign tag: ${response.statusText}`);
        return response.json();
    }

    // Новые методы global-tags для кампаний
    async getCampaignGlobalTags(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/global-tags`);
        if (!response.ok) throw new Error(`Failed to get campaign global tags: ${response.statusText}`);
        return response.json();
    }

    async linkCampaignGlobalTag(campaignId, tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/global-tags/${tagId}`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to link global tag: ${response.statusText}`);
        return response.json();
    }

    async unlinkCampaignGlobalTag(campaignId, tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/global-tags/${tagId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to unlink global tag: ${response.statusText}`);
    }

    async getTags(domainId = null, vaultId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (vaultId) params.set('vault_id', vaultId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/tags${qs}`);
        if (!response.ok) throw new Error(`Failed to get tags: ${response.statusText}`);
        return response.json();
    }

    async deleteTag(tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags/${tagId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete tag: ${response.statusText}`);
        // 204 No Content
    }

    async createTag(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create tag: ${response.statusText}`);
        return response.json();
    }

    async updateTag(tagId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags/${tagId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update tag: ${response.statusText}`);
        return response.json();
    }

    // === Pipelines ===

    async getPipelines(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines${qs}`);
        if (!response.ok) throw new Error(`Failed to get pipelines: ${response.statusText}`);
        return response.json();
    }

    // Новый метод: получить один pipeline по id
    async getPipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${encodeURIComponent(pipelineId)}`);
        if (!response.ok) throw new Error(`Failed to get pipeline: ${response.statusText}`);
        return response.json();
    }

    async createPipeline(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create pipeline: ${response.statusText}`);
        return response.json();
    }

    async updatePipeline(pipelineId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${encodeURIComponent(pipelineId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update pipeline: ${response.statusText}`);
        return response.json();
    }

    async activatePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${encodeURIComponent(pipelineId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate pipeline: ${response.statusText}`);
        return response.json();
    }

    async deactivatePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${encodeURIComponent(pipelineId)}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate pipeline: ${response.statusText}`);
        return response.json();
    }

    async deletePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${encodeURIComponent(pipelineId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete pipeline: ${response.statusText}`);
        // 204 No Content
    }

    // === Settings: status + params ===

    async getSettingsStatus() {
        const response = await fetch(`${this.baseUrl}/api/settings/status`);
        if (!response.ok) throw new Error(`Failed to get status: ${response.statusText}`);
        return response.json();
    }

    async getSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/params`);
        if (!response.ok) throw new Error(`Failed to get params: ${response.statusText}`);
        return response.json();
    }

    async updateSettingsParam(key, value) {
        const response = await fetch(`${this.baseUrl}/api/settings/params/${key}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
        if (!response.ok) throw new Error(`Failed to update param: ${response.statusText}`);
        return response.json();
    }

    async resetSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/reset`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reset params: ${response.statusText}`);
        return response.json();
    }

    // Новые методы конфига
    async getConfig() {
        const response = await fetch(`${this.baseUrl}/api/settings/config`);
        if (!response.ok) throw new Error(`Failed to get config: ${response.statusText}`);
        return response.json();
    }

    async updateConfig(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update config: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Domains CRUD ===

    async getSettingsDomains() {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    }

    // Новый метод: получить один домен по id
    async getDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}`);
        if (!response.ok) throw new Error(`Failed to get domain: ${response.statusText}`);
        return response.json();
    }

    async createDomain(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create domain: ${response.statusText}`);
        return response.json();
    }

    async updateDomain(domainId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update domain: ${response.statusText}`);
        return response.json();
    }

    async deleteDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete domain: ${response.statusText}`);
        // 204 No Content
    }

    async getDomainPrompts(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}/prompts`);
        if (!response.ok) throw new Error(`Failed to get prompts: ${response.statusText}`);
        return response.json();
    }

    async updateDomainPrompt(domainId, promptType, content) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}/prompts/${promptType}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            }
        );
        if (!response.ok) throw new Error(`Failed to update prompt: ${response.statusText}`);
        return response.json();
    }

    async getDomainFields(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}/fields`);
        if (!response.ok) throw new Error(`Failed to get fields: ${response.statusText}`);
        return response.json();
    }

    async updateDomainFields(domainId, fields) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}/fields`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(fields),
            }
        );
        if (!response.ok) throw new Error(`Failed to update fields: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Vaults CRUD ===

    async getSettingsVaults(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/vaults${qs}`);
        if (!response.ok) throw new Error(`Failed to get vaults: ${response.statusText}`);
        return response.json();
    }

    // Алиас без суффикса Settings (используется в новом коде)
    async getVaults(domainId = null) {
        return this.getSettingsVaults(domainId);
    }

    // Новый метод: получить один vault по id
    async getVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${encodeURIComponent(vaultId)}`);
        if (!response.ok) throw new Error(`Failed to get vault: ${response.statusText}`);
        return response.json();
    }

    async createVault(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create vault: ${response.statusText}`);
        return response.json();
    }

    async updateVault(vaultId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${encodeURIComponent(vaultId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update vault: ${response.statusText}`);
        return response.json();
    }

    async deleteVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${encodeURIComponent(vaultId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete vault: ${response.statusText}`);
        // 204 No Content
    }

    async toggleVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${encodeURIComponent(vaultId)}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle vault: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Generation Models CRUD ===

    async getGenerationModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation`);
        if (!response.ok) throw new Error(`Failed to get generation models: ${response.statusText}`);
        return response.json();
    }

    async createGenerationModel(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create generation model: ${response.statusText}`);
        return response.json();
    }

    async updateGenerationModel(modelId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update generation model: ${response.statusText}`);
        return response.json();
    }

    async deleteGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete generation model: ${response.statusText}`);
        // 204 No Content
    }

    async setActiveGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate generation model: ${response.statusText}`);
        return response.json();
    }

    async toggleGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle generation model: ${response.statusText}`);
        return response.json();
    }

    async checkGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check generation model: ${response.statusText}`);
        return response.json();
    }

    // Новые методы моделей (унифицированный API)
    async getModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models`);
        if (!response.ok) throw new Error(`Failed to get models: ${response.statusText}`);
        return response.json();
    }

    async getActiveModel() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/active`);
        if (!response.ok) throw new Error(`Failed to get active model: ${response.statusText}`);
        return response.json();
    }

    async setActiveModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/active`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
        if (!response.ok) throw new Error(`Failed to set active model: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Embedding Models CRUD ===
    // S19-A: setActiveEmbeddingModel удалён — роута нет, концепция неприменима (оригинал).
    // Восстановлен в виде нового унифицированного API (/api/settings/embedding-models/active).

    async getEmbeddingModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding`);
        if (!response.ok) throw new Error(`Failed to get embedding models: ${response.statusText}`);
        return response.json();
    }

    async createEmbeddingModel(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create embedding model: ${response.statusText}`);
        return response.json();
    }

    async updateEmbeddingModel(modelId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update embedding model: ${response.statusText}`);
        return response.json();
    }

    async deleteEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete embedding model: ${response.statusText}`);
        // 204 No Content
    }

    async checkEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check embedding model: ${response.statusText}`);
        return response.json();
    }

    // Новые методы embedding models (унифицированный API)
    async getActiveEmbeddingModel() {
        const response = await fetch(`${this.baseUrl}/api/settings/embedding-models/active`);
        if (!response.ok) throw new Error(`Failed to get active embedding model: ${response.statusText}`);
        return response.json();
    }

    async setActiveEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/embedding-models/active`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
        if (!response.ok) throw new Error(`Failed to set active embedding model: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Rerank Models CRUD ===

    async getRerankModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank`);
        if (!response.ok) throw new Error(`Failed to get rerank models: ${response.statusText}`);
        return response.json();
    }

    async createRerankModel(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create rerank model: ${response.statusText}`);
        return response.json();
    }

    async updateRerankModel(modelId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update rerank model: ${response.statusText}`);
        return response.json();
    }

    async deleteRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete rerank model: ${response.statusText}`);
        // 204 No Content
    }

    async activateRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate rerank model: ${response.statusText}`);
        return response.json();
    }

    async deactivateRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate rerank model: ${response.statusText}`);
        return response.json();
    }

    async checkRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check rerank model: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Documents ===

    // S40-B fix: бэк: GET /api/settings/documents?vault_id=|domain_id=&status=&tag_id=
    // Один из vault_id / domain_id обязателен (иначе бэк вернёт 400).
    async getSettingsDocuments({ vaultId = null, domainId = null, status = null, tagId = null } = {}) {
        const params = new URLSearchParams();
        if (vaultId)  params.set('vault_id',  vaultId);
        if (domainId) params.set('domain_id', domainId);
        if (status)   params.set('status',    status);
        if (tagId)    params.set('tag_id',     tagId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents${qs}`);
        if (!response.ok) throw new Error(`Failed to get settings documents: ${response.statusText}`);
        return response.json();
    }

    // S41-A fix: GET /api/settings/documents/{document_id} → DocumentRead
    async getSettingsDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}`);
        if (!response.ok) throw new Error(`Failed to get settings document: ${response.statusText}`);
        return response.json();
    }

    // Новые методы документов
    async uploadDocument(formData) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/upload`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) throw new Error(`Failed to upload document: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
        // 204 No Content
    }

    async reindexDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}/reindex`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reindex document: ${response.statusText}`);
        return response.json();
    }

    // DB Management: Documents

    // D1 fix: /api/db/documents?vault_id= (не /api/settings/documents?domain_id=)
    async getDocumentsByVault(vaultId, limit = 100, offset = 0, orderBy = 'document_id') {
        const params = new URLSearchParams({
            vault_id: vaultId,
            limit: String(limit),
            offset: String(offset),
            order_by: orderBy,
        });
        const response = await fetch(`${this.baseUrl}/api/db/documents?${params}`);
        if (!response.ok) throw new Error(`Failed to get documents: ${response.statusText}`);
        return response.json();
    }

    // D2 fix: DELETE /api/db/documents/{id}?vault_id=
    // Ответ — JSON (не 204!), бэк возвращает payload с deleted_count.
    async deleteDocumentById(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(`${this.baseUrl}/api/db/documents/${encodeURIComponent(documentId)}?${params}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
        return response.json(); // возвращает JSON, не 204
    }

    // D6 fix: PUT /api/settings/documents/{id}/labels
    // Full-replace семантика: удаляет все старые метки, вставляет новые. Возвращает DocumentRead (200).
    async updateDocumentLabels(documentId, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}/labels`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to update document labels: ${response.statusText}`);
        return response.json();
    }

    // S44-A fix: additive батч-назначение тегов
    async batchLabelDocuments(documentIds, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/labels/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ document_ids: documentIds, tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to batch label documents: ${response.statusText}`);
        // 204 No Content
    }

    // === Indexer ===

    // D3 fix: POST /vaults/{id}/reindex (не /api/settings/vaults/{id}/reindex)
    async runIndexer(vaultId = null, force = false) {
        if (!vaultId) {
            const vaults = await this.getSettingsVaults();
            const list = Array.isArray(vaults) ? vaults : (vaults.vaults || []);
            const active = list.find(v => v.enabled !== false) || list[0];
            vaultId = active ? (active.vault_id || active.id) : null;
        }
        if (!vaultId) throw new Error('Vault не найден — создайте vault перед запуском индексации');
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/reindex`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_reindex: force }),
        });
        if (!response.ok) throw new Error(`Failed to reindex vault: ${response.statusText}`);
        return response.json();
    }

    // D4 fix: WS /ws/index-tasks/{id}
    connectToTaskStream(taskId) {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${proto}://${location.host}/ws/index-tasks/${encodeURIComponent(taskId)}`;
        return new WebSocket(wsUrl);
    }

    // D5 fix: GET /index-tasks/{id}/state
    async getIndexTaskState(taskId) {
        const response = await fetch(`${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}/state`);
        if (!response.ok) throw new Error(`Failed to get task state: ${response.statusText}`);
        return response.json();
    }

    // D7 fix: POST /api/db/search/domain
    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/api/db/search/domain`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search by domain: ${response.statusText}`);
        return response.json();
    }

    // === Analytics ===

    async getAnalytics(domainId = null, startDate = null, endDate = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (startDate) params.set('start_date', startDate);
        if (endDate) params.set('end_date', endDate);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/analytics${qs}`);
        if (!response.ok) throw new Error(`Failed to get analytics: ${response.statusText}`);
        return response.json();
    }

    async getChatAnalytics(chatId) {
        const response = await fetch(`${this.baseUrl}/api/analytics/chat/${chatId}`);
        if (!response.ok) throw new Error(`Failed to get chat analytics: ${response.statusText}`);
        return response.json();
    }

    // === Health ===

    async getHealth() {
        const response = await fetch(`${this.baseUrl}/api/health`);
        if (!response.ok) throw new Error(`Health check failed: ${response.statusText}`);
        return response.json();
    }
}

// Глобальный синглтон API-клиента
window.chatAPI = new ChatAPI();
