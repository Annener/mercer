// API клиент для работы с backend
class ChatAPI {
    constructor() {
        this.baseUrl = '';
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

    // === DB Management API ===
    // Согласно спецификации V3.0: /api/db/*

    async listDocuments(vaultId, limit = 100, offset = 0) {
        const params = new URLSearchParams({
            vault_id: vaultId,
            limit: String(limit),
            offset: String(offset),
        });
        const response = await fetch(`${this.baseUrl}/api/db/documents?${params}`);
        if (!response.ok) throw new Error(`Failed to list documents: ${response.statusText}`);
        return response.json();
    }

    async listDocumentChunks(documentId, vaultId) {
        const params = new URLSearchParams({
            document_id: documentId,
            vault_id: vaultId,
        });
        const response = await fetch(`${this.baseUrl}/api/db/chunks?${params}`);
        if (!response.ok) throw new Error(`Failed to list chunks: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(
            `${this.baseUrl}/api/db/documents/${encodeURIComponent(documentId)}?${params}`,
            { method: 'DELETE' },
        );
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
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/detach`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to detach vault: ${response.statusText}`);
        return response.json();
    }

    // === Index Tasks API ===
    // Согласно спецификации V3.0: /index-tasks/* (не /indexer/tasks/*)

    async getIndexTaskState(taskId) {
        const response = await fetch(
            `${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}/state`,
        );
        if (!response.ok) throw new Error(`Failed to get task state: ${response.statusText}`);
        return response.json();
    }

    async cancelIndexTask(taskId) {
        const response = await fetch(
            `${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}`,
            { method: 'DELETE' },
        );
        if (!response.ok) throw new Error(`Failed to cancel task: ${response.statusText}`);
        return response.json();
    }

    // WebSocket согласно спецификации V3.0: /ws/index-tasks/{task_id}
    connectToTaskStream(taskId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/index-tasks/${encodeURIComponent(taskId)}`;
        return new WebSocket(wsUrl);
    }

    // === Settings API ===
    // Согласно спецификации V3.0: /api/settings/*

    async getSettingsStatus() { return this._request('/api/settings/status'); }
    async getSettingsParams() { return this._request('/api/settings/params'); }
    async updateSettingsParam(key, value) {
        return this._request(`/api/settings/param/${encodeURIComponent(key)}`, {
            method: 'PUT',
            body: JSON.stringify({ value }),
        });
    }
    async resetSettingsParams() { return this._request('/api/settings/reset', { method: 'POST' }); }

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

    // Модели согласно спецификации V3.0: /models/generation, /models/embedding
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

    async getWorlds(vaultId = null) {
        const url = new URL(`${this.baseUrl}/api/settings/worlds`, window.location.origin);
        if (vaultId) url.searchParams.set('vault_id', vaultId);
        return this._request(url.pathname + url.search);
    }
    async createWorld(data) { return this._request('/api/settings/worlds', { method: 'POST', body: JSON.stringify(data) }); }
    async updateWorld(worldId, data) { return this._request(`/api/settings/worlds/${encodeURIComponent(worldId)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async getWorldCampaigns(worldId) { return this._request(`/api/settings/worlds/${encodeURIComponent(worldId)}/campaigns`); }
    async createCampaign(worldId, data) { return this._request(`/api/settings/worlds/${encodeURIComponent(worldId)}/campaigns`, { method: 'POST', body: JSON.stringify(data) }); }
    async updateCampaign(worldId, campaignId, data) {
        return this._request(`/api/settings/worlds/${encodeURIComponent(worldId)}/campaigns/${encodeURIComponent(campaignId)}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }
    async toggleCampaign(worldId, campaignId) {
        return this._request(`/api/settings/worlds/${encodeURIComponent(worldId)}/campaigns/${encodeURIComponent(campaignId)}/toggle`, { method: 'POST' });
    }

    async getPipelines(domainId = null) {
        const url = new URL(`${this.baseUrl}/api/settings/pipelines`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        return this._request(url.pathname + url.search);
    }
    async createPipeline(data) { return this._request('/api/settings/pipelines', { method: 'POST', body: JSON.stringify(data) }); }
    async updatePipeline(id, data) { return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) }); }
    async deletePipeline(id) { return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
    async activatePipeline(id) { return this._request(`/api/settings/pipelines/${encodeURIComponent(id)}/activate`, { method: 'POST' }); }
    async deactivatePipeline(id) { return this.deletePipeline(id); }

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