// Generation, Embedding, Rerank Models API methods
export const modelsMixin = {
    // === Generation Models ===

    async getGenerationModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation`);
        if (!response.ok) throw new Error(`Failed to get generation models: ${response.statusText}`);
        return response.json();
    },

    async createGenerationModel(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create generation model: ${response.statusText}`);
        return response.json();
    },

    async updateGenerationModel(modelId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update generation model: ${response.statusText}`);
        return response.json();
    },

    async deleteGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete generation model: ${response.statusText}`);
    },

    async setActiveGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate generation model: ${response.statusText}`);
        return response.json();
    },

    async deactivateGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate generation model: ${response.statusText}`);
        return response.json();
    },

    async toggleGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle generation model: ${response.statusText}`);
        return response.json();
    },

    async checkGenerationModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/generation/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check generation model: ${response.statusText}`);
        return response.json();
    },

    // === Embedding Models ===

    async getEmbeddingModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding`);
        if (!response.ok) throw new Error(`Failed to get embedding models: ${response.statusText}`);
        return response.json();
    },

    async createEmbeddingModel(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create embedding model: ${response.statusText}`);
        return response.json();
    },

    async updateEmbeddingModel(modelId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update embedding model: ${response.statusText}`);
        return response.json();
    },

    async deleteEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete embedding model: ${response.statusText}`);
    },

    async toggleEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle embedding model: ${response.statusText}`);
        return response.json();
    },

    async checkEmbeddingModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/embedding/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check embedding model: ${response.statusText}`);
        return response.json();
    },

    // === Rerank Models ===

    async getRerankModels() {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank`);
        if (!response.ok) throw new Error(`Failed to get rerank models: ${response.statusText}`);
        return response.json();
    },

    async createRerankModel(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create rerank model: ${response.statusText}`);
        return response.json();
    },

    async updateRerankModel(modelId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update rerank model: ${response.statusText}`);
        return response.json();
    },

    async deleteRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete rerank model: ${response.statusText}`);
    },

    async checkRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/check`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to check rerank model: ${response.statusText}`);
        return response.json();
    },

    async setActiveRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/activate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to activate rerank model: ${response.statusText}`);
        return response.json();
    },

    async activateRerankModel(modelId) {
        return this.setActiveRerankModel(modelId);
    },

    async deactivateRerankModel(modelId) {
        const response = await fetch(`${this.baseUrl}/api/settings/models/rerank/${encodeURIComponent(modelId)}/deactivate`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to deactivate rerank model: ${response.statusText}`);
        return response.json();
    },

    async toggleRerankModel(modelId) {
        const current = await this.getRerankModels();
        const model = (Array.isArray(current) ? current : []).find(m => m.model_id === modelId);
        if (!model) throw new Error('Rerank model not found');
        return this.updateRerankModel(modelId, { enabled: !(model.enabled !== false) });
    },
};
