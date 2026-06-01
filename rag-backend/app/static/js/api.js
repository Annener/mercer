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

    // D10 fix: было return response.json() — DELETE возвращает 204 No Content, json() бросал SyntaxError
    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
        // 204 No Content — нет тела
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

    // S45-2 fix: /domains → /config/domains (CF1)
    async getDomains() {
        const response = await fetch(`${this.baseUrl}/config/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
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

    // === Settings: Campaigns API (S45–S51) ===

    // D08 fix: было ?domain_id=${domainId} — при null отправлялась строка "null" в URL
    async getCampaigns(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns${qs}`);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    // D09 fix: метод отсутствовал — TypeError при любом действии с кампанией
    async getCampaign(campaignId) {
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    async createCampaign(data) {
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    async updateCampaign(campaignId, data) {
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    // D09: deleteCampaign — 204 No Content, не вызываем .json()
    async deleteCampaign(campaignId) {
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'DELETE',
        });
        if (!r.ok) throw new Error(await r.text());
        // 204 No Content — нет тела
    }

    async getCampaignTags(campaignId) {
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    async createCampaignTag(campaignId, payload) {
        const r = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    // === Settings: Tags API (S36–S39) ===

    async getTags(domainId = null, vaultId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (vaultId) params.set('vault_id', vaultId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const r = await fetch(`${this.baseUrl}/api/settings/tags${qs}`);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
    }

    // D09: deleteTag — 204 No Content, не вызываем .json()
    async deleteTag(tagId) {
        const r = await fetch(`${this.baseUrl}/api/settings/tags/${tagId}`, {
            method: 'DELETE',
        });
        if (!r.ok) throw new Error(await r.text());
        // 204 No Content — нет тела
    }
}

// Глобальный синглтон API-клиента
window.chatAPI = new ChatAPI();
