// Pipeline API methods
export const pipelineMixin = {
    async lockPipeline(chatId, pipelineId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/lock_pipeline`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline_id: pipelineId }),
        });
        if (!response.ok) throw new Error(`Failed to lock pipeline: ${response.statusText}`);
        return response.json();
    },

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
    },

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
    },

    async getPipelines(domainId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId)   params.set('domain_id',   domainId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines${qs}`);
        if (!response.ok) throw new Error(`Failed to get pipelines: ${response.statusText}`);
        return response.json();
    },

    async getPipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`);
        if (!response.ok) throw new Error(`Failed to get pipeline: ${response.statusText}`);
        return response.json();
    },

    async createPipeline(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create pipeline: ${response.statusText}`);
        return response.json();
    },

    async updatePipeline(pipelineId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update pipeline: ${response.statusText}`);
        return response.json();
    },

    async activatePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate pipeline: ${response.statusText}`);
        return response.json();
    },

    async deactivatePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate pipeline: ${response.statusText}`);
        return response.json();
    },

    async deletePipeline(pipelineId) {
        const response = await fetch(`${this.baseUrl}/api/settings/pipelines/${pipelineId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete pipeline: ${response.statusText}`);
    },
};
