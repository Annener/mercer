// === Common ===

export type DomainId = string;
export type VaultId = string;
export type CampaignId = string;
export type PipelineId = string;
export type DocumentId = string;
export type TagId = string;
export type UUID = string;

export type ChatRole = 'user' | 'assistant' | 'system' | 'clarification';

export interface Source {
  path: string;
  page?: number | null;
  vault_id?: VaultId;
  source_kind?: 'chunk' | 'full_document';
}

export interface GroupedStep {
  step?: string;
  sources?: Source[];
}

export interface ChatMessage {
  role: ChatRole;
  content: string;
  clarification_id?: UUID;
  sources?: Source[];
}

// === Chat ===

export interface Chat {
  chat_id: UUID;
  title: string;
  domain_id: DomainId;
  campaign_id?: CampaignId | null;
  locked_pipeline_id?: PipelineId | null;
  full_document_mode_enabled?: boolean;
  context_update_mode?: boolean;
}

export interface ChatDetail {
  chat: Chat;
  messages: ChatMessage[];
}

export interface CreateChatRequest {
  domain_id: DomainId | null;
  campaign_id?: CampaignId | null;
}

export interface SendMessageRequest {
  content: string;
  stream?: boolean;
}

export interface SendMessageResponse {
  content?: string;
  clarification_id?: UUID;
}

export interface ClarificationRequest {
  clarification_id: UUID;
  answers: Record<string, unknown>;
}

// === Pipeline ===

export interface Pipeline {
  id?: string;
  pipeline_id: PipelineId;
  domain_id?: DomainId;
  campaign_id?: string | null;
  version?: string;
  name: string;
  description?: string | null;
  is_active?: boolean;
  steps?: PipelineStep[];
  final_composition?: string;
  created_at?: string | null;
}

export interface PipelineStep {
  id?: string;
  name?: string;
  type: 'retrieval' | 'validation';
  depends_on?: string[];
  params?: Record<string, unknown>;
}

// === Domain ===

export interface Domain {
  domain_id: DomainId;
  display_name?: string;
  description?: string | null;
  enabled?: boolean;
  is_system?: boolean;
  has_vault?: boolean;
  vault_enabled?: boolean;
}

export type PromptType = 'system' | 'clarification' | 'planner' | 'pipeline_router';

export interface DomainPrompt {
  prompt_type: PromptType;
  content: string;
}

export type ClarificationFieldType = 'text' | 'select' | 'multiselect';

export interface ClarificationField {
  field_key: string;
  label: string;
  type: ClarificationFieldType;
  options?: string[];
  required?: boolean;
  description?: string;
}

// === Vault ===

export interface Vault {
  vault_id: VaultId;
  domain_id: DomainId;
  display_name?: string | null;
  enabled?: boolean;
  embedding_model_id?: string | null;
  expected_dimensions?: number | null;
  chunk_size?: number | null;
  overlap?: number | null;
  entity_aware_mode?: boolean | null;
  binding_status?: 'unbound' | 'indexing' | 'bound' | 'error' | string;
  chunk_count?: number;
  git_author_name?: string | null;
  git_author_email?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateVaultRequest {
  vault_id: VaultId;
  domain_id: DomainId;
  display_name?: string | null;
  embedding_model_id?: string | null;
  create_folder?: boolean;
  chunk_size?: number | null;
  overlap?: number | null;
  entity_aware_mode?: boolean | null;
  git_author_name?: string | null;
  git_author_email?: string | null;
}

export interface UpdateVaultRequest {
  display_name?: string | null;
  domain_id?: DomainId;
  enabled?: boolean | null;
  embedding_model_id?: string | null;
  chunk_size?: number | null;
  overlap?: number | null;
  entity_aware_mode?: boolean | null;
  git_author_name?: string | null;
  git_author_email?: string | null;
}

// === Campaign ===

export interface Campaign {
  id: CampaignId;
  name: string;
  description?: string | null;
  system_prompt?: string | null;
  domain_id: DomainId;
  tags?: TagRead[];
  tag_ids?: TagId[];
  global_tag_ids?: TagId[];
  config_version?: number;
  last_session_at?: string | null;
  created_at?: string | null;
  has_initial_state?: boolean;
}

export interface CreateCampaignRequest {
  domain_id: DomainId;
  name: string;
  description?: string;
  system_prompt?: string | null;
}

export interface UpdateCampaignRequest {
  name?: string;
  description?: string | null;
  system_prompt?: string | null;
}

export interface TagRead {
  id: TagId;
  name: string;
  domain_id: DomainId;
  campaign_id?: CampaignId | null;
  color?: string | null;
  created_at?: string | null;
}

export interface CreateTagRequest {
  domain_id?: DomainId;
  name: string;
  color?: string | null;
  campaign_id?: CampaignId | null;
}

export interface TagsGrouped {
  global_tags: TagRead[];
  by_campaign: Record<string, TagRead[]>;
}

// === Campaign State ===

export type StateFieldMode = 'single' | 'list';

export interface StateFieldConfig {
  field_id: UUID;
  key: string;
  label: string;
  description?: string;
  mode: StateFieldMode;
  enabled: boolean;
  display_order: number;
}

export interface CreateStateFieldRequest {
  key: string;
  label: string;
  description?: string;
  mode: StateFieldMode;
  enabled?: boolean;
  display_order?: number;
}

export interface UpdateStateFieldRequest {
  label?: string;
  description?: string;
  enabled?: boolean;
  display_order?: number;
}

export interface CampaignStateSingleValueRead {
  field_key: string;
  text: string;
  source_refs?: string[];
  updated_at?: string;
}

export interface CampaignStateListItemRead {
  field_key: string;
  item_key: string;
  text: string;
  resolved: boolean;
  source_refs?: string[];
  updated_at?: string;
}

export interface CampaignStateFieldValue {
  field_key: string;
  field_id: string;
  field_label?: string;
  mode: StateFieldMode;
  enabled: boolean;
  display_order: number;
  single_value?: CampaignStateSingleValueRead | null;
  items?: CampaignStateListItemRead[];
}

export interface CampaignStateVersionSummary {
  id: string;
  campaign_id: string;
  state_version: number;
  config_version: number;
  source_kind?: string;
  base_state_version?: number | null;
  created_at?: string;
  created_by?: string;
}

export interface CampaignStateVersion {
  summary: CampaignStateVersionSummary;
  fields?: CampaignStateFieldValue[];
}

export type CampaignStatePatchOp =
  | { type: 'replace_single'; field_key: string; text: string; reason: string }
  | { type: 'clear_single'; field_key: string; reason: string }
  | { type: 'add_list_item'; field_key: string; text: string; reason: string }
  | { type: 'update_list_item'; field_key: string; item_key: string; text: string; reason: string }
  | { type: 'resolve_list_item'; field_key: string; item_key: string; reason: string }
  | { type: 'remove_list_item'; field_key: string; item_key: string; reason: string };

export interface CampaignStatePatchFailure {
  op_index: number;
  op_type: string;
  code: 'field_not_found' | 'mode_mismatch' | 'item_not_found' | 'invalid_payload';
  detail: string;
}

export interface CampaignStatePatchResponse {
  applied_state_version: number;
  config_version: number;
  applied_operations: string[];
  failed_operations: CampaignStatePatchFailure[];
}

// === Initial State (Stage 3) ===

export interface InitialProposalSingleValue {
  text: string;
  source_refs?: string[];
}

export interface InitialProposalListItem {
  text: string;
  source_refs?: string[];
}

export type InitialFieldStatus = 'proposed' | 'empty' | 'needs_clarification';

export interface InitialProposalField {
  field_key: string;
  mode: StateFieldMode;
  status: InitialFieldStatus;
  clarification_question?: string | null;
  single_value?: InitialProposalSingleValue | null;
  list_value?: { items: InitialProposalListItem[] } | null;
}

export interface InitialProposalSuggestion {
  key: string;
  label: string;
  description?: string;
  mode: StateFieldMode;
  initial_status: InitialFieldStatus;
  clarification_question?: string | null;
  single_value?: InitialProposalSingleValue | null;
  list_value?: { items: InitialProposalListItem[] } | null;
}

export interface DocumentSnapshot {
  document_id: DocumentId;
  vault_id: VaultId;
  source_path: string;
  title?: string | null;
  content_sha: string;
  estimated_tokens: number;
}

export interface InitialProposal {
  fields: InitialProposalField[];
  suggested_fields: InitialProposalSuggestion[];
  questions: string[];
}

export interface InitialProposalRead {
  proposal_id: string;
  config_version: number;
  source_snapshot: DocumentSnapshot[];
  proposal: InitialProposal;
  warnings: string[];
  created_at: string;
  expires_at: string;
}

export type InitialProposalReadV2 = InitialProposalRead;

export interface PreviewInitialStateRequest {
  document_ids: DocumentId[];
  propose_fields?: boolean;
  max_suggested_fields?: number;
}

export interface ApplyInitialStateRequest {
  proposal_id: string;
  config_version: number;
  proposal_overrides?: unknown;
  accepted_suggested_field_keys?: string[];
  rejected_suggested_field_keys?: string[];
}

export interface EffectiveContextBlock {
  name: string;
  text: string;
  estimated_tokens: number;
}

export interface EffectiveContextRead {
  campaign_id?: string;
  chat_id?: string;
  domain_id?: string;
  blocks: EffectiveContextBlock[];
  total_tokens: number;
  budget?: number;
  truncated_fields?: string[];
  state_version?: number | null;
}

export interface StateStaleStatus {
  potentially_stale: boolean;
  stale_documents: DocumentId[];
  active_state_version: number | null;
  checked_at: string;
}

// === Models ===

export type ModelKind = 'generation' | 'embedding' | 'rerank';

export interface GenerationModel {
  model_id: string;
  display_name?: string | null;
  provider?: string;
  base_url?: string;
  timeout_seconds?: number;
  enabled?: boolean;
  is_active?: boolean;
  has_api_key?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EmbeddingModel {
  model_id: string;
  display_name?: string | null;
  provider?: string;
  model_name?: string | null;
  base_url?: string;
  dimensions?: number;
  timeout_seconds?: number;
  max_retries?: number;
  enabled?: boolean;
  has_api_key?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RerankModel {
  model_id: string;
  display_name?: string | null;
  provider?: string;
  base_url?: string;
  timeout_seconds?: number;
  enabled?: boolean;
  is_active?: boolean;
  has_api_key?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateGenerationModelRequest {
  model_id: string;
  provider?: string;
  display_name?: string | null;
  base_url?: string;
  api_key?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface UpdateGenerationModelRequest {
  provider?: string;
  display_name?: string | null;
  base_url?: string;
  api_key?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface CreateEmbeddingModelRequest {
  model_id: string;
  provider: string;
  display_name?: string | null;
  model_name?: string | null;
  base_url?: string;
  api_key?: string | null;
  dimensions: number;
  timeout_seconds?: number;
  max_retries?: number;
  enabled?: boolean;
}

export interface UpdateEmbeddingModelRequest {
  provider?: string;
  display_name?: string | null;
  model_name?: string | null;
  base_url?: string;
  api_key?: string | null;
  dimensions?: number;
  timeout_seconds?: number;
  max_retries?: number;
  enabled?: boolean;
}

export interface CreateRerankModelRequest {
  model_id: string;
  provider?: string;
  display_name?: string | null;
  base_url: string;
  api_key?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface UpdateRerankModelRequest {
  provider?: string;
  display_name?: string | null;
  base_url?: string;
  api_key?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
}

export interface ModelCheckResult {
  ok: boolean;
  latency_ms?: number;
  error?: string | null;
  dimensions?: number | null;
}

// === Platform status / model availability ===

export interface PlatformStatus {
  has_active_generation_model: boolean;
  has_active_embedding_model: boolean;
  pdf_sidecar_available: boolean;
  has_vaults: boolean;
}

export type ModelAvailabilityStatus = 'ok' | 'warn' | 'fail' | 'unchecked';

export interface ModelHealthState {
  status: ModelAvailabilityStatus;
  latency_ms?: number | null;
  error?: string | null;
  dimensions?: number | null;
  checked_at?: string | null;
}

// === Documents ===

export interface Document {
  id: DocumentId;
  document_id?: DocumentId;
  title?: string | null;
  vault_id: VaultId;
  source_path?: string;
  path?: string;
  status?: string;
  tags?: TagRead[];
  tag_ids?: TagId[];
  md5?: string;
  mtime?: number | null;
  indexed_at?: string | null;
  created_at?: string | null;
  char_count?: number | null;
  chunk_count?: number | null;
  estimated_tokens?: number | null;
}

export interface DocumentCandidate {
  document_id: DocumentId;
  title: string;
  source_path?: string;
  estimated_tokens?: number;
  already_sent?: boolean;
}

export interface IndexerFileState {
  stage: string;
  chunks_total: number;
  chunks_done: number;
  error?: string | null;
}

export interface IndexerTaskState {
  task_id: string;
  vault_id?: string;
  status: 'running' | 'done' | 'error' | 'cancelled' | string;
  started_at?: string;
  finished_at?: string;
  files_total?: number;
  files_to_index?: number;
  files_skipped?: number;
  files_done?: number;
  error?: string;
  files?: Record<string, IndexerFileState>;
}

export interface SystemIndexState {
  tasks: IndexerTaskState[];
  has_active: boolean;
}

// === Watchdog / Pending files ===

export interface DomainPendingVaultEntry {
  vault_id: VaultId;
  pending_count: number;
}

export interface DomainPendingFiles {
  domain_id: DomainId;
  total_pending: number;
  vaults: DomainPendingVaultEntry[];
}

export interface IndexTriggerResult {
  domain_id: DomainId;
  queued: number;
}

// === Search ===

export interface SearchResult {
  chunk_id?: string;
  document_id: DocumentId;
  text: string;
  score?: number;
  path?: string;
  page?: number;
}

// === Platform Settings ===

export type PlatformSettingValueType = 'int' | 'float' | 'bool' | 'str';

export interface PlatformSetting {
  key: string;
  value: string | number | boolean;
  value_type: PlatformSettingValueType;
  group_name: string;
  label: string;
  hint: string;
  updated_at?: string | null;
}

// === Sidecar ===

export interface SidecarStatus {
  running: boolean;
  installed: boolean;
  agent_unavailable?: boolean;
  pid?: number;
}

// === Watchdog ===

export interface WatchdogSettings {
  auto_index_extensions: string[];
  interval_sec: number;
}

// === Update Mode ===

export type UpdateModeAction = 'update' | 'create';
export type UpdateModeChangeStatus =
  | 'pending'
  | 'accepted'
  | 'rejected'
  | 'resolution_failed';

export interface ResolvedUpdateModeChange {
  change_id: string;
  vault_id?: string | null;
  document_id?: string | null;
  file_path?: string | null;
  action: UpdateModeAction;
  description: string;
  operation?: string | null;
  anchor?: unknown;
  op_content?: string;
  resolve_order?: number;
  original_content?: string;
  proposed_content?: string;
  unified_diff?: string;
  expected_sha256?: string | null;
  status?: UpdateModeChangeStatus;
  error_code?: string | null;
  error_message?: string | null;
}

export interface UpdateModeStatePatchEntry {
  op_index: number;
  field_key: string;
  field_label: string;
  mode: 'single' | 'list';
  operation: string;
  previous_text?: string | null;
  proposed_text?: string | null;
  edited_text?: string | null;
  status: 'pending' | 'accepted' | 'rejected';
}

export type ContextFieldChangeOperation = 'create_field' | 'update_field';

export interface UpdateModeStateFieldChangeEntry {
  op_index: number;
  operation: ContextFieldChangeOperation;
  key: string;
  proposed_label?: string | null;
  proposed_description?: string | null;
  proposed_mode?: 'single' | 'list' | null;
  proposed_enabled?: boolean | null;
  proposed_display_order?: number | null;
  previous_label?: string | null;
  previous_description?: string | null;
  previous_enabled?: boolean | null;
  previous_display_order?: number | null;
  status: 'pending' | 'accepted' | 'rejected';
}

export interface UpdateModeSessionResponse {
  chat_id: UUID;
  campaign_id: string;
  domain_id: string;
  vault_ids: string[];
  expires_at: string;
  changes: ResolvedUpdateModeChange[];
  warnings: string[];
  state_field_snapshot: unknown[];
  state_patch_operations: UpdateModeStatePatchEntry[];
  state_field_change_operations: UpdateModeStateFieldChangeEntry[];
  related_document_ids?: UUID[];
}

export interface UpdateModeReviewRequest {
  accepted_change_ids: string[];
  rejected_change_ids: string[];
  state_patch_decisions?: {
    accepted_op_indexes?: number[];
    rejected_op_indexes?: number[];
    edited?: Array<{ op_index: number; text: string }>;
  };
  field_change_decisions?: {
    accepted_op_indexes?: number[];
    rejected_op_indexes?: number[];
  };
}

export interface UpdateModeApplyRequest {
  apply_id?: string;
}

// === Settings ===

export interface ParamGroup {
  group_name: string;
  params: Param[];
}

export interface Param {
  key: string;
  value: unknown;
  description?: string;
  group_name?: string;
}