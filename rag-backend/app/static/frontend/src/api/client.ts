import { HttpClient, HttpError } from './http';

export { HttpError };
import * as T from './types';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function requireUUID(value: string | null | undefined, name: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${name} is required (got ${typeof value}: ${String(value)})`);
  }
  if (!UUID_RE.test(value)) {
    throw new Error(`${name} is not a valid UUID: ${value}`);
  }
  return value;
}

/**
 * Главный API-клиент Mercer. Агрегирует все доменные методы.
 *
 * Используется через:
 *   import { api } from '@/api/client';
 *   const chats = await api.listChats('dnd');
 *
 * Все методы возвращают Promise<T> (типизированные ответы) и бросают HttpError
 * при не-2xx ответе. Для Initial State — HttpError с detail.code для машинной
 * обработки (snapshot_stale, proposal_expired и т.п.).
 */
export class MercerAPI extends HttpClient {
  // ============================================================
  // Chat
  // ============================================================

  async createChat(domainId: T.DomainId | null, campaignId?: T.CampaignId | null): Promise<T.Chat> {
    return this.post<T.Chat>('/chat/create', {
      domain_id: domainId,
      campaign_id: campaignId ?? null,
    });
  }

  async listChats(
    domainId?: T.DomainId | null,
    campaignId?: T.CampaignId | null,
  ): Promise<{ chats: T.Chat[] }> {
    const params = new URLSearchParams();
    if (domainId) params.set('domain_id', domainId);
    // campaignId === '' (или '__none__') — семантически "общий режим",
    // отправляем как '__none__' на бэкенд для фильтра по NULL.
    if (campaignId !== undefined && campaignId !== null) {
      const value = campaignId === '' ? '__none__' : campaignId;
      params.set('campaign_id', value);
    }
    const qs = params.toString() ? `?${params}` : '';
    return this.get<{ chats: T.Chat[] }>(`/chat/list${qs}`);
  }

  async getChat(chatId: T.UUID): Promise<T.ChatDetail> {
    return this.get<T.ChatDetail>(`/chat/${chatId}/history`);
  }

  async getChatHistory(chatId: T.UUID): Promise<T.ChatDetail> {
    return this.getChat(chatId);
  }

  async renameChat(chatId: T.UUID, title: string): Promise<unknown> {
    return this.post(`/chat/${chatId}/rename`, { title });
  }

  async updateChatTitle(chatId: T.UUID, title: string): Promise<unknown> {
    return this.put(`/chat/${chatId}/title`, { title });
  }

  async updateChat(chatId: T.UUID, data: Partial<T.Chat>): Promise<unknown> {
    return this.patch(`/chat/${chatId}`, data);
  }

  async deleteChat(chatId: T.UUID): Promise<void> {
    return this.delete(`/chat/${chatId}`);
  }

  async sendMessage(
    chatId: T.UUID,
    content: string,
    stream = true,
    signal?: AbortSignal,
  ): Promise<ReadableStream<Uint8Array> | T.SendMessageResponse> {
    const url = stream ? `/chat/${chatId}/send_stream` : `/chat/${chatId}/send`;
    const body = stream ? { content, stream: true } : { content };
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: signal ?? null,
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new HttpError(
        response.status,
        errorBody?.detail ?? errorBody,
        response.statusText,
      );
    }
    if (stream) return response.body as ReadableStream<Uint8Array>;
    return (await response.json()) as T.SendMessageResponse;
  }

  async submitClarification(
    chatId: T.UUID,
    clarificationId: T.UUID,
    answers: Record<string, unknown>,
  ): Promise<unknown> {
    return this.post(`/chat/${chatId}/clarify`, {
      clarification_id: clarificationId,
      answers,
    });
  }

  async setFullDocMode(
    chatId: T.UUID,
    enabled: boolean,
    campaignId: T.CampaignId | null = null,
  ): Promise<unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    const body: Record<string, unknown> = { full_document_mode_enabled: enabled };
    if (campaignId !== null) body.campaign_id = campaignId;
    return this.patch(`/chat/${validChatId}`, body);
  }

  async setContextUpdateMode(
    chatId: T.UUID,
    enabled: boolean,
    campaignId: T.CampaignId | null = null,
  ): Promise<unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    const body: Record<string, unknown> = { context_update_mode: enabled };
    if (campaignId !== null) body.campaign_id = campaignId;
    return this.patch(`/chat/${validChatId}`, body);
  }

  async setRagPrefill(
    chatId: T.UUID,
    enabled: boolean,
    campaignId: T.CampaignId | null = null,
  ): Promise<unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    const body: Record<string, unknown> = { rag_prefill_enabled: enabled };
    if (campaignId !== null) body.campaign_id = campaignId;
    return this.patch(`/chat/${validChatId}`, body);
  }

  async fullDocConfirm(
    chatId: T.UUID,
    selectedDocumentIds: T.DocumentId[],
  ): Promise<ReadableStream<Uint8Array> | unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    const response = await fetch(`/chat/${validChatId}/full_document_confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_document_ids: selectedDocumentIds }),
    });
    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new HttpError(
        response.status,
        errorBody?.detail ?? errorBody,
        response.statusText,
      );
    }
    const ct = response.headers.get('content-type') ?? '';
    if (ct.includes('text/event-stream')) return response.body;
    return response.json();
  }

  // ============================================================
  // Pipeline
  // ============================================================

  async lockPipeline(chatId: T.UUID, pipelineId: T.PipelineId | null): Promise<unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    return this.post(`/chat/${validChatId}/lock_pipeline`, { pipeline_id: pipelineId });
  }

  async pipelineConfirm(
    chatId: T.UUID,
    confirmToken: string,
    action: 'confirm' | 'cancel',
  ): Promise<ReadableStream<Uint8Array> | unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    return this.post(
      `/chat/${validChatId}/pipeline_confirm`,
      { confirm_token: confirmToken, confirmed: action === 'confirm' },
      { raw: true },
    );
  }

  async pipelineResume(
    chatId: T.UUID,
    resumeToken: string,
    action: 'resume' | 'cancel',
    feedback: string | null = null,
  ): Promise<ReadableStream<Uint8Array> | unknown> {
    const validChatId = requireUUID(chatId, 'chat_id');
    return this.post(
      `/chat/${validChatId}/pipeline_resume`,
      { resume_token: resumeToken, cancelled: action === 'cancel', user_feedback: feedback },
      { raw: true },
    );
  }

  async getPipelines(
    domainId?: T.DomainId | null,
    campaignId?: T.CampaignId | null,
  ): Promise<T.Pipeline[]> {
    const params = new URLSearchParams();
    if (domainId) params.set('domain_id', domainId);
    if (campaignId) params.set('campaign_id', campaignId);
    const qs = params.toString() ? `?${params}` : '';
    return this.get<T.Pipeline[]>(`/api/settings/pipelines${qs}`);
  }

  async getPipeline(pipelineId: T.PipelineId): Promise<T.Pipeline> {
    return this.get<T.Pipeline>(`/api/settings/pipelines/${pipelineId}`);
  }

  async createPipeline(data: Partial<T.Pipeline>): Promise<T.Pipeline> {
    return this.post<T.Pipeline>('/api/settings/pipelines', data);
  }

  async updatePipeline(pipelineId: T.PipelineId, data: Partial<T.Pipeline>): Promise<T.Pipeline> {
    return this.put<T.Pipeline>(`/api/settings/pipelines/${pipelineId}`, data);
  }

  async activatePipeline(pipelineId: T.PipelineId): Promise<unknown> {
    return this.post(`/api/settings/pipelines/${pipelineId}/activate`);
  }

  async deactivatePipeline(pipelineId: T.PipelineId): Promise<unknown> {
    return this.post(`/api/settings/pipelines/${pipelineId}/deactivate`);
  }

  async deletePipeline(pipelineId: T.PipelineId): Promise<void> {
    return this.delete(`/api/settings/pipelines/${pipelineId}`);
  }

  // ============================================================
  // Domains
  // ============================================================

  async getDomains(): Promise<T.Domain[] | { domains: T.Domain[] }> {
    return this.get<T.Domain[] | { domains: T.Domain[] }>('/config/domains');
  }

  async getSettingsDomains(): Promise<T.Domain[]> {
    return this.get<T.Domain[]>('/api/settings/domains');
  }

  async getDomain(domainId: T.DomainId): Promise<T.Domain> {
    return this.get<T.Domain>(`/api/settings/domains/${domainId}`);
  }

  async createDomain(data: Partial<T.Domain>): Promise<T.Domain> {
    return this.post<T.Domain>('/api/settings/domains', data);
  }

  async updateDomain(domainId: T.DomainId, data: Partial<T.Domain>): Promise<T.Domain> {
    return this.put<T.Domain>(`/api/settings/domains/${domainId}`, data);
  }

  async deleteDomain(domainId: T.DomainId): Promise<void> {
    return this.delete(`/api/settings/domains/${domainId}`);
  }

  async getDomainPrompts(domainId: T.DomainId): Promise<T.DomainPrompt[]> {
    return this.get<T.DomainPrompt[]>(`/api/settings/domains/${domainId}/prompts`);
  }

  async updateDomainPrompt(
    domainId: T.DomainId,
    promptType: T.PromptType,
    content: string,
  ): Promise<T.DomainPrompt> {
    return this.put<T.DomainPrompt>(
      `/api/settings/domains/${domainId}/prompts/${promptType}`,
      { content },
    );
  }

  async getDomainFields(domainId: T.DomainId): Promise<T.ClarificationField[]> {
    return this.get<T.ClarificationField[]>(`/api/settings/domains/${domainId}/fields`);
  }

  async updateDomainFields(
    domainId: T.DomainId,
    fields: T.ClarificationField[],
  ): Promise<unknown> {
    return this.put(`/api/settings/domains/${domainId}/fields`, fields);
  }

  // ============================================================
  // Vaults
  // ============================================================

  async getVaults(domainId?: T.DomainId | null): Promise<T.Vault[]> {
    const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
    return this.get<T.Vault[]>(`/api/settings/vaults${qs}`);
  }

  async getSettingsVaults(domainId?: T.DomainId | null): Promise<T.Vault[]> {
    return this.getVaults(domainId);
  }

  async getVault(vaultId: T.VaultId): Promise<T.Vault> {
    return this.get<T.Vault>(`/api/settings/vaults/${encodeURIComponent(vaultId)}`);
  }

  async createVault(data: T.CreateVaultRequest): Promise<T.Vault> {
    return this.post<T.Vault>('/api/settings/vaults', data);
  }

  async updateVault(vaultId: T.VaultId, data: T.UpdateVaultRequest): Promise<T.Vault> {
    return this.put<T.Vault>(`/api/settings/vaults/${vaultId}`, data);
  }

  async deleteVault(vaultId: T.VaultId): Promise<void> {
    return this.delete(`/api/settings/vaults/${vaultId}`);
  }

  async toggleVault(vaultId: T.VaultId): Promise<T.Vault> {
    return this.post<T.Vault>(`/api/settings/vaults/${vaultId}/toggle`);
  }

  // ============================================================
  // Campaigns
  // ============================================================

  async getCampaigns(domainId?: T.DomainId | null): Promise<T.Campaign[] | { campaigns: T.Campaign[] }> {
    const qs = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : '';
    return this.get(`/api/settings/campaigns${qs}`);
  }

  async getCampaign(campaignId: T.CampaignId): Promise<T.Campaign> {
    return this.get<T.Campaign>(`/api/settings/campaigns/${campaignId}`);
  }

  async createCampaign(data: T.CreateCampaignRequest): Promise<T.Campaign> {
    return this.post<T.Campaign>('/api/settings/campaigns', data);
  }

  async updateCampaign(campaignId: T.CampaignId, data: T.UpdateCampaignRequest): Promise<T.Campaign> {
    return this.put<T.Campaign>(`/api/settings/campaigns/${campaignId}`, data);
  }

  async deleteCampaign(campaignId: T.CampaignId): Promise<void> {
    return this.delete(`/api/settings/campaigns/${campaignId}`);
  }

  async getCampaignTags(campaignId: T.CampaignId): Promise<T.TagRead[]> {
    return this.get<T.TagRead[]>(`/api/settings/campaigns/${campaignId}/tags`);
  }

  async createCampaignTag(campaignId: T.CampaignId, payload: Partial<T.TagRead>): Promise<T.TagRead> {
    return this.post<T.TagRead>(`/api/settings/campaigns/${campaignId}/tags`, payload);
  }

  async getCampaignGlobalTags(campaignId: T.CampaignId): Promise<T.TagRead[]> {
    return this.get<T.TagRead[]>(`/api/settings/campaigns/${campaignId}/global-tags`);
  }

  async linkCampaignGlobalTag(campaignId: T.CampaignId, tagId: T.TagId): Promise<unknown> {
    return this.post(`/api/settings/campaigns/${campaignId}/global-tags/${tagId}`);
  }

  async unlinkCampaignGlobalTag(campaignId: T.CampaignId, tagId: T.TagId): Promise<void> {
    return this.delete(`/api/settings/campaigns/${campaignId}/global-tags/${tagId}`);
  }

  async getTags(
    domainId?: T.DomainId | null,
    vaultId?: T.VaultId | null,
    campaignId?: T.CampaignId | null,
  ): Promise<T.TagRead[] | T.TagsGrouped> {
    const params = new URLSearchParams();
    if (domainId) params.set('domain_id', domainId);
    if (vaultId) params.set('vault_id', vaultId);
    if (campaignId) params.set('campaign_id', campaignId);
    const qs = params.toString() ? `?${params}` : '';
    return this.get<T.TagRead[] | T.TagsGrouped>(`/api/settings/tags${qs}`);
  }

  async createTag(data: T.CreateTagRequest): Promise<T.TagRead> {
    return this.post<T.TagRead>('/api/settings/tags', data);
  }

  async updateTag(tagId: T.TagId, data: Partial<T.TagRead>): Promise<T.TagRead> {
    return this.put<T.TagRead>(`/api/settings/tags/${tagId}`, data);
  }

  async deleteTag(tagId: T.TagId): Promise<void> {
    return this.delete(`/api/settings/tags/${tagId}`);
  }

  // ============================================================
  // Campaign State — Stage 1 (fields config)
  // ============================================================

  async getStateFields(campaignId: T.CampaignId): Promise<T.StateFieldConfig[]> {
    return this.get<T.StateFieldConfig[]>(
      `/api/settings/campaigns/${campaignId}/state-fields`,
    );
  }

  async createStateField(
    campaignId: T.CampaignId,
    payload: T.CreateStateFieldRequest,
  ): Promise<T.StateFieldConfig> {
    return this.post<T.StateFieldConfig>(
      `/api/settings/campaigns/${campaignId}/state-fields`,
      payload,
    );
  }

  async updateStateField(
    campaignId: T.CampaignId,
    fieldId: T.UUID,
    payload: T.UpdateStateFieldRequest,
  ): Promise<T.StateFieldConfig> {
    return this.put<T.StateFieldConfig>(
      `/api/settings/campaigns/${campaignId}/state-fields/${fieldId}`,
      payload,
    );
  }

  async deleteStateField(campaignId: T.CampaignId, fieldId: T.UUID): Promise<void> {
    return this.delete(`/api/settings/campaigns/${campaignId}/state-fields/${fieldId}`);
  }

  async reorderStateFields(campaignId: T.CampaignId, orderedFieldIds: T.UUID[]): Promise<unknown> {
    return this.post(`/api/settings/campaigns/${campaignId}/state-fields/reorder`, {
      field_ids: orderedFieldIds,
    });
  }

  // ============================================================
  // Campaign State — Stage 2 (active version)
  // ============================================================

  async getActiveCampaignState(campaignId: T.CampaignId): Promise<T.CampaignStateVersion | null> {
    return this.get<T.CampaignStateVersion | null>(
      `/api/settings/campaigns/${campaignId}/state`,
    );
  }

  async patchCampaignState(
    campaignId: T.CampaignId,
    body: {
      base_state_version: number | null;
      config_version: number;
      operations: T.CampaignStatePatchOp[];
    },
  ): Promise<T.CampaignStatePatchResponse> {
    return this.post<T.CampaignStatePatchResponse>(
      `/api/settings/campaigns/${campaignId}/state/patch`,
      body,
    );
  }

  // ============================================================
  // Initial State — Stage 3
  // ============================================================

  async previewInitialState(
    campaignId: T.CampaignId,
    documentIds: T.DocumentId[],
    opts?: { propose_fields?: boolean; max_suggested_fields?: number },
  ): Promise<T.InitialProposalReadV2> {
    const body: Record<string, unknown> = { document_ids: documentIds };
    if (opts?.propose_fields !== undefined) body.propose_fields = opts.propose_fields;
    if (opts?.max_suggested_fields !== undefined) {
      body.max_suggested_fields = opts.max_suggested_fields;
    }
    return this.post<T.InitialProposalReadV2>(
      `/api/settings/campaigns/${campaignId}/state/initial/preview`,
      body,
    );
  }

  async getInitialStateProposal(campaignId: T.CampaignId): Promise<T.InitialProposalRead | null> {
    const response = await fetch(
      `/api/settings/campaigns/${campaignId}/state/initial`,
    );
    if (response.status === 404) {
      const detail = await response.json().catch(() => null);
      throw new HttpError(404, detail?.detail ?? detail, 'Not found');
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new HttpError(response.status, detail?.detail ?? detail, response.statusText);
    }
    return (await response.json()) as T.InitialProposalRead;
  }

  async applyInitialState(
    campaignId: T.CampaignId,
    proposalId: string,
    configVersion: number,
    proposalOverrides?: T.InitialProposal,
    acceptedSuggestedFieldKeys?: string[],
    rejectedSuggestedFieldKeys?: string[],
  ): Promise<T.CampaignStateVersion> {
    const body: Record<string, unknown> = {
      proposal_id: proposalId,
      config_version: configVersion,
    };
    if (proposalOverrides) body.proposal_overrides = proposalOverrides;
    if (acceptedSuggestedFieldKeys) {
      body.accepted_suggested_field_keys = acceptedSuggestedFieldKeys;
    }
    if (rejectedSuggestedFieldKeys) {
      body.rejected_suggested_field_keys = rejectedSuggestedFieldKeys;
    }
    return this.post<T.CampaignStateVersion>(
      `/api/settings/campaigns/${campaignId}/state/initial/apply`,
      body,
    );
  }

  // ============================================================
  // Stage 6: Effective context debug
  // ============================================================

  async getEffectiveContext(
    campaignId: T.CampaignId,
    chatId?: T.UUID | null,
  ): Promise<T.EffectiveContextRead> {
    const qs = chatId ? `?chat_id=${encodeURIComponent(chatId)}` : '';
    return this.get<T.EffectiveContextRead>(
      `/api/settings/campaigns/${campaignId}/effective-context${qs}`,
    );
  }

  // ============================================================
  // Stage 7: Stale status
  // ============================================================

  async getStateStaleStatus(campaignId: T.CampaignId): Promise<T.StateStaleStatus> {
    return this.get<T.StateStaleStatus>(
      `/api/settings/campaigns/${campaignId}/state/stale-status`,
    );
  }

  // ============================================================
  // Models — Generation
  // ============================================================

  async getGenerationModels(): Promise<T.GenerationModel[]> {
    return this.get<T.GenerationModel[]>('/api/settings/models/generation');
  }

  async createGenerationModel(data: Partial<T.GenerationModel>): Promise<T.GenerationModel> {
    return this.post<T.GenerationModel>('/api/settings/models/generation', data);
  }

  async updateGenerationModel(
    modelId: string,
    data: Partial<T.GenerationModel>,
  ): Promise<T.GenerationModel> {
    return this.put<T.GenerationModel>(
      `/api/settings/models/generation/${encodeURIComponent(modelId)}`,
      data,
    );
  }

  async deleteGenerationModel(modelId: string): Promise<void> {
    return this.delete(`/api/settings/models/generation/${encodeURIComponent(modelId)}`);
  }

  async setActiveGenerationModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/generation/${encodeURIComponent(modelId)}/activate`);
  }

  async deactivateGenerationModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/generation/${encodeURIComponent(modelId)}/deactivate`);
  }

  async toggleGenerationModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/generation/${encodeURIComponent(modelId)}/toggle`);
  }

  async checkGenerationModel(modelId: string): Promise<T.ModelCheckResult> {
    return this.post<T.ModelCheckResult>(
      `/api/settings/models/generation/${encodeURIComponent(modelId)}/check`,
    );
  }

  // ============================================================
  // Models — Embedding
  // ============================================================

  async getEmbeddingModels(): Promise<T.EmbeddingModel[]> {
    return this.get<T.EmbeddingModel[]>('/api/settings/models/embedding');
  }

  async createEmbeddingModel(data: Partial<T.EmbeddingModel>): Promise<T.EmbeddingModel> {
    return this.post<T.EmbeddingModel>('/api/settings/models/embedding', data);
  }

  async updateEmbeddingModel(
    modelId: string,
    data: Partial<T.EmbeddingModel>,
  ): Promise<T.EmbeddingModel> {
    return this.put<T.EmbeddingModel>(
      `/api/settings/models/embedding/${encodeURIComponent(modelId)}`,
      data,
    );
  }

  async deleteEmbeddingModel(modelId: string): Promise<void> {
    return this.delete(`/api/settings/models/embedding/${encodeURIComponent(modelId)}`);
  }

  async toggleEmbeddingModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/embedding/${encodeURIComponent(modelId)}/toggle`);
  }

  async checkEmbeddingModel(modelId: string): Promise<T.ModelCheckResult> {
    return this.post<T.ModelCheckResult>(
      `/api/settings/models/embedding/${encodeURIComponent(modelId)}/check`,
    );
  }

  // ============================================================
  // Models — Rerank
  // ============================================================

  async getRerankModels(): Promise<T.RerankModel[]> {
    return this.get<T.RerankModel[]>('/api/settings/models/rerank');
  }

  async createRerankModel(data: Partial<T.RerankModel>): Promise<T.RerankModel> {
    return this.post<T.RerankModel>('/api/settings/models/rerank', data);
  }

  async updateRerankModel(
    modelId: string,
    data: Partial<T.RerankModel>,
  ): Promise<T.RerankModel> {
    return this.put<T.RerankModel>(
      `/api/settings/models/rerank/${encodeURIComponent(modelId)}`,
      data,
    );
  }

  async deleteRerankModel(modelId: string): Promise<void> {
    return this.delete(`/api/settings/models/rerank/${encodeURIComponent(modelId)}`);
  }

  async checkRerankModel(modelId: string): Promise<T.ModelCheckResult> {
    return this.post<T.ModelCheckResult>(
      `/api/settings/models/rerank/${encodeURIComponent(modelId)}/check`,
    );
  }

  async setActiveRerankModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/rerank/${encodeURIComponent(modelId)}/activate`);
  }

  async activateRerankModel(modelId: string): Promise<unknown> {
    return this.setActiveRerankModel(modelId);
  }

  async deactivateRerankModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/rerank/${encodeURIComponent(modelId)}/deactivate`);
  }

  async toggleRerankModel(modelId: string): Promise<T.RerankModel> {
    const current = await this.getRerankModels();
    const model = current.find((m) => m.model_id === modelId);
    if (!model) throw new Error('Rerank model not found');
    return this.updateRerankModel(modelId, { enabled: !(model.enabled !== false) });
  }

  // ============================================================
  // Models — Drift
  // ============================================================

  async getDriftModels(): Promise<T.DriftModel[]> {
    return this.get<T.DriftModel[]>('/api/settings/models/drift');
  }

  async createDriftModel(data: T.CreateDriftModelRequest): Promise<T.DriftModel> {
    return this.post<T.DriftModel>('/api/settings/models/drift', data);
  }

  async updateDriftModel(
    modelId: string,
    data: T.UpdateDriftModelRequest,
  ): Promise<T.DriftModel> {
    return this.put<T.DriftModel>(
      `/api/settings/models/drift/${encodeURIComponent(modelId)}`,
      data,
    );
  }

  async deleteDriftModel(modelId: string): Promise<void> {
    return this.delete(`/api/settings/models/drift/${encodeURIComponent(modelId)}`);
  }

  async checkDriftModel(modelId: string): Promise<T.ModelCheckResult> {
    return this.post<T.ModelCheckResult>(
      `/api/settings/models/drift/${encodeURIComponent(modelId)}/check`,
    );
  }

  async setActiveDriftModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/drift/${encodeURIComponent(modelId)}/activate`);
  }

  async deactivateDriftModel(modelId: string): Promise<unknown> {
    return this.post(`/api/settings/models/drift/${encodeURIComponent(modelId)}/deactivate`);
  }

  async toggleDriftModel(modelId: string): Promise<T.DriftModel> {
    const current = await this.getDriftModels();
    const model = current.find((m) => m.model_id === modelId);
    if (!model) throw new Error('Drift model not found');
    return this.updateDriftModel(modelId, { enabled: !(model.enabled !== false) });
  }

  // ============================================================
  // Documents & Indexer
  // ============================================================

  async getDocuments(vaultId?: T.VaultId | null, domainId?: T.DomainId | null): Promise<T.Document[]> {
    const params = new URLSearchParams();
    if (vaultId) params.set('vault_id', vaultId);
    if (domainId) params.set('domain_id', domainId);
    const qs = params.toString() ? `?${params}` : '';
    return this.get<T.Document[]>(`/api/settings/documents${qs}`);
  }

  async getSettingsDocuments(
    opts: {
      vaultId?: T.VaultId | null;
      domainId?: T.DomainId | null;
      status?: string | null;
      tagId?: T.TagId | null;
      tagIds?: T.TagId[] | null;
    } = {},
  ): Promise<T.Document[]> {
    const params = new URLSearchParams();
    if (opts.vaultId) params.set('vault_id', opts.vaultId);
    if (opts.domainId) params.set('domain_id', opts.domainId);
    if (opts.status) params.set('status', opts.status);
    if (opts.tagIds && opts.tagIds.length) {
      for (const tid of opts.tagIds) {
        if (tid) params.append('tag_id', String(tid));
      }
    } else if (opts.tagId) {
      params.set('tag_id', opts.tagId);
    }
    const qs = params.toString() ? `?${params}` : '';
    return this.get<T.Document[]>(`/api/settings/documents${qs}`);
  }

  async deleteDocument(documentId: T.DocumentId): Promise<void> {
    return this.delete(`/api/settings/documents/${encodeURIComponent(documentId)}`);
  }

  async deleteDocumentById(documentId: T.DocumentId, vaultId?: T.VaultId): Promise<void> {
    const params = new URLSearchParams();
    if (vaultId) params.set('vault_id', vaultId);
    const qs = params.toString() ? `?${params}` : '';
    return this.delete(`/api/settings/documents/${encodeURIComponent(documentId)}${qs}`);
  }

  async updateDocumentLabels(
    documentId: T.DocumentId,
    tagIds: T.TagId[],
  ): Promise<unknown> {
    return this.put(`/api/settings/documents/${encodeURIComponent(documentId)}/labels`, {
      tag_ids: tagIds,
    });
  }

  async runIndexer(domainId?: T.DomainId | null): Promise<unknown> {
    if (!domainId) {
      try {
        const resp = await this.getDomains();
        const list = Array.isArray(resp) ? resp : (resp.domains ?? []);
        const first = list.find((d) => d.enabled !== false) ?? list[0];
        domainId = first ? (first.domain_id ?? null) : null;
      } catch {
        /* ignore */
      }
    }
    if (!domainId) throw new Error('No active domain found to run indexer');
    return this.post(`/api/v1/domains/${encodeURIComponent(domainId)}/index`);
  }

  async getDomainPendingFiles(domainId: T.DomainId): Promise<T.DomainPendingFiles> {
    return this.get<T.DomainPendingFiles>(
      `/api/v1/domains/${encodeURIComponent(domainId)}/pending-files`,
    );
  }

  async triggerDomainIndex(domainId: T.DomainId): Promise<T.IndexTriggerResult> {
    return this.post<T.IndexTriggerResult>(
      `/api/v1/domains/${encodeURIComponent(domainId)}/index`,
    );
  }

  async getIndexTaskState(taskId: string): Promise<unknown> {
    return this.get(`/index-tasks/${encodeURIComponent(taskId)}/state`);
  }

  async getSystemIndexState(): Promise<T.SystemIndexState> {
    return this.get<T.SystemIndexState>('/api/v1/indexer/tasks');
  }

  async cancelIndexTask(taskId: string): Promise<unknown> {
    const response = await fetch(
      `/api/v1/indexer/tasks/${encodeURIComponent(taskId)}/cancel`,
      { method: 'POST' },
    );
    if (response.status === 409) {
      return { cancelled: false, task_id: taskId };
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new HttpError(response.status, detail?.detail ?? detail, response.statusText);
    }
    return response.json();
  }

  // ============================================================
  // Settings & Params
  // ============================================================

  async getSettingsStatus(): Promise<T.PlatformStatus> {
    return this.get<T.PlatformStatus>('/api/settings/status');
  }

  async getModelHealth(
    kind: 'generation' | 'embedding' | 'rerank' | 'drift',
    modelId: string,
  ): Promise<T.ModelHealthState> {
    let res: T.ModelCheckResult;
    try {
      if (kind === 'drift') {
        res = await this.checkDriftModel(modelId);
      } else if (kind === 'generation') {
        res = await this.checkGenerationModel(modelId);
      } else if (kind === 'embedding') {
        res = await this.checkEmbeddingModel(modelId);
      } else {
        res = await this.checkRerankModel(modelId);
      }
    } catch (err) {
      return {
        status: 'fail',
        latency_ms: null,
        error: err instanceof Error ? err.message : String(err),
        checked_at: new Date().toISOString(),
      };
    }
    return {
      status: res.ok ? 'ok' : 'fail',
      latency_ms: res.latency_ms ?? null,
      error: res.error ?? null,
      dimensions: res.dimensions ?? null,
      checked_at: new Date().toISOString(),
    };
  }

  async getSettingsParams(): Promise<T.PlatformSetting[]> {
    return this.get<T.PlatformSetting[]>('/api/settings/params');
  }

  async updateSettingsParam(key: string, value: unknown): Promise<unknown> {
    return this.put(`/api/settings/params/${encodeURIComponent(key)}`, { value });
  }

  async resetSettingsParams(): Promise<unknown> {
    return this.post('/api/settings/params/reset');
  }

  async getConfig(): Promise<unknown> {
    return this.get('/config');
  }

  async updateConfig(data: unknown): Promise<unknown> {
    return this.put('/config', data);
  }

  async getWatchdogSettings(): Promise<T.WatchdogSettings> {
    return this.get<T.WatchdogSettings>('/api/v1/settings/watchdog');
  }

  async saveWatchdogSettings(
    extensions: string[],
    intervalSec: number,
  ): Promise<T.WatchdogSettings> {
    return this.patch<T.WatchdogSettings>('/api/v1/settings/watchdog', {
      auto_index_extensions: extensions,
      interval_sec: intervalSec,
    });
  }

  // ============================================================
  // Sidecar (через host-agent)
  // ============================================================

  async getSidecarStatus(): Promise<T.SidecarStatus> {
    try {
      return await this.get<T.SidecarStatus>('/api/settings/sidecar/status');
    } catch {
      return { running: false, installed: false, agent_unavailable: true };
    }
  }

  async sidecarStart(): Promise<unknown> {
    return this.post('/api/settings/sidecar/start');
  }

  async sidecarStop(): Promise<unknown> {
    return this.post('/api/settings/sidecar/stop');
  }

  async sidecarRestart(): Promise<unknown> {
    return this.post('/api/settings/sidecar/restart');
  }

  getSidecarInstallStreamUrl(): string {
    return '/api/settings/sidecar/install/stream';
  }

  // ============================================================
  // DB Search (LanceDB)
  // ============================================================

  async textSearchByDomain(
    domainId: T.DomainId,
    queryText: string,
    limit = 20,
  ): Promise<T.SearchResult[]> {
    return this.post<T.SearchResult[]>('/api/db/search/domain', {
      domain_id: domainId,
      query_text: queryText,
      limit,
    });
  }

  // ============================================================
  // Update Mode
  // ============================================================

  async updateModeStart(chatId: T.UUID, note: string): Promise<T.UpdateModeSessionResponse> {
    return this.post<T.UpdateModeSessionResponse>(
      `/api/chats/${chatId}/update-mode/start`,
      { note },
    );
  }

  async updateModeGetSession(chatId: T.UUID): Promise<T.UpdateModeSessionResponse | null> {
    const response = await fetch(`/api/chats/${chatId}/update-mode/session`);
    if (response.status === 410) return null;
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new HttpError(response.status, detail?.detail ?? detail, response.statusText);
    }
    return (await response.json()) as T.UpdateModeSessionResponse;
  }

  async updateModeReview(
    chatId: T.UUID,
    acceptedIds: string[],
    rejectedIds: string[],
    statePatchDecisions: T.UpdateModeReviewRequest['state_patch_decisions'] | null = null,
    fieldChangeDecisions: T.UpdateModeReviewRequest['field_change_decisions'] | null = null,
  ): Promise<T.UpdateModeSessionResponse> {
    const body: Record<string, unknown> = {
      accepted_change_ids: acceptedIds,
      rejected_change_ids: rejectedIds,
    };
    if (statePatchDecisions !== null) {
      body.state_patch_decisions = statePatchDecisions;
    }
    if (fieldChangeDecisions !== null) {
      body.field_change_decisions = fieldChangeDecisions;
    }
    return this.patch<T.UpdateModeSessionResponse>(
      `/api/chats/${chatId}/update-mode/review`,
      body,
    );
  }

  async updateModeApply(chatId: T.UUID, applyId: string | null = null): Promise<unknown> {
    const body: Record<string, unknown> = {};
    if (applyId) body.apply_id = applyId;
    return this.post(`/api/chats/${chatId}/update-mode/apply`, body);
  }

  async updateModeCancel(chatId: T.UUID): Promise<unknown> {
    return this.delete(`/api/chats/${chatId}/update-mode/session`);
  }

  // ============================================================
  // Context Draft (Phase 4)
  // ============================================================

  async getContextDraft(chatId: T.UUID): Promise<T.ContextDraftResponse> {
    return this.get<T.ContextDraftResponse>(
      `/api/chats/${chatId}/context-draft`,
    );
  }

  async acceptContextDraft(chatId: T.UUID): Promise<T.ContextDraftAcceptResponse> {
    return this.post<T.ContextDraftAcceptResponse>(
      `/api/chats/${chatId}/context-draft/accept`,
      {},
    );
  }

  async rejectContextDraft(chatId: T.UUID): Promise<T.ContextDraftRejectResponse> {
    return this.post<T.ContextDraftRejectResponse>(
      `/api/chats/${chatId}/context-draft/reject`,
      {},
    );
  }

  async checkFilesFromContextDraft(chatId: T.UUID): Promise<{ session_id: string }> {
    return this.post<{ session_id: string }>(
      `/api/chats/${chatId}/context-draft/check-files`,
      {},
    );
  }
}

export const api = new MercerAPI();