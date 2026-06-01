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

    // S22 fix: отсутствовали — вызывались из handlePipelinesAction
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

    // Ключ передаётся as-is — FastAPI {key:path} принимает точки напрямую
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

    // === Settings: Domains CRUD ===

    // getDomains() сохраняется для sidebar (/config/domains, read-only).
    // getSettingsDomains() — полный список для настроек.
    async getSettingsDomains() {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
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
    // S17-A fix: вся группа отсутствовала → TypeError в handleVaultsAction / showVaultModal

    async getSettingsVaults() {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults`);
        if (!response.ok) throw new Error(`Failed to get vaults: ${response.statusText}`);
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

    // === Settings: Generation Models CRUD ===
    // S18-A fix: вся группа отсутствовала → TypeError в handleGenModelsAction

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
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/set_active`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to set active generation model: ${response.statusText}`);
        return response.json();
    }

    // === Settings: Embedding Models CRUD ===
    // S19-A fix: вся группа отсутствовала → TypeError в handleEmbModelsAction

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

    async setActiveEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}/set_active`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to set active embedding model: ${response.statusText}`);
        return response.json();
    }
}

// Глобальный синглтон API-клиента
window.chatAPI = new ChatAPI();
