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
        return response.json();
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
     * B08 fix: POST /chat/{chatId}/clarify (C9)
     * Отправляет заполненные пользователем answers для уточняющего запроса.
     * answers: Record<string, string>  (ключ — название поля, значение — ответ пользователя)
     * Возвращает MessageResponse: { role, content, chat_id, message_id }
     */
    async submitClarification(chatId, answers) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/clarify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ answers }),
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
    async getDomains() {
        const response = await fetch(`${this.baseUrl}/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    }

    async getCampaigns(domainId) {
        const response = await fetch(`${this.baseUrl}/campaigns?domain_id=${encodeURIComponent(domainId)}`);
        if (!response.ok) throw new Error(`Failed to get campaigns: ${response.statusText}`);
        return response.json();
    }

    async getPipelines(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params.toString()}` : '';
        const response = await fetch(`${this.baseUrl}/pipelines${qs}`);
        if (!response.ok) throw new Error(`Failed to get pipelines: ${response.statusText}`);
        return response.json();
    }
}

// Глобальный синглтон API-клиента
window.chatAPI = new ChatAPI();
