// API клиент для работы с backend
class ChatAPI {
    constructor() {
        this.baseUrl = '';
        this.indexerUrl = 'http://localhost:9000';
        this.indexerWsUrl = `ws://${window.location.hostname}:9000`;
    }

    // === Chat API ===

    async createChat(vaultId = null, domainId = null) {
        const response = await fetch(`${this.baseUrl}/chat/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                vault_id: vaultId,
                domain_id: domainId,
            }),
        });
        if (!response.ok) {
            throw new Error(`Failed to create chat: ${response.statusText}`);
        }
        return response.json();
    }

    async listChats(domainId = null) {
        const url = new URL(`${this.baseUrl}/chat/list`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        const response = await fetch(url.toString());
        if (!response.ok) throw new Error(`Failed to list chats: ${response.statusText}`);
        return response.json();
    }

    async getChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`);
        if (!response.ok) throw new Error(`Failed to get chat: ${response.statusText}`);
        return response.json();
    }

    async deleteChat(chatId) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`Failed to delete chat: ${response.statusText}`);
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

    async sendMessage(chatId, content, stream = true) {
        const response = await fetch(`${this.baseUrl}/chat/${chatId}/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content, stream }),
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Failed to send message: ${response.statusText}`);
        }
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('text/event-stream')) {
            return response.body;
        }
        return response.json();
    }

    // === Config API ===

    async getDomains() {
        const response = await fetch(`${this.baseUrl}/config/domains`);
        if (!response.ok) throw new Error(`Failed to load domains: ${response.statusText}`);
        return response.json();
    }

    async getVaults(domainId = null, search = null) {
        const url = new URL(`${this.baseUrl}/config/vaults`, window.location.origin);
        if (domainId) url.searchParams.set('domain_id', domainId);
        if (search) url.searchParams.set('search', search);
        const response = await fetch(url.toString());
        if (!response.ok) throw new Error(`Failed to load vaults: ${response.statusText}`);
        return response.json();
    }

    // === DB Management API ===

    async listDocuments(vaultId, limit = 100, offset = 0) {
        const params = new URLSearchParams({
            vault_id: vaultId,
            limit: String(limit),
            offset: String(offset),
        });
        const response = await fetch(`${this.baseUrl}/db/documents?${params}`);
        if (!response.ok) throw new Error(`Failed to list documents: ${response.statusText}`);
        return response.json();
    }

    async listDocumentChunks(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(`${this.baseUrl}/db/docs/${encodeURIComponent(documentId)}/chunks?${params}`);
        if (!response.ok) throw new Error(`Failed to list chunks: ${response.statusText}`);
        return response.json();
    }

    async deleteDocument(documentId, vaultId) {
        const params = new URLSearchParams({ vault_id: vaultId });
        const response = await fetch(
            `${this.baseUrl}/db/docs/${encodeURIComponent(documentId)}?${params}`,
            { method: 'DELETE' },
        );
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
        return response.json();
    }

    async textSearch(vaultId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/db/search/text`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vault_id: vaultId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search: ${response.statusText}`);
        return response.json();
    }

    async textSearchByDomain(domainId, queryText, limit = 20) {
        const response = await fetch(`${this.baseUrl}/db/search/text/by-domain`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain_id: domainId, query_text: queryText, limit }),
        });
        if (!response.ok) throw new Error(`Failed to search: ${response.statusText}`);
        return response.json();
    }

    async reindexVault(vaultId, forceReindex = false) {
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/reindex`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_reindex: forceReindex }),
        });
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Failed to start indexing: ${text}`);
        }
        return response.json();
    }

    async detachVault(vaultId) {
        const response = await fetch(`${this.baseUrl}/vaults/${encodeURIComponent(vaultId)}/detach`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to detach vault: ${response.statusText}`);
        return response.json();
    }

    async cancelIndexTask(taskId) {
        const response = await fetch(
            `${this.indexerUrl}/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`,
            { method: 'POST' },
        );
        if (!response.ok) throw new Error(`Failed to cancel task: ${response.statusText}`);
        return response.json();
    }

    connectToTaskStream(taskId) {
        const url = `${this.indexerWsUrl}/api/v1/tasks/${encodeURIComponent(taskId)}/stream`;
        return new WebSocket(url);
    }
}

const chatAPI = new ChatAPI();