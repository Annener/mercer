// Update Mode API methods
export const updateModeMixin = {
    /**
     * POST /api/chats/{chatId}/update-mode/start
     * Body: { note: string }
     * Returns: StartUpdateModeResponse
     */
    async updateModeStart(chatId, note) {
        const response = await fetch(`${this.baseUrl}/api/chats/${chatId}/update-mode/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            let errCode = null;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
                errCode = typeof errData.detail === 'string' ? errData.detail : null;
            } catch (_) {}
            const err = new Error(errMsg);
            err.status = response.status;
            err.code = errCode;
            throw err;
        }
        return response.json();
    },

    /**
     * GET /api/chats/{chatId}/update-mode/session
     * Returns: UpdateModeSessionResponse | null (410 → null)
     */
    async updateModeGetSession(chatId) {
        const response = await fetch(`${this.baseUrl}/api/chats/${chatId}/update-mode/session`);
        if (response.status === 410) return null;
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {}
            const err = new Error(errMsg);
            err.status = response.status;
            throw err;
        }
        return response.json();
    },

    /**
     * PATCH /api/chats/{chatId}/update-mode/review
     * Body: { accepted_change_ids: string[], rejected_change_ids: string[] }
     * Returns: UpdateModeSessionResponse
     */
    async updateModeReview(chatId, acceptedIds, rejectedIds) {
        const response = await fetch(`${this.baseUrl}/api/chats/${chatId}/update-mode/review`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                accepted_change_ids: acceptedIds,
                rejected_change_ids: rejectedIds,
            }),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {}
            const err = new Error(errMsg);
            err.status = response.status;
            throw err;
        }
        return response.json();
    },

    /**
     * POST /api/chats/{chatId}/update-mode/apply
     * Body: { apply_id?: string }
     * Returns: ApplyUpdateModeResponse
     */
    async updateModeApply(chatId, applyId = null) {
        const body = {};
        if (applyId) body.apply_id = applyId;
        const response = await fetch(`${this.baseUrl}/api/chats/${chatId}/update-mode/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {}
            const err = new Error(errMsg);
            err.status = response.status;
            throw err;
        }
        return response.json();
    },

    /**
     * DELETE /api/chats/{chatId}/update-mode/session
     * Returns: CancelUpdateModeResponse
     */
    async updateModeCancel(chatId) {
        const response = await fetch(`${this.baseUrl}/api/chats/${chatId}/update-mode/session`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            let errMsg = response.statusText;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.message || errMsg;
            } catch (_) {}
            const err = new Error(errMsg);
            err.status = response.status;
            throw err;
        }
        return response.json();
    },
};
