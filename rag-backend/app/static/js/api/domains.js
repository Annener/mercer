// Domains API methods
export const domainsMixin = {
    async getDomains() {
        const response = await fetch(`${this.baseUrl}/config/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    },

    async getSettingsDomains() {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`);
        if (!response.ok) throw new Error(`Failed to get domains: ${response.statusText}`);
        return response.json();
    },

    async getDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}`);
        if (!response.ok) throw new Error(`Failed to get domain: ${response.statusText}`);
        return response.json();
    },

    async createDomain(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create domain: ${response.statusText}`);
        return response.json();
    },

    async updateDomain(domainId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update domain: ${response.statusText}`);
        return response.json();
    },

    async deleteDomain(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete domain: ${response.statusText}`);
    },

    async getDomainPrompts(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/prompts`);
        if (!response.ok) throw new Error(`Failed to get domain prompts: ${response.statusText}`);
        return response.json();
    },

    async updateDomainPrompt(domainId, promptType, content) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/prompts/${promptType}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        if (!response.ok) throw new Error(`Failed to update domain prompt: ${response.statusText}`);
        return response.json();
    },

    async getDomainFields(domainId) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/fields`);
        if (!response.ok) throw new Error(`Failed to get domain fields: ${response.statusText}`);
        return response.json();
    },

    async updateDomainFields(domainId, fields) {
        const response = await fetch(`${this.baseUrl}/api/settings/domains/${domainId}/fields`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(fields),
        });
        if (!response.ok) throw new Error(`Failed to update domain fields: ${response.statusText}`);
        return response.json();
    },
};
