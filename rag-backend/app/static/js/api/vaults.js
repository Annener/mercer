// Vaults API methods
export const vaultsMixin = {
    async getVaults(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/vaults${qs}`);
        if (!response.ok) throw new Error(`Failed to get vaults: ${response.statusText}`);
        return response.json();
    },

    async getSettingsVaults(domainId = null) {
        return this.getVaults(domainId);
    },

    async createVault(data) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to create vault: ${response.statusText}`);
        return response.json();
    },

    async updateVault(vaultId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update vault: ${response.statusText}`);
        return response.json();
    },

    async deleteVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete vault: ${response.statusText}`);
    },

    async toggleVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to toggle vault: ${response.statusText}`);
        return response.json();
    },
};
