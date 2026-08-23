// Campaigns & Tags API methods

/**
 * Типизированная ошибка для Initial State endpoints.
 * Хранит HTTP-статус и `detail` от сервера (строка или объект).
 *
 * Для snapshot_stale backend возвращает 409 с detail = { code, stale_documents: [...] } —
 * эти поля доступны через `err.detail.code` и `err.detail.stale_documents`.
 */
export class InitialStateApiError extends Error {
    constructor(status, detail) {
        const msg = typeof detail === 'string'
            ? `Initial State API ${status}: ${detail}`
            : `Initial State API ${status}: ${JSON.stringify(detail)}`;
        super(msg);
        this.name = 'InitialStateApiError';
        this.status = status;
        this.detail = detail;
    }

    /**
     * Удобный предикат: `err.isCode('source_snapshot_stale')`.
     * Поддерживает как string-detail (старый формат), так и object-detail (snapshot_stale).
     */
    isCode(code) {
        if (typeof this.detail === 'string') {
            return this.detail === code;
        }
        if (this.detail && typeof this.detail === 'object' && typeof this.detail.code === 'string') {
            return this.detail.code === code;
        }
        return false;
    }

    /** Список doc_id для snapshot_stale (пустой массив если неприменимо). */
    staleDocuments() {
        if (this.detail
            && typeof this.detail === 'object'
            && Array.isArray(this.detail.stale_documents)) {
            return this.detail.stale_documents;
        }
        return [];
    }
}

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

// -----------------------------------------------------------------------
    // Initial State (Stage 3) endpoints
    // ---------------------------------------------------------------------------

    /**
     * Сформировать LLM-proposal Initial State из выбранных Markdown-документов.
     *
     * POST /api/settings/campaigns/{cid}/state/initial/preview
     * Body: { document_ids: string[], propose_fields?: boolean,
     *         max_suggested_fields?: number }
     *
     * Параметр opts (опционально):
     *   - propose_fields (boolean, default false) — Stage 3.v2: разрешает LLM
     *     предложить новые поля через suggested_fields[]. При 0 enabled-полей
     *     кампании и propose_fields=false сервис вернёт 422.
     *   - max_suggested_fields (number, default 15) — soft cap.
     *
     * На успех возвращает CampaignStateInitialProposalReadV2: всегда содержит
     * `proposal.suggested_fields` (возможно, пустой массив).
     * На ошибку бросает InitialStateApiError со специфическим status.
     */
    async previewInitialState(campaignId, documentIds, opts = null) {
        const body = { document_ids: documentIds };
        if (opts && typeof opts === 'object') {
            if (typeof opts.propose_fields === 'boolean') {
                body.propose_fields = opts.propose_fields;
            }
            if (Number.isFinite(opts.max_suggested_fields)) {
                body.max_suggested_fields = opts.max_suggested_fields;
            }
        }
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state/initial/preview`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            }
        );
        return this._parseInitialStateResponse(response);
    },

    /**
     * Получить текущий Initial State proposal из Redis.
     *
     * GET /api/settings/campaigns/{cid}/state/initial
     * Возвращает CampaignStateInitialProposalRead или null (нет/истёк).
     * Бросает InitialStateApiError на ошибку (404 campaign_not_found и т.п.).
     */
    async getInitialStateProposal(campaignId) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state/initial`
        );
        if (response.status === 404) {
            // 404 может означать либо нет proposal (не ошибка), либо кампания не найдена.
            // Сервер различает: при отсутствии proposal возвращает 200 + null.
            // Если 404 — это именно ошибка (campaign_not_found), пробрасываем.
            const detail = await this._readDetail(response);
            throw new InitialStateApiError(404, detail);
        }
        return this._parseInitialStateResponse(response);
    },

    /**
     * Применить Initial State proposal (review/approval).
     *
     * POST /api/settings/campaigns/{cid}/state/initial/apply
     * Body: { proposal_id, config_version, proposal_overrides?,
     *         accepted_suggested_field_keys?, rejected_suggested_field_keys? }
     * На успех возвращает CampaignStateVersionRead с state_version=1, source_kind='initial'.
     *
     * `proposalOverrides` — необязательный proposal с правками пользователя
     * (отредактированный single_value / list_value.items). На бэкенде мерджится
     * поверх proposal из Redis по field_key.
     *
     * `acceptedSuggestedFieldKeys` / `rejectedSuggestedFieldKeys` — массивы
     * строк (Stage 3.v2). Сервер создаст поля с принятыми ключами перед
     * apply_initial. Отклонённые ключи просто игнорируются.
     */
    async applyInitialState(
        campaignId,
        proposalId,
        configVersion,
        proposalOverrides = null,
        acceptedSuggestedFieldKeys = null,
        rejectedSuggestedFieldKeys = null,
    ) {
        const body = {
            proposal_id: proposalId,
            config_version: configVersion,
        };
        if (proposalOverrides && typeof proposalOverrides === 'object') {
            body.proposal_overrides = proposalOverrides;
        }
        if (Array.isArray(acceptedSuggestedFieldKeys)) {
            body.accepted_suggested_field_keys = acceptedSuggestedFieldKeys;
        }
        if (Array.isArray(rejectedSuggestedFieldKeys)) {
            body.rejected_suggested_field_keys = rejectedSuggestedFieldKeys;
        }
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state/initial/apply`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            }
        );
        return this._parseInitialStateResponse(response);
    },

    async _parseInitialStateResponse(response) {
        if (!response.ok) {
            const detail = await this._readDetail(response);
            throw new InitialStateApiError(response.status, detail);
        }
        return response.json();
    },

    async _readDetail(response) {
        try {
            const data = await response.json();
            return data && typeof data === 'object' && 'detail' in data ? data.detail : data;
        } catch (_) {
            return response.statusText;
        }
    },

    // -----------------------------------------------------------------------
    // Campaign State — Stage 1+2 endpoints (используются tab-campaigns для
    // определения условий показа Initial State UI).
    // -----------------------------------------------------------------------

    /**
     * Список полей Campaign State (Stage 1).
     * GET /api/settings/campaigns/{cid}/state-fields
     * Возвращает CampaignStateFieldConfigRead[] (отсортирован по display_order).
     */
    async getStateFields(campaignId) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state-fields`
        );
        if (!response.ok) {
            throw new Error(`Failed to get state fields: ${response.statusText}`);
        }
        return response.json();
    },

    /**
     * Активная версия Campaign State (Stage 2).
     * GET /api/settings/campaigns/{cid}/state
     * Возвращает CampaignStateVersionRead или null (если versions ещё нет).
     */
    async getActiveCampaignState(campaignId) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state`
        );
        if (!response.ok) {
            throw new Error(`Failed to get active state: ${response.statusText}`);
        }
        return response.json();
    },

    /**
     * Создать поле Campaign State.
     * POST /api/settings/campaigns/{cid}/state-fields
     * Body: { key, label, description?, mode, enabled?, display_order? }
     */
    async createStateField(campaignId, payload) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state-fields`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            const detail = err && 'detail' in err ? err.detail : err;
            throw new InitialStateApiError(response.status, detail);
        }
        return response.json();
    },

    /**
     * Обновить поле Campaign State (label/description/enabled/display_order).
     * PUT /api/settings/campaigns/{cid}/state-fields/{fid}
     * key и mode — immutable (бэкенд вернёт 409 если попробовать).
     */
    async updateStateField(campaignId, fieldId, payload) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state-fields/${fieldId}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            const detail = err && 'detail' in err ? err.detail : err;
            throw new InitialStateApiError(response.status, detail);
        }
        return response.json();
    },

    /**
     * Удалить поле Campaign State.
     * DELETE /api/settings/campaigns/{cid}/state-fields/{fid}
     * 409 если на поле ссылаются значения state (поле уже использовалось).
     */
    async deleteStateField(campaignId, fieldId) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state-fields/${fieldId}`,
            { method: 'DELETE' }
        );
        if (!response.ok && response.status !== 204) {
            const err = await response.json().catch(() => ({}));
            const detail = err && 'detail' in err ? err.detail : err;
            throw new InitialStateApiError(response.status, detail);
        }
    },

    /**
     * Переупорядочить поля Campaign State.
     * POST /api/settings/campaigns/{cid}/state-fields/reorder
     * Body: { field_ids: string[] } (полный список ID в нужном порядке).
     */
    async reorderStateFields(campaignId, orderedFieldIds) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state-fields/reorder`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ field_ids: orderedFieldIds }),
            }
        );
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            const detail = err && 'detail' in err ? err.detail : err;
            throw new InitialStateApiError(response.status, detail);
        }
        return response.json();
    },

    // -----------------------------------------------------------------------
    // Stage 6: Effective context — debug view скомпилированного prompt.
    // -----------------------------------------------------------------------

    /**
     * Получить effective-context для кампании.
     * GET /api/settings/campaigns/{cid}/effective-context?chat_id=...
     * Возвращает EffectiveContextRead: blocks[], total_tokens, budget, truncated_fields.
     */
    async getEffectiveContext(campaignId, chatId = null) {
        const qs = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : '';
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/effective-context${qs}`
        );
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            const detail = err && 'detail' in err ? err.detail : err;
            throw new InitialStateApiError(response.status, detail);
        }
        return response.json();
    },

    // -----------------------------------------------------------------------
    // Stage 7: potentially_stale signal
    // -----------------------------------------------------------------------

    /**
     * Получить текущий stale-статус Campaign State.
     *
     * GET /api/settings/campaigns/{cid}/state/stale-status
     * Возвращает CampaignStateStaleStatus: {
     *   potentially_stale: boolean,
     *   stale_documents: string[],
     *   active_state_version: number | null,
     *   checked_at: ISO-8601 string,
     * }
     *
     * 404 — кампания не найдена.
     * 200 + potentially_stale=false — нормальный случай (state свежий
     * или ещё не применён).
     */
    async getStateStaleStatus(campaignId) {
        const response = await fetch(
            `${this.baseUrl}/api/settings/campaigns/${campaignId}/state/stale-status`
        );
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            const detail = err && 'detail' in err ? err.detail : err;
            throw new InitialStateApiError(response.status, detail);
        }
        return response.json();
    },
};
