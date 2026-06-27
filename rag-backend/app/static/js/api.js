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

    // Алиас для getChat — используется в новом коде
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

    // Алиас для renameChat через PUT (новый роут /chat/{id}/title)
    async updateChatTitle(chatId, title) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/title`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title }),
        });
        if (!response.ok) {
            // Fallback на старый роут если новый не существует
            return this.renameChat(chatId, title);
        }
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
        // 204 No Content — не вызываем .json()
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
     * @param {string} chatId
     * @param {string} content
     * @param {boolean} stream
     * @param {AbortSignal|null} signal — опциональный сигнал для прерывания запроса
     */
    async sendMessage(chatId, content, stream = true, signal = null) {
        const url = stream
            ? `${this.baseUrl}/chat/${chatId}/send_stream`
            : `${this.baseUrl}/chat/${chatId}/send`;
        // C25-A fix: при stream=true добавляем stream:true в body (SendMessageRequest требует это поле)
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

    // Clarification FSM (новые методы)
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

    // === Pipeline confirm / resume (Этап 10) ===

    /**
     * POST /chat/{chatId}/pipeline_confirm
     * action: 'confirm' | 'cancel'
     * confirmToken: строка из SSE-чанка pipeline_confirm_required
     *
     * fix: бэк ожидает {confirm_token, confirmed: bool}, не {confirm_token, action}
     */
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
            } catch (_) { /* ignore */ }
            throw new Error(errMsg);
        }
        // Ответ может быть StreamingResponse (SSE) или JSON в зависимости от бэка
        const ct = response.headers.get('content-type') || '';
        if (ct.includes('text/event-stream')) return response.body;
        return response.json();
    }

    /**
     * POST /chat/{chatId}/pipeline_resume
     * action: 'resume' | 'cancel'
     * resumeToken: строка из SSE-чанка validation_required
     * feedback: выбранная пользователем опция (только для action='resume')
     *
     * fix: бэк ожидает {resume_token, cancelled: bool, user_feedback}, не {resume_token, action, feedback}
     */
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
            } catch (_) { /* ignore */ }
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

    async getPipelines(campaignId = null) {
        const qs = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '';
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

    // === Vaults API ===

    async getVaults() {
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

    // === Documents API ===

    async getDocuments(vaultId = null, domainId = null) {
        const params = new URLSearchParams();
        if (vaultId) params.set('vault_id', vaultId);
        if (domainId) params.set('domain_id', domainId);
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

    // === Settings / Params API ===

    async getSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/v1/settings/params`);
        if (!response.ok) throw new Error(`Failed to get settings params: ${response.statusText}`);
        return response.json();
    }

    async updateSettingsParam(key, value) {
        const response = await fetch(`${this.baseUrl}/api/v1/settings/params/${encodeURIComponent(key)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
        if (!response.ok) throw new Error(`Failed to update settings param: ${response.statusText}`);
        return response.json();
    }

    async resetSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/v1/settings/params/reset`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reset settings params: ${response.statusText}`);
        return response.json();
    }

    // === Vault Watchdog settings ===

    async getWatchdogSettings() {
        const res = await fetch('/api/v1/settings/watchdog');
        if (!res.ok) throw new Error('Failed to load watchdog settings');
        return res.json(); // { auto_index_extensions: string[], interval_sec: number }
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

    // === PDF Sidecar (управление через host-agent) ===

    /** Статус sidecar-процесса. Никогда не бросает — возвращает { agent_unavailable: true } при недоступности агента. */
    async getSidecarStatus() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/status`);
        if (!res.ok) {
            return { running: false, installed: false, agent_unavailable: true };
        }
        return res.json();
    }

    async sidecarStart() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/start`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start sidecar');
        return res.json();
    }

    async sidecarStop() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/stop`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to stop sidecar');
        return res.json();
    }

    async sidecarRestart() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/restart`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to restart sidecar');
        return res.json();
    }

    getSidecarInstallStreamUrl() {
        return `${this.baseUrl}/api/settings/sidecar/install/stream`;
    }

    // === Indexer API ===

    // POST /api/v1/domains/{domain_id}/index  (watchdog_settings router)
    async runIndexer(domainId = null) {
        // Если domainId не передан — берём первый активный домен
        if (!domainId) {
            try {
                const resp = await this.getDomains();
                const list = Array.isArray(resp) ? resp : (resp.domains || []);
                const first = list.find(d => d.enabled !== false) || list[0];
                domainId = first ? (first.domain_id || first.id || null) : null;
            } catch (_) {}
        }
        if (!domainId) throw new Error('No domain available for indexing');
        const res = await fetch(`${this.baseUrl}/api/v1/domains/${domainId}/index`, {
            method: 'POST',
        });
        if (!res.ok) throw new Error('Failed to start indexer');
        return res.json();
    }

    // GET /api/v1/indexer/status
    async getIndexerStatus() {
        const res = await fetch(`${this.baseUrl}/api/v1/indexer/status`);
        if (!res.ok) throw new Error('Failed to get indexer status');
        return res.json();
    }
}

const api = new ChatAPI();
