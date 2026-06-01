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

    async sendMessage(chatId, content, stream = true) {
        const url = stream
            ? `${this.baseUrl}/chat/${chatId}/send_stream`
            : `${this.baseUrl}/chat/${chatId}/send`;
        // C25-A fix: при stream=true добавляем stream:true в body (SendMessageRequest требует это поле)
        const body = stream ? { content, stream: true } : { content };
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
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

    // === Settings: Domains CRUD ===

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

    // === Settings: Embedding Models CRUD ===
    // S19-A: setActiveEmbeddingModel удалён — роута нет, концепция неприменима.

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

    // === Settings: Documents ===

    // S40-B fix: метод отсутствовал. Бэк: GET /api/settings/documents?vault_id=|domain_id=&status=&tag_id=
    // Один из vault_id / domain_id обязателен (иначе бэк вернёт 400).
    // Фильтры status и tag_id — серверные, переносим фильтрацию на бэк.
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

    // S41-A fix: метод отсутствовал. Бэк: GET /api/settings/documents/{document_id} → DocumentRead
    async getSettingsDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}`);
        if (!response.ok) throw new Error(`Failed to get settings document: ${response.statusText}`);
        return response.json();
    }

    // DB Management: Documents

    // D1 fix: /api/db/documents?vault_id= (не /api/settings/documents?domain_id=)
    // Параметр vault_id обязателен — бэк принимает только vault_id, не domain_id.
    // tab-documents.js использует _resolveVaultId() перед вызовом.
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

    // D2 fix: DELETE /api/db/documents/{id}?vault_id= (не /api/settings/documents/{id})
    // Ответ — JSON (не 204!), бэк возвращает payload с deleted_count.
    async deleteDocumentById(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(`${this.baseUrl}/api/db/documents/${encodeURIComponent(documentId)}?${params}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
        return response.json(); // возвращает JSON, не 204
    }

    // D6 fix: путь исправлен /api/db/ → /api/settings/
    // Роут PUT /api/settings/documents/{id}/labels реализован в app/api/settings/documents.py
    // Full-replace семантика: удаляет все старые метки, вставляет новые.
    // Валидирует domain ownership тегов. Возвращает DocumentRead (200).
    async updateDocumentLabels(documentId, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}/labels`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to update document labels: ${response.statusText}`);
        return response.json();
    }

    // S44-A fix: метод отсутствовал — бэк имеет эндпоинт, фронт не мог его вызвать.
    // Семантика: additive (добавляет теги, не заменяет). Ответ: 204 No Content.
    async batchLabelDocuments(documentIds, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/labels/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ document_ids: documentIds, tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to batch label documents: ${response.statusText}`);
        // 204 No Content
    }

    // D3 fix: /vaults/{id}/reindex (не /api/settings/vaults/{id}/reindex)
    async reindexVault(vaultId, force = false) {
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/reindex`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_reindex: force }),
        });
        if (!response.ok) throw new Error(`Failed to reindex vault: ${response.statusText}`);
        return response.json();
    }

    // D4 fix: WS /ws/index-tasks/{id} (не /api/settings/tasks/{id}/stream)
    connectToTaskStream(taskId) {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${proto}://${location.host}/ws/index-tasks/${encodeURIComponent(taskId)}`;
        return new WebSocket(wsUrl);
    }

    // D5 fix: GET /index-tasks/{id}/state (не /api/settings/tasks/{id})
    async getIndexTaskState(taskId) {
        const response = await fetch(`${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}/state`);
        if (!response.ok) throw new Error(`Failed to get task state: ${response.statusText}`);
        return response.json();
    }

    // D7 fix: метод отсутствовал — db_management.js вызывал chatAPI.textSearchByDomain(), которого не было.
    // Бэк: POST /api/db/search/domain, body: {domain_id, query_text, limit}
    // Ответ: TextSearchResponse {results: [{chunk_id, document_id, text, score, metadata}]}
    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/api/db/search/domain`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search by domain: ${response.statusText}`);
        return response.json();
    }
}

// Глобальный синглтон API-клиента
window.chatAPI = new ChatAPI();
