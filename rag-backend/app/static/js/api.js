// API клиент для работы с backend
class ChatAPI {
    constructor() {
        this.baseUrl = '';
    }

    // === Chat API ===
    async createChat(domainId = null, campaignId = null) {
        // vault_id больше не передаётся — привязка перешла на domain_id
        const response = await fetch(`${this.baseUrl}/chat/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, campaign_id: campaignId }),
        });
        if (!response.ok) throw new Error(`Failed to create chat: ${response.statusText}`);
        return response.json();
    }

    async listChats(domainId = null) {
        const url = new URL(`${this.baseUrl}/chat/list`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        const response = await fetch(url.toString());
        if (!response.ok) throw new Error(`Failed to list chats: ${response.statusText}`);
        return response.json();
    }

    // FIX: бэкенд отдаёт {chat, messages} только на /chat/{id}/history, а не на /chat/{id}
    async getChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/history`);
        if (!response.ok) throw new Error(`Failed to get chat: ${response.statusText}`);
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
        return null; // 204 No Content
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

    // FIX: эндпоинт /chat/{id}/message не существует.
    //   stream=true  → POST /chat/{id}/send_stream (SSE, text/event-stream)
    //   stream=false → POST /chat/{id}/send        (JSON)
    // SendMessageRequest принимает только { content }, параметра stream нет.
    async sendMessage(chatId, content, stream = true) {
        const endpoint = stream
            ? `${this.baseUrl}/chat/${chatId}/send_stream`
            : `${this.baseUrl}/chat/${chatId}/send`;
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Failed to send message: ${response.statusText}`);
        }
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('text/event-stream')) {
            return response.body;
        }
        return response.json();
    }

    // FIX: метод был PUT /chat/{id}/pipeline, бэкенд ждёт POST /chat/{id}/lock_pipeline
    async lockPipeline(chatId, pipelineId) {
        return this._request(`/chat/${encodeURIComponent(chatId)}/lock_pipeline`, {
            method: 'POST',
            body: JSON.stringify({ pipeline_id: pipelineId }),
        });
    }

    // === DB Management API (LanceDB) ===
    async listDocuments(vaultId, limit = 100, offset = 0) {
        const params = new URLSearchParams({ vault_id: vaultId, limit: String(limit), offset: String(offset) });
        const response = await fetch(`${this.baseUrl}/api/db/documents?${params}`);
        if (!response.ok) throw new Error(`Failed to list documents: ${response.statusText}`);
        return response.json();
    }

    async listDocumentChunks(documentId, vaultId) {
        const params = new URLSearchParams({ document_id: documentId, vault_id: vaultId });
        const response = await fetch(`${this.baseUrl}/api/db/chunks?${params}`);
        if (!response.ok) throw new Error(`Failed to list chunks: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(`${this.baseUrl}/api/db/documents/${encodeURIComponent(documentId)}?${params}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
        return response.json();
    }

    async textSearch(vaultId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/api/db/search/text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vault_id: vaultId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search: ${response.statusText}`);
        return response.json();
    }

    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/api/db/search/domain`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search: ${response.statusText}`);
        return response.json();
    }

    async reindexVault(vaultId, forceReindex = false) {
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/reindex`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_reindex: forceReindex }),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Failed to start indexing: ${text}`);
        }
        return response.json();
    }

    async detachVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/detach`, { method: 'POST' });
        if (!response.ok) throw new Error(`Failed to detach vault: ${response.statusText}`);
        return response.json();
    }

    // === Index Tasks API ===
    async getIndexTaskState(taskId) {
        const response = await fetch(`${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}/state`);
        if (!response.ok) throw new Error(`Failed to get task state: ${response.statusText}`);
        return response.json();
    }

    async cancelIndexTask(taskId) {
        const response = await fetch(`${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`Failed to cancel task: ${response.statusText}`);
        return response.json();
    }

    connectToTaskStream(taskId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/index-tasks/${encodeURIComponent(taskId)}`;
        return new WebSocket(wsUrl);
    }

    // === Settings API ===
    async getSettingsStatus() { return this._request('/api/settings/status'); }
    async getSettingsParams() { return this._request('/api/settings/params'); }

    // FIX: был /api/settings/param/{key} (singular) → правильно /api/settings/params/{key} (plural)
    async updateSettingsParam(key, value) {
        return this._request(`/api/settings/params/${encodeURIComponent(key)}`, {
            method: 'PUT',
            body: JSON.stringify({ value }),
        });
    }
    async resetSettingsParams() { return this._request('/api/settings/reset', { method: 'POST' }); }

    async getDomains() { return this._request('/api/settings/domains'); }
    async createDomain(data) { return this._request('/api/settings/domains', { method: 'POST', body: JSON.stringify(data) }); }
    async updateDomain(id, data) { return this._request(`/api/settings/domains/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteDomain(id) { return this._request(`/api/settings/domains/${encodeURIComponent(id)}`, { method: 'DELETE' }); }

    async getDomainPrompts(id) { return this._request(`/api/settings/domains/${encodeURIComponent(id)}/prompts`); }
    async updateDomainPrompt(id, type, content) {
        return this._request(`/api/settings/domains/${encodeURIComponent(id)}/prompts/${encodeURIComponent(type)}`, {
            method: 'PUT',
            body: JSON.stringify({ content }),
        });
    }
    async getDomainFields(id) { return this._request(`/api/settings/domains/${encodeURIComponent(id)}/fields`); }
    async updateDomainFields(id, fields) {
        return this._request(`/api/settings/domains/${encodeURIComponent(id)}/fields`, { method: 'PUT', body: JSON.stringify(fields) });
    }

    async getGenerationModels() { return this._request('/api/settings/models/generation'); }
    async createGenerationModel(data) { return this._request('/api/settings/models/generation', { method: 'POST', body: JSON.stringify(data) }); }
    async updateGenerationModel(id, data) { return this._request(`/api/settings/models/generation/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteGenerationModel(id) { return this._request(`/api/settings/models/generation/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async activateGenerationModel(id) { return this._request(`/api/settings/models/generation/${encodeURIComponent(id)}/activate`, { method: 'POST' }); }
    async checkGenerationModel(id) { return this._request(`/api/settings/models/generation/${encodeURIComponent(id)}/check`, { method: 'POST' }); }

    async getEmbeddingModels() { return this._request('/api/settings/models/embedding'); }
    async createEmbeddingModel(data) { return this._request('/api/settings/models/embedding', { method: 'POST', body: JSON.stringify(data) }); }
    async updateEmbeddingModel(id, data) { return this._request(`/api/settings/models/embedding/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteEmbeddingModel(id) { return this._request(`/api/settings/models/embedding/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async checkEmbeddingModel(id) { return this._request(`/api/settings/models/embedding/${encodeURIComponent(id)}/check`, { method: 'POST' }); }

    async getSettingsVaults() { return this._request('/api/settings/vaults'); }
    async createVault(data) { return this._request('/api/settings/vaults', { method: 'POST', body: JSON.stringify(data) }); }
    async updateVault(id, data) { return this._request(`/api/settings/vaults/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteVault(id) { return this._request(`/api/settings/vaults/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async toggleVault(id) { return this._request(`/api/settings/vaults/${encodeURIComponent(id)}/toggle`, { method: 'POST' }); }

    // === Tags API ===
    // Приоритет: domain_id. vault_id оставлен для обратной совместимости (например, settings.js ещё может слать vault_id).
    async getTags(domainId, campaignId = null) {
        const url = new URL(`${this.baseUrl}/api/settings/tags`, window.location.origin);
        url.searchParams.set('domain_id', domainId);
        if (campaignId) url.searchParams.set('campaign_id', campaignId);
        return this._request(url.pathname + url.search);
    }
    // Старый метод через vault — оставлен для кода, который ещё не перешёл на domain_id
    async getTagsByVault(vaultId, campaignId = null) {
        const url = new URL(`${this.baseUrl}/api/settings/tags`, window.location.origin);
        url.searchParams.set('vault_id', vaultId);
        if (campaignId) url.searchParams.set('campaign_id', campaignId);
        return this._request(url.pathname + url.search);
    }
    async createTag(data) { return this._request('/api/settings/tags', { method: 'POST', body: JSON.stringify(data) }); }
    async updateTag(tagId, data) { return this._request(`/api/settings/tags/${encodeURIComponent(tagId)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteTag(tagId) { return this._request(`/api/settings/tags/${encodeURIComponent(tagId)}`, { method: 'DELETE' }); }
    async getCampaignTags(campaignId) { return this._request(`/api/settings/campaigns/${encodeURIComponent(campaignId)}/tags`); }
    async createCampaignTag(campaignId, data) {
        return this._request(`/api/settings/campaigns/${encodeURIComponent(campaignId)}/tags`, { method: 'POST', body: JSON.stringify(data) });
    }

    // === Campaigns API ===
    // getCampaigns(домен): приоритет domain_id. vault_id удалён.
    async getCampaigns(domainId = null) {
        const url = new URL(`${this.baseUrl}/api/settings/campaigns`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        return this._request(url.pathname + url.search);
    }
    async getCampaign(id) { return this._request(`/api/settings/campaigns/${encodeURIComponent(id)}`); }
    async createCampaign(data) { return this._request('/api/settings/campaigns', { method: 'POST', body: JSON.stringify(data) }); }
    async updateCampaign(id, data) {
        return this._request(`/api/settings/campaigns/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) });
    }
    async deleteCampaign(id) { return this._request(`/api/settings/campaigns/${encodeURIComponent(id)}`, { method: 'DELETE' }); }

    // === Documents API (PostgreSQL registry) ===
    async getDocuments(vaultId) {
        const url = new URL(`${this.baseUrl}/api/settings/documents`, window.location.origin);
        url.searchParams.set('vault_id', vaultId);
        return this._request(url.pathname + url.search);
    }
    async deleteDocumentById(documentId) {
        return this._request(`/api/settings/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' });
    }
    async updateDocumentLabels(documentId, tagIds) {
        return this._request(`/api/settings/documents/${encodeURIComponent(documentId)}/labels`, {
            method: 'PUT',
            body: JSON.stringify({ tag_ids: tagIds }),
        });
    }

    // === Indexer API ===
    async runIndexer(vaultId, forceReindex = false) {
        return this.reindexVault(vaultId, forceReindex);
    }

    // === Pipelines API ===
    // getPipelines(домен, кампания): бэкенд фильтрует пайплайны по тегам кампании если campaign_id задан
    async getPipelines(domainId = null, campaignId = null) {
        const url = new URL(`${this.baseUrl}/api/settings/pipelines`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        if (campaignId) url.searchParams.set('campaign_id', campaignId);
        return this._request(url.pathname + url.search);
    }

    async getPipeline(pipelineId) {
        return this._request(`/api/settings/pipelines/${encodeURIComponent(pipelineId)}`);
    }
    async createPipeline(data) { return this._request('/api/settings/pipelines', { method: 'POST', body: JSON.stringify(data) }); }
    async updatePipeline(id, data) { return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deletePipeline(id) { return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async activatePipeline(id) { return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}/activate`, { method: 'POST' }); }
    async deactivatePipeline(id) {
        return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}/deactivate`, { method: 'POST' });
    }

    async _request(path, options = {}) {
        const response = await fetch(`${this.baseUrl}${path}`, {
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
            ...options,
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || response.statusText);
        }
        if (response.status === 204) return null;
        return response.json();
    }
}

const chatAPI = new ChatAPI();
window.chatAPI = chatAPI;
