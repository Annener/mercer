// Documents & Indexer API methods
export const documentsMixin = {
    async getDocuments(vaultId = null, domainId = null) {
        const params = new URLSearchParams();
        if (vaultId)  params.set('vault_id',  vaultId);
        if (domainId) params.set('domain_id', domainId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents${qs}`);
        if (!response.ok) throw new Error(`Failed to get documents: ${response.statusText}`);
        return response.json();
    },

    async getSettingsDocuments({ vaultId = null, domainId = null, status = null, tagId = null } = {}) {
        const params = new URLSearchParams();
        if (vaultId)  params.set('vault_id',  vaultId);
        if (domainId) params.set('domain_id', domainId);
        if (status)   params.set('status',    status);
        if (tagId)    params.set('tag_id',    tagId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents${qs}`);
        if (!response.ok) throw new Error(`Failed to get documents: ${response.statusText}`);
        return response.json();
    },

    async deleteDocument(documentId) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
    },

    async deleteDocumentById(documentId, vaultId = null) {
        const params = new URLSearchParams();
        if (vaultId) params.set('vault_id', vaultId);
        const qs = params.toString() ? `?${params}` : '';
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}${qs}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to delete document: ${response.statusText}`);
    },

    async updateDocumentLabels(documentId, tagIds) {
        const response = await fetch(`${this.baseUrl}/api/settings/documents/${encodeURIComponent(documentId)}/labels`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: tagIds }),
        });
        if (!response.ok) throw new Error(`Failed to update document labels: ${response.statusText}`);
        return response.json();
    },

    async runIndexer(domainId = null) {
        if (!domainId) {
            try {
                const resp = await this.getDomains();
                const list = Array.isArray(resp) ? resp : (resp.domains || []);
                const first = list.find(d => d.enabled !== false) || list[0];
                domainId = first ? (first.domain_id || first.id || null) : null;
            } catch (_) {}
        }
        if (!domainId) throw new Error('No active domain found to run indexer');
        const response = await fetch(`${this.baseUrl}/api/v1/domains/${encodeURIComponent(domainId)}/index`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to run indexer: ${response.statusText}`);
        return response.json();
    },

    async getIndexTaskState(taskId) {
        const response = await fetch(`${this.baseUrl}/index-tasks/${encodeURIComponent(taskId)}/state`);
        if (!response.ok) throw new Error(`Failed to get index task state: ${response.statusText}`);
        return response.json();
    },

    /**
     * Глобальный системный статус индексации — не требует task_id.
     * Возвращает все активные задачи + последнюю завершённую.
     * Используется для инициализации панели «Состояние индексации» при открытии вкладки Файлы.
     *
     * Response: { tasks: [...], has_active: bool }
     */
    async getSystemIndexState() {
        const response = await fetch(`${this.baseUrl}/api/v1/indexer/tasks`);
        if (!response.ok) throw new Error(`Failed to get system index state: ${response.statusText}`);
        return response.json();
    },

    /**
     * Запрашивает отмену задачи индексации через backend.
     * Backend устанавливает cancel:{task_id} в Redis;
     * воркер rag-indexer проверяет флаг и завершает задачу.
     */
    async cancelIndexTask(taskId) {
        const response = await fetch(
            `${this.baseUrl}/api/v1/indexer/tasks/${encodeURIComponent(taskId)}/cancel`,
            { method: 'POST' },
        );
        // Graceful fallback: если endpoint вернул ошибку — не ломаем UI
        if (!response.ok) {
            logger?.warn?.(`cancelIndexTask: server returned ${response.status}`);
            return { cancelled: false, task_id: taskId };
        }
        return response.json();
    },
};
