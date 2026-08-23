// Vaults API methods

// Extracts a human-readable error message from a non-2xx response.
// Handles two FastAPI shapes:
//   - HTTPException(detail="...")        -> detail is a string
//   - RequestValidationError             -> detail is an array of {loc, msg, ...}
async function readErrorMessage(response, fallbackOp) {
    const fallback = `Failed to ${fallbackOp}: ${response.statusText}`;
    let body = null;
    try {
        body = await response.json();
    } catch {
        return fallback;
    }
    const detail = body?.detail;
    if (typeof detail === 'string' && detail) return detail;
    if (Array.isArray(detail)) {
        const parts = detail.map(e => {
            const loc = Array.isArray(e?.loc)
                ? e.loc.filter(p => p !== 'body').join('.')
                : '';
            return loc ? `${loc}: ${e.msg}` : (e?.msg || '');
        }).filter(Boolean);
        if (parts.length) return parts.join('; ');
    }
    return fallback;
}

export const vaultsMixin = {
    async getVaults(domainId = null) {
        const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/vaults${qs}`);
        if (!response.ok) throw new Error(await readErrorMessage(response, 'get vaults'));
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
        if (!response.ok) throw new Error(await readErrorMessage(response, 'create vault'));
        return response.json();
    },

    async updateVault(vaultId, data) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(await readErrorMessage(response, 'update vault'));
        return response.json();
    },

    async deleteVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(await readErrorMessage(response, 'delete vault'));
    },

    async toggleVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/api/settings/vaults/${vaultId}/toggle`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(await readErrorMessage(response, 'toggle vault'));
        return response.json();
    },
};