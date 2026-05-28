// API клиент для работы с backend
class ChatAPI {
    constructor() {
        this.baseUrl = '';
        this.indexerUrl = 'http://localhost:9000';
        this.indexerWsUrl = `ws://${window.location.hostname}:9000`;
    }

    // === Chat API ===

    async createChat(vaultId = null, domainId = null, worldId = null) {
        const response = await fetch(`${this.baseUrl}/chat/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vault_id: vaultId,
                domain_id: domainId,
                world_id: worldId,
            }),
        });
        if (!response.ok) {
            throw new Error(`Failed to create chat: ${response.statusText}`);
        }
        return response.json();
    }

    async listChats(domainId = null) {
        const url = new URL(`${this.baseUrl}/chat/list`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        const response = await fetch(url.toString());
        if (!response.ok) throw new Error(`Failed to list chats: ${response.statusText}`);
        return response.json();
    }

    async getChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`);
        if (!response.ok) throw new Error(`Failed to get chat: ${response.statusText}`);
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
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

    async sendMessage(chatId, content, stream = true) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, stream }),
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

    async lockPipeline(chatId, pipelineId) {
        return this._request(`/chat/${encodeURIComponent(chatId)}/pipeline`, {
            method: 'PUT',
            body: JSON.stringify({ pipeline_id: pipelineId }),
        });
    }

    // === Config API ===

    async getDomains() {
        const response = await fetch(`${this.baseUrl}/config/domains`);
        if (!response.ok) throw new Error(`Failed to load domains: ${response.statusText}`);
        return response.json();
    }

    async getVaults(domainId = null, search = null) {
        const url = new URL(`${this.baseUrl}/config/vaults`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        if (search) url.searchParams.set('search', search);
        const response = await fetch(url.toString());
        if (!response.ok) throw new Error(`Failed to load vaults: ${response.statusText}`);
        return response.json();
    }

    // === DB Management API ===

    async listDocuments(vaultId, limit = 100, offset = 0) {
        const params = new URLSearchParams({
            vault_id: vaultId,
            limit: String(limit),
            offset: String(offset),
        });
        const response = await fetch(`${this.baseUrl}/db/documents?${params}`);
        if (!response.ok) throw new Error(`Failed to list documents: ${response.statusText}`);
        return response.json();
    }

    async listDocumentChunks(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(`${this.baseUrl}/db/docs/${encodeURIComponent(documentId)}/chunks?${params}`);
        if (!response.ok) throw new Error(`Failed to list chunks: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(
            `${this.baseUrl}/db/docs/${encodeURIComponent(documentId)}?${params}`,
            { method: 'DELETE' },
        );
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
        return response.json();
    }

    async textSearch(vaultId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/db/search/text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vault_id: vaultId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search: ${response.statusText}`);
        return response.json();
    }

    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/db/search/text/by-domain`, {
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
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/detach`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to detach vault: ${response.statusText}`);
        return response.json();
    }

    async getIndexerTaskState(taskId) {
        const response = await fetch(
            `${this.baseUrl}/indexer/tasks/${encodeURIComponent(taskId)}/state`,
        );
        if (!response.ok) throw new Error(`Failed to get task state: ${response.statusText}`);
        return response.json();
    }

    async cancelIndexTask(taskId) {
        // Используем backend-прокси вместо прямого запроса на localhost:9000 (избегаем CORS)
        const response = await fetch(
            `${this.baseUrl}/indexer/tasks/${encodeURIComponent(taskId)}/cancel`,
            { method: 'POST' },
        );
        if (!response.ok) throw new Error(`Failed to cancel task: ${response.statusText}`);
        return response.json();
    }

    connectToTaskStream(taskId) {
        // WebSocket на indexer через текущий хост (поддерживает прохождение через nginx если есть)
        const url = `${this.indexerWsUrl}/api/v1/tasks/${encodeURIComponent(taskId)}/stream`;
        return new WebSocket(url);
    }

    // === Settings API ===
    async getSettingsStatus() { return this._request('/settings/status'); }
    async getSettingsParams() { return this._request('/settings/params'); }
    async updateSettingsParam(key, value) {
        return this._request(`/settings/params/${encodeURIComponent(key)}`, {
            method: 'PUT',
            body: JSON.stringify({ value }),
        });
    }
    async resetSettingsParams() { return this._request('/settings/params/reset', { method: 'POST' }); }

    async createDomain(data) { return this._request('/settings/domains', { method: 'POST', body: JSON.stringify(data) }); }
    async updateDomain(id, data) { return this._request(`/settings/domains/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteDomain(id) { return this._request(`/settings/domains/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async getDomainPrompts(id) { return this._request(`/settings/domains/${encodeURIComponent(id)}/prompts`); }
    async updateDomainPrompt(id, type, content) {
        return this._request(`/settings/domains/${encodeURIComponent(id)}/prompts/${encodeURIComponent(type)}`, {
            method: 'PUT',
            body: JSON.stringify({ content }),
        });
    }
    async getDomainFields(id) { return this._request(`/settings/domains/${encodeURIComponent(id)}/fields`); }
    async updateDomainFields(id, fields) {
        return this._request(`/settings/domains/${encodeURIComponent(id)}/fields`, { method: 'PUT', body: JSON.stringify(fields) });
    }

    async getGenerationModels() { return this._request('/settings/generation-models'); }
    async createGenerationModel(data) { return this._request('/settings/generation-models', { method: 'POST', body: JSON.stringify(data) }); }
    async updateGenerationModel(id, data) { return this._request(`/settings/generation-models/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteGenerationModel(id) { return this._request(`/settings/generation-models/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async activateGenerationModel(id) { return this._request(`/settings/generation-models/${encodeURIComponent(id)}/activate`, { method: 'POST' }); }
    async checkGenerationModel(id) { return this._request(`/settings/generation-models/${encodeURIComponent(id)}/check`, { method: 'POST' }); }

    async getEmbeddingModels() { return this._request('/settings/embedding-models'); }
    async createEmbeddingModel(data) { return this._request('/settings/embedding-models', { method: 'POST', body: JSON.stringify(data) }); }
    async updateEmbeddingModel(id, data) { return this._request(`/settings/embedding-models/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteEmbeddingModel(id) { return this._request(`/settings/embedding-models/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async checkEmbeddingModel(id) { return this._request(`/settings/embedding-models/${encodeURIComponent(id)}/check`, { method: 'POST' }); }

    async getSettingsVaults() { return this._request('/settings/vaults'); }
    async createVault(data) { return this._request('/settings/vaults', { method: 'POST', body: JSON.stringify(data) }); }
    async updateVault(id, data) { return this._request(`/settings/vaults/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deleteVault(id) { return this._request(`/settings/vaults/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async toggleVault(id) { return this._request(`/settings/vaults/${encodeURIComponent(id)}/toggle`, { method: 'POST' }); }

    async getWorlds(vaultId = null) {
        const url = new URL(`${this.baseUrl}/settings/worlds`, window.location.origin);
        if (vaultId) url.searchParams.set('vault_id', vaultId);
        return this._request(url.pathname + url.search);
    }
    async createWorld(data) { return this._request('/settings/worlds', { method: 'POST', body: JSON.stringify(data) }); }
    async updateWorld(worldId, data) { return this._request(`/settings/worlds/${encodeURIComponent(worldId)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async getWorldCampaigns(worldId) { return this._request(`/settings/worlds/${encodeURIComponent(worldId)}/campaigns`); }
    async createCampaign(worldId, data) { return this._request(`/settings/worlds/${encodeURIComponent(worldId)}/campaigns`, { method: 'POST', body: JSON.stringify(data) }); }
    async updateCampaign(worldId, campaignId, data) {
        return this._request(`/settings/worlds/${encodeURIComponent(worldId)}/campaigns/${encodeURIComponent(campaignId)}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }
    async toggleCampaign(worldId, campaignId) {
        return this._request(`/settings/worlds/${encodeURIComponent(worldId)}/campaigns/${encodeURIComponent(campaignId)}/toggle`, { method: 'POST' });
    }

    async getPipelines(domainId = null) {
        const url = new URL(`${this.baseUrl}/settings/pipelines`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        return this._request(url.pathname + url.search);
    }
    async createPipeline(data) { return this._request('/settings/pipelines', { method: 'POST', body: JSON.stringify(data) }); }
    async updatePipeline(id, data) { return this._request(`/settings/pipelines/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deletePipeline(id) { return this._request(`/settings/pipelines/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async activatePipeline(id) { return this._request(`/settings/pipelines/${encodeURIComponent(id)}/activate`, { method: 'POST' }); }

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
