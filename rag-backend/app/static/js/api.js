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

    async listChats(domainId = null) {
        const params = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/chat/list${params}`);
        if (!response.ok) throw new Error(`Failed to list chats: ${response.statusText}`);
        return response.json();
    }

    async getChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/history`);
        if (!response.ok) throw new Error(`Failed to get chat: ${response.statusText}`);
        return response.json();
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

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
        // D10 fix: 204 No Content — не вызываем .json()
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
     * POST /chat/{chatId}/send (или /send_stream)
     * stream=true → возвращает ReadableStream (SSE)
     * stream=false → возвращает JSON
     */
    async sendMessage(chatId, content, stream = true) {
        const url = stream
            ? `${this.baseUrl}/chat/${chatId}/send_stream`
            : `${this.baseUrl}/chat/${chatId}/send`;
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
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

    /**
     * C01 fix: POST /chat/{chatId}/clarify (C9)
     * ClarificationAnswer: { clarification_id: str, answers: Record<string, string> }
     * clarification_id обязателен — Pydantic возвращал 422 когда B08 отправлял только { answers }.
     * Возвращает ClarificationResponse: { message_id, role, content, clarification_id, stage }
     */
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

    // === Domain / Campaign / Pipeline API ===

    // S45-2 fix: /domains → /config/domains (CF1) — read-only для sidebar
    async getDomains() {
        const response = await fetch(`${this.baseUrl}/config/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    }

    // S45-2 fix: /campaigns → /api/settings/campaigns (S45)
    // D08 fix: domainId=null больше не отправляет ?domain_id=null (строку)
    async getCampaigns(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns${qs}`);
        if (!response.ok) throw new Error(`Failed to get campaigns: ${response.statusText}`);
        return response.json();
    }

    // D09 fix: getCampaign — отсутствовал, вызывался из tab-campaigns.js → TypeError
    async getCampaign(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`);
        if (!response.ok) throw new Error(`Failed to get campaign: ${response.statusText}`);
        return response.json();
    }

    // D09 fix: createCampaign — отсутствовал
    async createCampaign(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create campaign: ${response.statusText}`);
        return response.json();
    }

    // D09 fix: updateCampaign — отсутствовал
    async updateCampaign(campaignId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update campaign: ${response.statusText}`);
        return response.json();
    }

    // D09 fix: deleteCampaign — отсутствовал; D10 fix: нет .json() на 204
    async deleteCampaign(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete campaign: ${response.statusText}`);
        // 204 No Content — нет тела
    }

    // D09 fix: getCampaignTags — отсутствовал
    async getCampaignTags(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`);
        if (!response.ok) throw new Error(`Failed to get campaign tags: ${response.statusText}`);
        return response.json();
    }

    // D09 fix: createCampaignTag — отсутствовал
    async createCampaignTag(campaignId, payload) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed to create campaign tag: ${response.statusText}`);
        return response.json();
    }

    // D09 fix: getTags — отсутствовал (вызывался из showCampaignModal)
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

    // D09 fix: deleteTag — отсутствовал; D10 fix: нет .json() на 204
    async deleteTag(tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags/${tagId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete tag: ${response.statusText}`);
        // 204 No Content — нет тела
    }

    // S45-2 fix: /pipelines → /api/settings/pipelines (S30)
    async getPipelines(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines${qs}`);
        if (!response.ok) throw new Error(`Failed to get pipelines: ${response.statusText}`);
        return response.json();
    }

    // === Settings API ===

    // S1-A fix: getSettingsStatus — отсутствовал → TypeError на вкладке Status
    async getSettingsStatus() {
        const response = await fetch(`${this.baseUrl}/api/settings/status`);
        if (!response.ok) throw new Error(`Failed to get status: ${response.statusText}`);
        return response.json();
    }

    // S2-A fix: getSettingsParams — отсутствовал → TypeError на вкладке Params
    async getSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/params`);
        if (!response.ok) throw new Error(`Failed to get params: ${response.statusText}`);
        return response.json();
    }

    // S3-A fix: updateSettingsParam — отсутствовал
    // Ключ передаётся as-is (без encodeURIComponent) — FastAPI {key:path} принимает точки напрямую.
    async updateSettingsParam(key, value) {
        const response = await fetch(`${this.baseUrl}/api/settings/params/${key}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
        if (!response.ok) throw new Error(`Failed to update param: ${response.statusText}`);
        return response.json();
    }

    // S4-A fix: resetSettingsParams — отсутствовал
    async resetSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/reset`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reset params: ${response.statusText}`);
        return response.json();
    }

    // S5-B fix: getSettingsDomains — отдельный метод для CRUD в настройках
    // getDomains() остаётся для sidebar (/config/domains, read-only).
    async getSettingsDomains() {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    }

    // S5-B fix: createDomain — отсутствовал → TypeError в showDomainModal
    async createDomain(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create domain: ${response.statusText}`);
        return response.json();
    }

    // S5-B fix: updateDomain — отсутствовал → TypeError в showDomainModal
    async updateDomain(domainId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update domain: ${response.statusText}`);
        return response.json();
    }

    // S5-B fix: deleteDomain — отсутствовал; 204 No Content
    async deleteDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete domain: ${response.statusText}`);
        // 204 No Content — нет тела
    }

    // S10-A fix: getDomainPrompts — отсутствовал → TypeError в showPromptsModal
    async getDomainPrompts(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}/prompts`);
        if (!response.ok) throw new Error(`Failed to get prompts: ${response.statusText}`);
        return response.json();
    }

    // S10-A fix: updateDomainPrompt — отсутствовал → TypeError в showPromptsModal
    // PUT /api/settings/domains/{domain_id}/prompts/{prompt_type}  body: { content: str }
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

    // S12-A fix: getDomainFields — отсутствовал
    // GET /api/settings/domains/{domain_id}/fields → list[ClarificationField]
    async getDomainFields(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${encodeURIComponent(domainId)}/fields`);
        if (!response.ok) throw new Error(`Failed to get fields: ${response.statusText}`);
        return response.json();
    }

    // S12-A fix: updateDomainFields — отсутствовал
    // PUT /api/settings/domains/{domain_id}/fields  body: ClarificationFieldRequest[]
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
}

// Глобальный синглтон API-клиента
window.chatAPI = new ChatAPI();
