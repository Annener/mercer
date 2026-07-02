// Campaigns & Tags API methods
export const campaignsMixin = {
    async getCampaigns(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns${qs}`);
        if (!response.ok) throw new Error(`Failed to get campaigns: ${response.statusText}`);
        return response.json();
    },

    async getCampaign(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`);
        if (!response.ok) throw new Error(`Failed to get campaign: ${response.statusText}`);
        return response.json();
    },

    async createCampaign(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create campaign: ${response.statusText}`);
        return response.json();
    },

    async updateCampaign(campaignId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update campaign: ${response.statusText}`);
        return response.json();
    },

    async deleteCampaign(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete campaign: ${response.statusText}`);
    },

    async getCampaignTags(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`);
        if (!response.ok) throw new Error(`Failed to get campaign tags: ${response.statusText}`);
        return response.json();
    },

    async createCampaignTag(campaignId, payload) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed to create campaign tag: ${response.statusText}`);
        return response.json();
    },

    async getCampaignGlobalTags(campaignId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/global-tags`);
        if (!response.ok) throw new Error(`Failed to get campaign global tags: ${response.statusText}`);
        return response.json();
    },

    async linkCampaignGlobalTag(campaignId, tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/global-tags/${tagId}`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to link global tag: ${response.statusText}`);
        return response.json();
    },

    async unlinkCampaignGlobalTag(campaignId, tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/campaigns/${campaignId}/global-tags/${tagId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to unlink global tag: ${response.statusText}`);
    },

    async getTags(domainId = null, vaultId = null, campaignId = null) {
        const params = new URLSearchParams();
        if (domainId)   params.set('domain_id',   domainId);
        if (vaultId)    params.set('vault_id',     vaultId);
        if (campaignId) params.set('campaign_id', campaignId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/tags${qs}`);
        if (!response.ok) throw new Error(`Failed to get tags: ${response.statusText}`);
        return response.json();
    },

    async createTag(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create tag: ${response.statusText}`);
        return response.json();
    },

    async updateTag(tagId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags/${tagId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update tag: ${response.statusText}`);
        return response.json();
    },

    async deleteTag(tagId) {
        const response = await fetch(`${this.baseUrl}/api/settings/tags/${tagId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete tag: ${response.statusText}`);
    },
};
