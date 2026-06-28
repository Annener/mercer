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

    async updateChatTitle(chatId, title) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/title`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        if (!response.ok) {
            return this.renameChat(chatId, title);
        }
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
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

    async sendMessage(chatId, content, stream = true, signal = null) {
        const url = stream
            ? `${this.baseUrl}/chat/${chatId}/send_stream`
            : `${this.baseUrl}/chat/${chatId}/send`;
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
            } catch (_) {}
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
            } catch (_) {}
            throw new Error(errMsg);
        }
        return response.json();
    }

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
            } catch (_) {}
            throw new Error(errMsg);
        }
        const ct = response.headers.get('content-type') || '';
        if (ct.includes('text/event-stream')) return response.body;
        return response.json();
    }

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
            } catch (_) {}
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
        if (domainId)  params.set('domain_id',   domainId);
        if (vaultId)   params.set('vault_id',     vaultId);
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

    async getPipelines(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId)   params.set('domain_id',   domainId);
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

    async activatePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate pipeline: ${response.statusText}`);
        return response.json();
    }

    async deactivatePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate pipeline: ${response.statusText}`);
        return response.json();
    }

    async deletePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete pipeline: ${response.statusText}`);
    }

    // === Settings API ===

    async getSettingsStatus() {
        const response = await fetch(`${this.baseUrl}/api/settings/status`);
        if (!response.ok) throw new Error(`Failed to get settings status: ${response.statusText}`);
        return response.json();
    }

    async getSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/params`);
        if (!response.ok) throw new Error(`Failed to get settings params: ${response.statusText}`);
        return response.json();
    }

    async updateSettingsParam(key, value) {
        const response = await fetch(`${this.baseUrl}/api/settings/params/${encodeURIComponent(key)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
        if (!response.ok) throw new Error(`Failed to update param: ${response.statusText}`);
        return response.json();
    }

    async resetSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/params/reset`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reset params: ${response.statusText}`);
        return response.json();
    }

    async getConfig() {
        const response = await fetch(`${this.baseUrl}/config`);
        if (!response.ok) throw new Error(`Failed to get config: ${response.statusText}`);
        return response.json();
    }

    async updateConfig(data) {
        const response = await fetch(`${this.baseUrl}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update config: ${response.statusText}`);
        return response.json();
    }

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

    async getDomainPrompts(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/prompts`);
        if (!response.ok) throw new Error(`Failed to get domain prompts: ${response.statusText}`);
        return response.json();
    }

    async updateDomainPrompt(domainId, promptType, content) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/prompts/${promptType}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        if (!response.ok) throw new Error(`Failed to update domain prompt: ${response.statusText}`);
        return response.json();
    }

    async getDomainFields(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/fields`);
        if (!response.ok) throw new Error(`Failed to get domain fields: ${response.statusText}`);
        return response.json();
    }

    async updateDomainFields(domainId, fields) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/fields`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(fields),
        });
        if (!response.ok) throw new Error(`Failed to update domain fields: ${response.statusText}`);
        return response.json();
    }

    async getVaults(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/vaults${qs}`);
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

    async toggleVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle vault: ${response.statusText}`);
        return response.json();
    }

    // === Generation Models ===

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
    }

    async setActiveGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate generation model: ${response.statusText}`);
        return response.json();
    }

    async deactivateGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate generation model: ${response.statusText}`);
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

    // === Embedding Models ===

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
    }

    async toggleEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle embedding model: ${response.statusText}`);
        return response.json();
    }

    async checkEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check embedding model: ${response.statusText}`);
        return response.json();
    }

    // === Rerank Models ===

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
    }

    async checkRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check rerank model: ${response.statusText}`);
        return response.json();
    }

    async setActiveRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate rerank model: ${response.statusText}`);
        return response.json();
    }

    async activateRerankModel(modelId) {
        return this.setActiveRerankModel(modelId);
    }

    async deactivateRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate rerank model: ${response.statusText}`);
        return response.json();
    }

    async toggleRerankModel(modelId) {
        const current = await this.getRerankModels();
        const model = (Array.isArray(current) ? current : []).find(m => m.model_id === modelId);
        if (!model) throw new Error('Rerank model not found');
        return this.updateRerankModel(modelId, { enabled: !(model.enabled !== false) });
    }

    async getDocuments(vaultId = null, domainId = null) {
        const params = new URLSearchParams();
        if (vaultId) params.set('vault_id', vaultId);
        if (domainId) params.set('domain_id', domainId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents${qs}`);
        if (!response.ok) throw new Error(`Failed to get documents: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
    }

    async getWatchdogSettings() {
        const res = await fetch('/api/v1/settings/watchdog');
        if (!res.ok) throw new Error('Failed to load watchdog settings');
        return res.json();
    }

    async saveWatchdogSettings(extensions, intervalSec) {
        const res = await fetch('/api/v1/settings/watchdog', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                auto_index_extensions: extensions,
                interval_sec: intervalSec,
            }),
        });
        if (!res.ok) throw new Error('Failed to save watchdog settings');
        return res.json();
    }

    async getSidecarStatus() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/status`);
        if (!res.ok) {
            return { running: false, installed: false, agent_unavailable: true };
        }
        return res.json();
    }

    async sidecarStart() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/start`, { method: 'POST' });
        if (!res.ok) {
            let detail = res.statusText;
            try { detail = (await res.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return res.json();
    }

    async sidecarStop() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/stop`, { method: 'POST' });
        if (!res.ok) {
            let detail = res.statusText;
            try { detail = (await res.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return res.json();
    }

    async sidecarRestart() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/restart`, { method: 'POST' });
        if (!res.ok) {
            let detail = res.statusText;
            try { detail = (await res.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return res.json();
    }

    getSidecarInstallStreamUrl() {
        return `${this.baseUrl}/api/settings/sidecar/install/stream`;
    }

    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/api/db/search/domain`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                domain_id: domainId,
                query_text: queryText,
                limit,
            }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {}
            throw new Error(`Text search failed: ${errMsg}`);
        }
        return response.json();
    }

    async getSettingsVaults() {
        return this.getVaults();
    }

    async getSettingsDocuments({ vaultId = null, domainId = null, status = null, tagId = null } = {}) {
        const params = new URLSearchParams();
        if (vaultId)  params.set('vault_id',  vaultId);
        if (domainId) params.set('domain_id', domainId);
        if (status)   params.set('status',    status);
        if (tagId)    params.set('tag_id',    tagId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents${qs}`);
        if (!response.ok) throw new Error(`Failed to get documents: ${response.statusText}`);
        return response.json();
    }

    async deleteDocumentById(documentId, vaultId = null) {
        const params = new URLSearchParams();
        if (vaultId) params.set('vault_id', vaultId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}${qs}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
    }

    async updateDocumentLabels(documentId, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}/labels`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to update document labels: ${response.statusText}`);
        return response.json();
    }

    async runIndexer(domainId = null) {
        if (!domainId) {
            try {
                const resp = await this.getDomains();
                const list = Array.isArray(resp) ? resp : (resp.domains || []);
                const first = list.find(d => d.enabled !== false) || list[0];
                domainId = first ? (first.domain_id || first.id || null) : null;
            } catch (_) {}
        }
        if (!domainId) throw new Error('No active domain found to run indexer');
        const response = await fetch(`${this.baseUrl}/api/v1/domains/${encodeURIComponent(domainId)}/index`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to run indexer: ${response.statusText}`);
        return response.json();
    }

    async getIndexTaskState(taskId) {
        const response = await fetch(`${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}/state`);
        if (!response.ok) throw new Error(`Failed to get index task state: ${response.statusText}`);
        return response.json();
    }

    async cancelIndexTask(taskId) {
        return { cancelled: true, task_id: taskId };
    }
}

window.chatAPI = new ChatAPI();
