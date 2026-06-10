// API клиент для работы с backend
class ChatAPI {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }

    async createChat(domainId = null, campaignId = null) {
        const response = await fetch(`${this.baseUrl}/api/chat/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, campaign_id: campaignId }),
        });
        if (!response.ok) throw new Error(`Failed to create chat: ${response.statusText}`);
        return response.json();
    }

    async sendMessage(chatId, message, mode = 'general') {
        const response = await fetch(`${this.baseUrl}/api/chat/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: chatId, message, mode }),
        });
        if (!response.ok) throw new Error(`Failed to send message: ${response.statusText}`);
        return response.json();
    }

    getStreamUrl(chatId, message, mode = 'general') {
        const params = new URLSearchParams({ chat_id: chatId, message, mode });
        return `${this.baseUrl}/api/chat/send_stream?${params}`;
    }

    async getChatHistory(chatId) {
        const response = await fetch(`${this.baseUrl}/api/chat/history/${chatId}`);
        if (!response.ok) throw new Error(`Failed to get history: ${response.statusText}`);
        return response.json();
    }

    async listChats(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/chat/list${qs}`);
        if (!response.ok) throw new Error(`Failed to list chats: ${response.statusText}`);
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/api/chat/${chatId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
    }

    async updateChatTitle(chatId, title) {
        const response = await fetch(`${this.baseUrl}/api/chat/${chatId}/title`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        if (!response.ok) throw new Error(`Failed to update chat title: ${response.statusText}`);
        return response.json();
    }

    // --- Settings: Domains ---

    async getSettingsDomains() {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    }

    async getDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}`);
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
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update domain: ${response.statusText}`);
        return response.json();
    }

    async deleteDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete domain: ${response.statusText}`);
    }

    // --- Settings: Campaigns ---

    async getCampaigns(domainId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        const qs = params.toString() ? `?${params}` : '';
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

    // --- Settings: Pipelines ---

    async getPipelines(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines${qs}`);
        if (!response.ok) throw new Error(`Failed to get pipelines: ${response.statusText}`);
        return response.json();
    }

    async getPipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`);
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
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update pipeline: ${response.statusText}`);
        return response.json();
    }

    async deletePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete pipeline: ${response.statusText}`);
    }

    // --- Settings: Vaults ---

    async getVaults(domainId = null) {
        const params = new URLSearchParams();
        if (domainId) params.set('domain_id', domainId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/vaults${qs}`);
        if (!response.ok) throw new Error(`Failed to get vaults: ${response.statusText}`);
        return response.json();
    }

    async getVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`);
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
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update vault: ${response.statusText}`);
        return response.json();
    }

    async deleteVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete vault: ${response.statusText}`);
    }

    // --- Settings: Documents ---

    // S40-B fix: метод отсутствовал. Бэк: GET /api/settings/documents?vault_id=|domain_id=&status=&tag_id=
    // Параметры: vaultId, domainId, status ('indexed'|'pending'|...), tagId
    async getSettingsDocuments({ vaultId = null, domainId = null, status = null, tagId = null } = {}) {
        const params = new URLSearchParams();
        if (vaultId)  params.set('vault_id',   vaultId);
        if (domainId) params.set('domain_id',  domainId);
        if (status)   params.set('status',      status);
        if (tagId)    params.set('tag_id',     tagId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents${qs}`);
        if (!response.ok) throw new Error(`Failed to get documents: ${response.statusText}`);
        return response.json();
    }

    async uploadDocument(formData) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/upload`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) throw new Error(`Failed to upload document: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${documentId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
    }

    async reindexDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${documentId}/reindex`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reindex document: ${response.statusText}`);
        return response.json();
    }

    async updateDocumentLabels(documentId, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${documentId}/labels`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to update document labels: ${response.statusText}`);
        return response.json();
    }

    // --- Settings: Models ---

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

    // --- Analytics ---

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

    // --- Health ---

    async getHealth() {
        const response = await fetch(`${this.baseUrl}/api/health`);
        if (!response.ok) throw new Error(`Health check failed: ${response.statusText}`);
        return response.json();
    }

    // --- Settings: Config ---

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

    // --- Clarification FSM ---

    async getClarificationState(chatId) {
        const response = await fetch(`${this.baseUrl}/api/chat/${chatId}/clarification`);
        if (!response.ok) throw new Error(`Failed to get clarification state: ${response.statusText}`);
        return response.json();
    }

    async updateClarificationState(chatId, data) {
        const response = await fetch(`${this.baseUrl}/api/chat/${chatId}/clarification`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update clarification state: ${response.statusText}`);
        return response.json();
    }

    // --- Embedding Models ---

    async getEmbeddingModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/embedding-models`);
        if (!response.ok) throw new Error(`Failed to get embedding models: ${response.statusText}`);
        return response.json();
    }

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
}

// Глобальный синглтон — используется в chat.js, sidebar.js, settings.js
window.chatAPI = new ChatAPI();
