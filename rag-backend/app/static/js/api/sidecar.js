// Sidecar API methods
export const sidecarMixin = {
    async getSidecarStatus() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/status`);
        if (!res.ok) {
            return { running: false, installed: false, agent_unavailable: true };
        }
        return res.json();
    },

    async sidecarStart() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/start`, { method: 'POST' });
        if (!res.ok) {
            let detail = res.statusText;
            try { detail = (await res.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return res.json();
    },

    async sidecarStop() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/stop`, { method: 'POST' });
        if (!res.ok) {
            let detail = res.statusText;
            try { detail = (await res.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return res.json();
    },

    async sidecarRestart() {
        const res = await fetch(`${this.baseUrl}/api/settings/sidecar/restart`, { method: 'POST' });
        if (!res.ok) {
            let detail = res.statusText;
            try { detail = (await res.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        return res.json();
    },

    getSidecarInstallStreamUrl() {
        return `${this.baseUrl}/api/settings/sidecar/install/stream`;
    },
};
