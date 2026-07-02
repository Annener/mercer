// Settings API methods
export const settingsMixin = {
    async getSettingsStatus() {
        const response = await fetch(`${this.baseUrl}/api/settings/status`);
        if (!response.ok) throw new Error(`Failed to get settings status: ${response.statusText}`);
        return response.json();
    },

    async getSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/params`);
        if (!response.ok) throw new Error(`Failed to get settings params: ${response.statusText}`);
        return response.json();
    },

    async updateSettingsParam(key, value) {
        const response = await fetch(`${this.baseUrl}/api/settings/params/${encodeURIComponent(key)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
        if (!response.ok) throw new Error(`Failed to update param: ${response.statusText}`);
        return response.json();
    },

    async resetSettingsParams() {
        const response = await fetch(`${this.baseUrl}/api/settings/params/reset`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reset params: ${response.statusText}`);
        return response.json();
    },

    async getConfig() {
        const response = await fetch(`${this.baseUrl}/config`);
        if (!response.ok) throw new Error(`Failed to get config: ${response.statusText}`);
        return response.json();
    },

    async updateConfig(data) {
        const response = await fetch(`${this.baseUrl}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`Failed to update config: ${response.statusText}`);
        return response.json();
    },

    async getWatchdogSettings() {
        const res = await fetch('/api/v1/settings/watchdog');
        if (!res.ok) throw new Error('Failed to load watchdog settings');
        return res.json();
    },

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
    },
};
