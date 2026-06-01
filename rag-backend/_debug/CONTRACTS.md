# API Contracts — RAG Backend

> Источник правды: `openapi.json` (FastAPI auto-generated)  
> Бэкенд — источник правды. Фронт подстраивается под бэк.  
> Обновлено: 2026-06-01

---

## Группа: chat

| # | Метод | URL | Request Body | Response |
|---|---|---|---|---|
| C1 | POST | `/chat/create` | `CreateChatRequest` | `CreateChatResponse` |
| C2 | GET | `/chat/list` | query: `domain_id?` | `ChatListResponse` |
| C3 | GET | `/chat/{chat_id}/history` | — | `ChatHistoryResponse` |
| C4 | POST | `/chat/{chat_id}/rename` | `RenameChatRequest` | `CreateChatResponse` |
| C5 | DELETE | `/chat/{chat_id}` | — | 204 |
| C6 | POST | `/chat/{chat_id}/lock_pipeline` | `PipelineLockRequest` | `{status, locked_pipeline_id}` |
| C7 | POST | `/chat/{chat_id}/send` | `SendMessageRequest` | `MessageResponse` |
| C8 | POST | `/chat/{chat_id}/send_stream` | `SendMessageRequest` | SSE stream |
| C9 | POST | `/chat/{chat_id}/clarify` | `ClarificationAnswer` | `ClarificationResponse` |

## Группа: config

| # | Метод | URL | Request Body | Response |
|---|---|---|---|---|
| CF1 | GET | `/config/domains` | — | `DomainsResponse` |
| CF2 | GET | `/config/vaults` | query: `domain_id?`, `search?` | `VaultsResponse` |

## Группа: settings

| # | Метод | URL | Request Body | Response |
|---|---|---|---|---|
| S1 | GET | `/api/settings/status` | — | `{key: boolean}` |
| S2 | GET | `/api/settings/params` | — | `{key: any}` |
| S3 | PUT | `/api/settings/params/{key}` | `ParamUpdateRequest` | `{key: any}` |
| S4 | POST | `/api/settings/reset` | — | `{key: string}` |
| S5 | GET | `/api/settings/domains` | — | `array<object>` |
| S6 | POST | `/api/settings/domains` | `DomainCreateRequest` | `object` (201) |
| S7 | GET | `/api/settings/domains/{domain_id}` | — | `object` |
| S8 | PUT | `/api/settings/domains/{domain_id}` | `DomainUpdateRequest` | `object` |
| S9 | DELETE | `/api/settings/domains/{domain_id}` | — | 204 |
| S10 | GET | `/api/settings/domains/{domain_id}/prompts` | — | `{type: string}` |
| S11 | PUT | `/api/settings/domains/{domain_id}/prompts/{prompt_type}` | `PromptUpdateRequest` | `{type: string}` |
| S12 | GET | `/api/settings/domains/{domain_id}/fields` | — | `array<object>` |
| S13 | PUT | `/api/settings/domains/{domain_id}/fields` | `ClarificationFieldRequest[]` | `{key: string}` |
| S14 | GET | `/api/settings/models/generation` | — | `array<object>` |
| S15 | POST | `/api/settings/models/generation` | `GenerationModelCreateRequest` | `object` (201) |
| S16 | POST | `/api/settings/models/generation/{model_id}/activate` | — | `{key: string}` |
| S17 | POST | `/api/settings/models/generation/{model_id}/check` | — | `object` |
| S18 | PUT | `/api/settings/models/generation/{model_id}` | `GenerationModelUpdateRequest` | `object` |
| S19 | DELETE | `/api/settings/models/generation/{model_id}` | — | 204 |
| S20 | GET | `/api/settings/models/embedding` | — | `array<object>` |
| S21 | POST | `/api/settings/models/embedding` | `EmbeddingModelCreateRequest` | `object` (201) |
| S22 | POST | `/api/settings/models/embedding/{model_id}/check` | — | `object` |
| S23 | PUT | `/api/settings/models/embedding/{model_id}` | `EmbeddingModelUpdateRequest` | `object` |
| S24 | DELETE | `/api/settings/models/embedding/{model_id}` | — | 204 |
| S25 | GET | `/api/settings/vaults` | query: `domain_id?` | `array<object>` |
| S26 | POST | `/api/settings/vaults` | `VaultCreateRequest` | `object` (201) |
| S27 | PUT | `/api/settings/vaults/{vault_id}` | `VaultUpdateRequest` | `object` |
| S28 | DELETE | `/api/settings/vaults/{vault_id}` | — | 204 |
| S29 | POST | `/api/settings/vaults/{vault_id}/toggle` | — | `object` |
| S30 | GET | `/api/settings/pipelines` | query: `domain_id?`, `campaign_id?` | `array<object>` |
| S31 | POST | `/api/settings/pipelines` | `PipelineCreateRequest` | `object` (201) |
| S32 | PUT | `/api/settings/pipelines/{pipeline_uuid}` | `PipelineUpdateRequest` | `object` |
| S33 | DELETE | `/api/settings/pipelines/{pipeline_uuid}` | — | 204 |
| S34 | POST | `/api/settings/pipelines/{pipeline_uuid}/activate` | — | `{key: string}` |
| S35 | POST | `/api/settings/pipelines/{pipeline_uuid}/deactivate` | — | `{key: string}` |
| S36 | GET | `/api/settings/tags` | query: `domain_id?`, `vault_id?`, `campaign_id?` | `TagsGrouped` |
| S37 | POST | `/api/settings/tags` | `TagCreate` | `TagRead` (201) |
| S38 | PUT | `/api/settings/tags/{tag_id}` | `TagUpdate` | `TagRead` |
| S39 | DELETE | `/api/settings/tags/{tag_id}` | — | 204 |
| S40 | GET | `/api/settings/documents` | query: `vault_id?`, `domain_id?`, `status?`, `tag_id?` | `DocumentRead[]` |
| S41 | GET | `/api/settings/documents/{document_id}` | — | `DocumentRead` |
| S42 | DELETE | `/api/settings/documents/{document_id}` | — | 204 |
| S43 | PUT | `/api/settings/documents/{document_id}/labels` | `DocumentLabelWrite` | `DocumentRead` |
| S44 | POST | `/api/settings/documents/labels/batch` | `{document_ids, tag_ids}` | 204 |
| S45 | GET | `/api/settings/campaigns` | query: `domain_id?`, `vault_id?` | `CampaignRead[]` |
| S46 | POST | `/api/settings/campaigns` | `CampaignCreate` | `CampaignRead` (201) |
| S47 | GET | `/api/settings/campaigns/{campaign_id}` | — | `CampaignRead` |
| S48 | PUT | `/api/settings/campaigns/{campaign_id}` | `CampaignUpdate` | `CampaignRead` |
| S49 | DELETE | `/api/settings/campaigns/{campaign_id}` | — | 204 |
| S50 | GET | `/api/settings/campaigns/{campaign_id}/tags` | — | `TagRead[]` |
| S51 | POST | `/api/settings/campaigns/{campaign_id}/tags` | `{name, color?, ...}` | `TagRead` (201) |

## Группа: db-management

| # | Метод | URL | Request Body | Response |
|---|---|---|---|---|
| D1 | GET | `/api/db/documents` | query: `vault_id` (required), `limit`, `offset`, `order_by` | `DocumentsResponse` |
| D2 | GET | `/api/db/chunks` | query: `document_id`, `vault_id` (both required) | `ChunksResponse` |
| D3 | POST | `/api/db/search/text` | `TextSearchRequest` | `TextSearchResponse` |
| D4 | POST | `/api/db/search/domain` | `TextSearchByDomainRequest` | `TextSearchResponse` |
| D5 | DELETE | `/api/db/documents/{document_id}` | query: `vault_id` (required) | `object` |
| D6 | POST | `/vaults/{vault_id}/reindex` | `ReindexRequest?` | `object` |
| D7 | DELETE | `/index-tasks/{task_id}` | — | `object` |
| D8 | GET | `/index-tasks/{task_id}/state` | — | `object` |
| D9 | POST | `/vaults/{vault_id}/detach` | — | `object` |
| D10 | GET | `/db/ui` | — | HTML |

---

## Ключевые схемы

### CreateChatRequest
```json
{
  "domain_id": "string | null",
  "vault_id": "string | null",       // deprecated, back-compat
  "campaign_id": "string | null"
}
```

### CreateChatResponse
```json
{ "chat_id": "string", "title": "string" }
```

### SendMessageRequest
```json
{ "content": "string", "stream": true }
```

### MessageResponse
```json
{ "content": "string", "message_id": "string" }
```

### ChatListResponse
```json
{
  "chats": [
    {
      "chat_id": "string",
      "title": "string",
      "vault_id": "string | null",
      "domain_id": "string | null",
      "vault_enabled": false,
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ]
}
```

### ChatHistoryResponse
```json
{
  "chat": { "id", "title", "vault_id", "domain_id", "campaign_id", "created_at", "updated_at" },
  "messages": [ { "message_id", "role", "content", "created_at", "pipeline_id" } ],
  "vault_enabled": false
}
```

### ClarificationAnswer
```json
{ "clarification_id": "string", "answers": { "field_name": "value" } }
```

### ClarificationResponse
```json
{ "message_id": "string", "role": "assistant", "content": "string", "clarification_id": "string | null", "stage": "string | null" }
```

### TagsGrouped
```json
{ "global_tags": [TagRead], "by_campaign": { "campaign_id": [TagRead] } }
```

### TagCreate (требует domain_id, НЕ vault_id)
```json
{ "name": "string", "domain_id": "string", "campaign_id": "string | null", "color": "string | null" }
```

### CampaignCreate (привязка к домену, НЕ vault)
```json
{ "domain_id": "string", "name": "string", "description": "string | null", "system_prompt": "string | null" }
```

### PipelineCreateRequest
```json
{
  "pipeline_id": "string",
  "domain_id": "string",
  "name": "string",
  "description": "string | null",
  "steps": [object],
  "final_composition": object,
  "is_active": true
}
```

### SSE stream events (`/send_stream`)
- `data: {"type": "token", "content": "..."}` — чанк текста
- `data: {"type": "done", "message_id": "..."}` — конец
- `data: [DONE]` — финальный маркер закрытия стрима
