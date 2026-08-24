from __future__ import annotations

import logging as _logging
import uuid as _uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_log = _logging.getLogger(__name__)

# Sentinel для «атрибут не найден на ORM-объекте» — чтобы не отличать от
# случая, когда атрибут есть, но равен None.
MISSING = object()


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _coerce_uuid_fields(cls, data: Any) -> Any:
        """Авто-конвертация uuid.UUID ORM-атрибутов в str для str-полей.

        ВАЖНО: намеренно пропускаем list-поля (релатионшипы типа tags, chats и т.п.).
        getattr на lazy SQLAlchemy relationship в async-контексте вызывает MissingGreenlet.
        List-поля заполняются явно снаружи (в роуте или хелпере) — не через from_attributes.

        Поддерживает Pydantic `validation_alias`: если у поля есть alias
        (например, ChatRecord.metadata с alias='metadata_json'), сначала
        пробуем `getattr(data, alias, MISSING)`, потом fallback на Pydantic-имя.

        Если атрибут отсутствует на ORM-объекте (например, вычисляемое поле вроде
        `has_initial_state`) — поле пропускается, и Pydantic применяет default.
        Раньше здесь ставился `None`, что ломало bool/int/etc. поля с required type.
        """
        if not hasattr(data, "__dict__") and not hasattr(data, "__mapper__"):
            return data
        result: dict[str, Any] = {}
        for field_name, field_info in cls.model_fields.items():
            annotation = field_info.annotation
            origin = getattr(annotation, "__origin__", None)
            if origin is list:
                continue
            alias = getattr(field_info, "validation_alias", None)
            candidates: list[str] = []
            if isinstance(alias, str):
                candidates.append(alias)
            candidates.append(field_name)
            val: Any = MISSING
            for name in candidates:
                v = getattr(data, name, MISSING)
                if v is not MISSING:
                    val = v
                    break
            if val is MISSING:
                # ORM-объект не содержит атрибута — оставляем default из схемы.
                continue
            if isinstance(val, _uuid.UUID):
                result[field_name] = str(val)
            else:
                result[field_name] = val
        return result


class FileIndexState(BaseModel):
    checksum_md5: str
    status: Literal[
        "pending",
        "parsing",
        "chunking",
        "indexing",
        "done",
        "error",
        "cancelled",
        "empty",
        "indexed",  # back-compat V2.1
    ]
    progress_pct: int = Field(default=0, ge=0, le=100)  # deprecated, back-compat
    chunks_total: int = 0
    chunks_processed: int = 0
    last_modified: datetime
    error: str | None = None


class IndexState(BaseModel):
    version: str = "1.0"
    task_id: str
    vault_id: str
    status: Literal["running", "done", "error", "cancelled"]
    last_updated: datetime
    files: dict[str, FileIndexState] = Field(default_factory=dict)
    error: str | None = None


class DocumentRecord(BaseModel):
    document_id: str
    vault_id: str
    source_path: str
    checksum: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunk_count: int = 0


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    vault_id: str
    text: str
    vector: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None


class EntityRecord(BaseModel):
    entity_id: str
    kind: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_chunk_ids: list[str] = Field(default_factory=list)


class VaultBinding(BaseModel):
    vault_id: str
    embedding_model_id: str
    expected_dimensions: int = Field(gt=0)
    locked: bool = False
    status: Literal["unbound", "binding", "bound", "error"] = "unbound"
    chunk_count: int = 0


class DomainRead(ORMModel):
    domain_id: str
    display_name: str
    description: str | None = None
    is_system: bool = False
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DomainCreate(BaseModel):
    domain_id: str
    display_name: str
    description: str | None = None
    enabled: bool = True


class DomainUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    enabled: bool | None = None


class DomainPromptRead(ORMModel):
    id: str | None = None
    domain_id: str
    prompt_type: Literal["system", "clarification", "planner", "pipeline_router"]
    content: str
    updated_at: datetime | None = None


class DomainPromptUpdate(BaseModel):
    content: str


class DomainClarificationFieldRead(ORMModel):
    id: str | None = None
    domain_id: str
    field_name: str
    label: str
    hint: str | None = None
    required: bool = True
    display_order: int = 0


class DomainClarificationFieldCreate(BaseModel):
    field_name: str
    label: str
    hint: str | None = None
    required: bool = True
    display_order: int = 0


class PlatformSettingRead(ORMModel):
    key: str
    value: Any
    value_type: Literal["int", "float", "bool", "str"]
    group_name: str
    label: str
    hint: str
    updated_at: datetime | None = None


class PlatformSettingUpdate(BaseModel):
    value: Any


class GenerationModelRead(ORMModel):
    model_id: str
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str
    timeout_seconds: int = 60
    is_active: bool = False
    enabled: bool = True
    has_api_key: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GenerationModelCreate(BaseModel):
    model_id: str
    provider: str = "openai_compatible"
    display_name: str | None = None
    base_url: str
    api_key: str | None = None
    timeout_seconds: int = 60
    enabled: bool = True


class GenerationModelUpdate(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None


class EmbeddingModelRead(ORMModel):
    model_id: str
    provider: Literal["ollama", "openai_compatible"]
    display_name: str | None = None
    model_name: str
    base_url: str
    dimensions: int
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True
    has_api_key: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EmbeddingModelCreate(BaseModel):
    model_id: str
    provider: Literal["ollama", "openai_compatible"]
    display_name: str | None = None
    model_name: str
    base_url: str
    api_key: str | None = None
    dimensions: int = Field(gt=0)
    timeout_seconds: int = 30
    max_retries: int = 3
    enabled: bool = True


class EmbeddingModelUpdate(BaseModel):
    provider: Literal["ollama", "openai_compatible"] | None = None
    display_name: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    timeout_seconds: int | None = None
    max_retries: int | None = None
    enabled: bool | None = None


class VaultRead(ORMModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    enabled: bool = True
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    semantic_threshold: float = 0.3
    binding_status: Literal["unbound", "indexing", "bound", "error"] = "unbound"
    chunk_count: int = 0
    # Git identity — added by migration 0005_campaign_update_git_identity
    git_author_name: str | None = None
    git_author_email: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VaultCreate(BaseModel):
    vault_id: str
    domain_id: str
    display_name: str | None = None
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    semantic_threshold: float = 0.3
    # Git identity — optional, persisted to DB
    git_author_name: str | None = None
    git_author_email: str | None = None


class VaultUpdate(BaseModel):
    domain_id: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    semantic_threshold: float | None = None
    binding_status: Literal["unbound", "indexing", "bound", "error"] | None = None
    chunk_count: int | None = None
    # Git identity — per-vault override for git commits
    git_author_name: str | None = None
    git_author_email: str | None = None


class TagRead(ORMModel):
    """Тег принадлежит домену (не Vault)."""

    id: str
    name: str
    domain_id: str
    campaign_id: str | None = None
    color: str | None = None
    created_at: datetime | None = None


class TagCreate(BaseModel):
    """Создание тега: привязка к домену, не к Vault."""

    name: str
    domain_id: str
    campaign_id: str | None = None
    color: str | None = None


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class TagsGrouped(BaseModel):
    """Ответ GET /tags — теги сгруппированы для UI"""

    global_tags: list[TagRead] = []
    by_campaign: dict[str, list[TagRead]] = {}  # campaign_id → теги


class DocumentRead(ORMModel):
    id: str
    vault_id: str
    source_path: str
    title: str | None = None
    md5: str
    mtime: int
    indexed_at: datetime | None = None
    status: Literal["pending", "indexed", "error"]
    char_count: int | None = None
    chunk_count: int | None = None
    estimated_tokens: int | None = None
    tags: list[TagRead] = []
    created_at: datetime | None = None


class DocumentCandidate(BaseModel):
    document_id: str
    title: str
    source_path: str
    char_count: int | None = None
    chunk_count: int | None = None
    estimated_tokens: int | None = None
    already_sent: bool


class DocumentLabelWrite(BaseModel):
    """Полная замена тегов документа"""

    tag_ids: list[str]


class CampaignRead(ORMModel):
    """Кампания принадлежит домену (не Vault)."""

    id: str
    domain_id: str
    name: str
    description: str | None = None
    system_prompt: str | None = None
    last_session_at: datetime | None = None
    created_at: datetime | None = None
    tags: list[TagRead] = []
    # Stage 6: true если у кампании есть хотя бы одна active state version
    # (т.е. был применён Initial State).
    has_initial_state: bool = False


class CampaignCreate(BaseModel):
    """Создание кампании: привязка к домену, не к Vault."""

    domain_id: str
    name: str
    description: str | None = None
    system_prompt: str | None = None


class CampaignUpdate(BaseModel):
    # все поля optional — partial update; min_length на name чтобы нельзя было случайно обнулить
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    system_prompt: str | None = None


# ---------------------------------------------------------------------------
# Campaign State — Stage 1: Field Configuration contracts
# ---------------------------------------------------------------------------

CampaignStateFieldMode = Literal["single", "list"]


class CampaignStateFieldConfigRead(ORMModel):
    """Конфигурация поля Campaign State (метаданные).

    Актуальные значения state хранятся в отдельной таблице (Stage 2).
    """

    id: str
    campaign_id: str
    key: str
    label: str
    description: str = ""
    mode: CampaignStateFieldMode
    enabled: bool = True
    display_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CampaignStateFieldConfigCreate(BaseModel):
    """Создание поля Campaign State.

    key — стабильный технический идентификатор, immutable после создания.
    mode — допускается только при создании (смена запрещена).
    """

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8 * 1024)
    mode: CampaignStateFieldMode
    enabled: bool = True
    display_order: int = Field(default=0, ge=0)


class CampaignStateFieldConfigUpdate(BaseModel):
    """Partial update. key и mode — НЕ допускаются (immutable).

    Если клиент пришлёт их явно — сервис вернёт 409.
    """

    label: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=8 * 1024)
    enabled: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    # Sentinel-поля: клиент не должен их посылать. Сервис отклонит запрос с 409.
    # Помечены как optional, чтобы Pydantic не выкидывал их из тела запроса раньше
    # времени, и проверка immutability в сервисе могла сработать.
    key: str | None = Field(default=None, exclude=True)
    mode: str | None = Field(default=None, exclude=True)


class CampaignStateFieldConfigReorderRequest(BaseModel):
    """Body для POST /state-fields/reorder.

    field_ids должны:
      - быть уникальными;
      - принадлежать указанной кампании;
      - покрывать ровно весь набор полей кампании (len == current count).
    """

    field_ids: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Campaign State — Stage 2: Versioned State contracts
# ---------------------------------------------------------------------------

CampaignStateSourceKind = Literal["initial", "patch"]


class CampaignStateSingleValueRead(ORMModel):
    """Значение single-поля в конкретной версии state.

    source_refs — массив строк формата:
      - "file:<document_id>:sha:<sha256>"
      - "chat:<message_id>"
      - "vault:<vault_id>"
    """

    field_key: str
    text: str
    source_refs: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class CampaignStateListItemRead(ORMModel):
    """Элемент list-поля в конкретной версии state."""

    field_key: str
    item_key: str
    text: str
    resolved: bool = False
    source_refs: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class CampaignStateFieldValuesRead(ORMModel):
    """Снимок значений одного поля в конкретной версии state.

    Для single: single_value непуст, items пуст.
    Для list: single_value отсутствует, items содержит элементы.
    """

    field_key: str
    field_id: str
    mode: CampaignStateFieldMode
    enabled: bool
    display_order: int
    single_value: CampaignStateSingleValueRead | None = None
    items: list[CampaignStateListItemRead] = Field(default_factory=list)


class CampaignStateVersionSummary(ORMModel):
    """Краткая мета-информация о версии state."""

    id: str
    campaign_id: str
    state_version: int
    config_version: int
    source_kind: CampaignStateSourceKind
    base_state_version: int | None = None
    created_at: datetime | None = None
    created_by: str | None = None


class CampaignStateVersionRead(ORMModel):
    """Полный снимок версии state: мета + значения всех полей кампании."""

    summary: CampaignStateVersionSummary
    fields: list[CampaignStateFieldValuesRead] = Field(default_factory=list)


# --- Patch operations (discriminated union) -------------------------------

CampaignStatePatchOperationType = Literal[
    "replace_single",
    "clear_single",
    "add_list_item",
    "update_list_item",
    "resolve_list_item",
    "remove_list_item",
]


class _CampaignStatePatchBase(BaseModel):
    """Общие поля для всех patch-операций."""

    reason: str = Field(min_length=1, max_length=1024)
    source_refs: list[str] = Field(default_factory=list)


class CampaignStateReplaceSingle(_CampaignStatePatchBase):
    type: Literal["replace_single"] = "replace_single"
    field_key: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=8192)


class CampaignStateClearSingle(_CampaignStatePatchBase):
    type: Literal["clear_single"] = "clear_single"
    field_key: str = Field(min_length=1, max_length=64)


class CampaignStateAddListItem(_CampaignStatePatchBase):
    type: Literal["add_list_item"] = "add_list_item"
    field_key: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=8192)


class CampaignStateUpdateListItem(_CampaignStatePatchBase):
    type: Literal["update_list_item"] = "update_list_item"
    field_key: str = Field(min_length=1, max_length=64)
    item_key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8192)


class CampaignStateResolveListItem(_CampaignStatePatchBase):
    type: Literal["resolve_list_item"] = "resolve_list_item"
    field_key: str = Field(min_length=1, max_length=64)
    item_key: str = Field(min_length=1, max_length=128)


class CampaignStateRemoveListItem(_CampaignStatePatchBase):
    type: Literal["remove_list_item"] = "remove_list_item"
    field_key: str = Field(min_length=1, max_length=64)
    item_key: str = Field(min_length=1, max_length=128)


CampaignStatePatchOperation = (
    CampaignStateReplaceSingle
    | CampaignStateClearSingle
    | CampaignStateAddListItem
    | CampaignStateUpdateListItem
    | CampaignStateResolveListItem
    | CampaignStateRemoveListItem
)


class CampaignStatePatchRequest(BaseModel):
    """Запрос применения patch к Campaign State.

    - base_state_version: сервер проверяет соответствие активной версии.
      При несовпадении возвращается 409 + server snapshot (no silent overwrite).
    - config_version: должна совпадать с текущей Campaign.config_version.
    """

    base_state_version: int | None = Field(default=None, ge=1)
    config_version: int = Field(ge=1)
    operations: list[CampaignStatePatchOperation] = Field(min_length=1)


class CampaignStatePatchRejection(BaseModel):
    """Описание отклонённой операции.

    Возвращается при валидационном отказе одной из операций:
      - неизвестный field_key;
      - нарушение mode ↔ type;
      - неизвестный item_key для update/resolve/remove;
      - пустой reason.
    """

    op_index: int
    op_type: CampaignStatePatchOperationType
    code: Literal[
        "field_not_found",
        "mode_mismatch",
        "item_not_found",
        "invalid_source_ref",
        "invalid_payload",
    ]
    detail: str = ""


class CampaignStatePatchResponse(BaseModel):
    """Ответ на успешно применённый patch.

    failed_operations заполняется только если валидация одной или нескольких
    операций провалилась. На этапе 2 используется fail-fast: первая же
    ошибка прерывает apply; failed_operations содержит ровно одну запись.
    """

    applied_state_version: int
    config_version: int
    applied_operations: list[CampaignStatePatchOperationType] = Field(
        default_factory=list
    )
    failed_operations: list[CampaignStatePatchRejection] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Campaign State — Stage 3: Initial State contracts
# ---------------------------------------------------------------------------

CampaignStateSourceType = Literal["file"]

CampaignStateInitialFieldStatusValue = Literal[
    "proposed", "empty", "needs_clarification"
]


class DocumentSnapshot(BaseModel):
    """Снимок файла-источника на момент формирования proposal.

    content_sha хранит md5 hex-дайджест (32 hex символа) — соответствует
    Document.md5 на момент preview. Используется для проверки неизменности
    источника между preview и apply.
    """

    document_id: str
    vault_id: str
    source_path: str
    title: str | None = None
    content_sha: str = Field(min_length=32, max_length=32)
    estimated_tokens: int = Field(ge=0)


class CampaignStateInitialSingleValue(BaseModel):
    """Значение single-поля в proposal."""

    text: str = Field(min_length=1, max_length=8192)
    source_refs: list[str] = Field(default_factory=list)


class CampaignStateInitialListItem(BaseModel):
    """Элемент list-поля в proposal. item_key НЕ задаётся LLM — генерируется сервером."""

    text: str = Field(min_length=1, max_length=8192)
    source_refs: list[str] = Field(default_factory=list)


class CampaignStateInitialListValue(BaseModel):
    items: list[CampaignStateInitialListItem] = Field(default_factory=list)


class CampaignStateInitialFieldStatus(BaseModel):
    """Статус поля в proposal.

    - "proposed": LLM предлагает значение/элементы, single_value/list_value заполнены.
    - "empty": надёжных данных нет, поле остаётся пустым.
    - "needs_clarification": источники противоречат друг другу или данных недостаточно;
      clarification_question обязателен и показывается пользователю.
    """

    status: CampaignStateInitialFieldStatusValue
    clarification_question: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _check_clarification_question(self) -> CampaignStateInitialFieldStatus:
        if self.status == "needs_clarification" and (
            not self.clarification_question
            or not self.clarification_question.strip()
        ):
            raise ValueError(
                "clarification_question is required when status == 'needs_clarification'"
            )
        return self


class CampaignStateInitialProposalField(BaseModel):
    """Одно поле в proposal.

    Для mode == "single" ожидается заполненный single_value при status='proposed'.
    Для mode == "list" ожидается заполненный list_value при status='proposed'.
    """

    field_key: str = Field(min_length=1, max_length=64)
    mode: CampaignStateFieldMode
    status: CampaignStateInitialFieldStatus
    single_value: CampaignStateInitialSingleValue | None = None
    list_value: CampaignStateInitialListValue | None = None


class CampaignStateInitialProposal(BaseModel):
    """Полный LLM-proposal для Initial State.

    Поля списка `fields` должны содержать ровно одну запись на каждое
    enabled-поле кампании — это валидируется на уровне сервиса.
    """

    fields: list[CampaignStateInitialProposalField] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class CampaignStateInitialProposalRead(BaseModel):
    """Proposal + мета, возвращается клиенту и хранится в Redis."""

    proposal_id: str
    campaign_id: str
    config_version: int
    source_snapshot: list[DocumentSnapshot]
    proposal: CampaignStateInitialProposal
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime


class CampaignStateInitialPreviewRequest(BaseModel):
    """Запрос на формирование initial proposal из выбранных Markdown-документов."""

    document_ids: list[str] = Field(min_length=1, max_length=50)


class CampaignStateInitialApplyRequest(BaseModel):
    """Запрос на применение initial proposal (review/approval).

    `proposal_overrides` — необязательный частичный proposal, который мерджится
    поверх proposal, хранящегося в Redis, по `field_key`. Позволяет клиенту
    отредактировать текст single_value и/или list_value.items перед apply.

    Слияние:
      - Берётся базовый proposal из Redis.
      - Для каждого поля из overrides.mode/status/single_value/list_value
        соответствующее поле в базовом proposal заменяется (если field_key
        есть в базовом proposal).
      - Если field_key отсутствует в базовом proposal — поле игнорируется.
      - source_snapshot не затрагивается.
    """

    proposal_id: str = Field(min_length=1, max_length=64)
    config_version: int = Field(ge=1)
    proposal_overrides: CampaignStateInitialProposal | None = None


# ---------------------------------------------------------------------------
# Campaign State — Stage 3.v2: Initial State with propose_fields
# ---------------------------------------------------------------------------
#
# Расширение Initial State: когда у кампании 0 enabled-полей, клиент может
# отправить `propose_fields=true` и попросить LLM САМОМУ предложить набор полей
# (key/label/description/mode) вместе со значениями. Пользователь ревьюит/правит
# в Wizard, отклоняет ненужные и применяет всё одной транзакцией.
#
# Backward-compat: V1 контракты сохранены как есть. suggested_fields всегда
# опциональный список; при propose_fields=False любые suggested_fields от LLM
# отбрасываются на бэкенде с warning.


class CampaignStateSuggestedFieldConfig(BaseModel):
    """Предложение нового поля Campaign State от LLM (Stage 3.v2).

    Семантика:
      - key — стабильный snake_case идентификатор; проходит regex Field Key regex.
      - label — человеко-читаемый заголовок (1..256 символов).
      - description — подсказка для будущих LLM-вызовов (≤8KB, опционально).
      - mode — single или list; immutable после создания.
      - initial_status — предлагаемый статус значения: proposed/empty/needs_clarification.
      - single_value / list_value — заполняются при status=proposed.
        mode должен соответствовать: mode=single ↔ single_value, mode=list ↔ list_value.
    """

    key: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
        description="Stable snake_case key (regex ^[a-z][a-z0-9_]{0,63}$).",
    )
    label: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8 * 1024)
    mode: CampaignStateFieldMode
    initial_status: CampaignStateInitialFieldStatusValue
    clarification_question: str | None = Field(default=None, max_length=1024)
    single_value: CampaignStateInitialSingleValue | None = None
    list_value: CampaignStateInitialListValue | None = None

    @model_validator(mode="after")
    def _check_mode_value_consistency(self) -> CampaignStateSuggestedFieldConfig:
        # 1) needs_clarification ↔ clarification_question обязательно
        if self.initial_status == "needs_clarification" and (
            not self.clarification_question
            or not self.clarification_question.strip()
        ):
            raise ValueError(
                "clarification_question is required when initial_status == 'needs_clarification'"
            )
        # 2) mode ↔ value shape
        if self.initial_status == "proposed":
            if self.mode == "single" and self.single_value is None:
                raise ValueError(
                    "single_value is required for mode=single when initial_status='proposed'"
                )
            if self.mode == "list" and self.list_value is None:
                raise ValueError(
                    "list_value is required for mode=list when initial_status='proposed'"
                )
            if self.mode == "single" and self.list_value is not None:
                raise ValueError(
                    "list_value must be None when mode=single"
                )
            if self.mode == "list" and self.single_value is not None:
                raise ValueError(
                    "single_value must be None when mode=list"
                )
        return self


class CampaignStateInitialProposalV2(BaseModel):
    """Proposal с возможными suggested_fields (Stage 3.v2).

    Для существующих полей кампании (Stage 1) LLM заполняет `fields`.
    Для новых полей, которые LLM предлагает создать — `suggested_fields`.
    Список `suggested_fields` не зависит от текущих enabled-полей.
    """

    fields: list[CampaignStateInitialProposalField] = Field(default_factory=list)
    suggested_fields: list[CampaignStateSuggestedFieldConfig] = Field(
        default_factory=list
    )
    questions: list[str] = Field(default_factory=list)


class CampaignStateInitialProposalReadV2(CampaignStateInitialProposalRead):
    """Read-форма с поддержкой V2 (suggested_fields). Полная обратная совместимость:

    Клиент, ожидающий `proposal.suggested_fields`, получит пустой массив, если
    сервер не отправляет V2 — pydantic-сериализация v1 → v2 не отличается на
    стороне клиента (новые поля опциональны с default).
    """

    proposal: CampaignStateInitialProposalV2


class CampaignStateInitialPreviewRequestV2(BaseModel):
    """Запрос preview с поддержкой propose_fields (Stage 3.v2).

    propose_fields=False (по умолчанию) → поведение V1 (только значения для
    существующих полей). Если 0 enabled-полей и propose_fields=False, сервис
    вернёт 422 no_fields_configured_no_propose.

    propose_fields=True → LLM также может предложить `suggested_fields` в ответе.
    Требует ≥1 enabled-поля ИЛИ работает при 0 enabled-полей (Wizard UI).
    """

    document_ids: list[str] = Field(min_length=1, max_length=50)
    propose_fields: bool = False
    max_suggested_fields: int = Field(default=15, ge=0, le=50)


class CampaignStateInitialApplyRequestV2(CampaignStateInitialApplyRequest):
    """Apply с поддержкой принятия/отклонения suggested_fields.

    accepted_suggested_field_keys — какие предложенные поля создать перед apply.
    rejected_suggested_field_keys — какие отклонить (не создавать).
    Каждый ключ должен быть уникальным; дубликаты между accepted/rejected
    игнорируются на бэкенде с warning.

    proposal_overrides (V1) — по-прежнему может присутствовать и применяется
    к значениям (как existing, так и suggested) перед apply.
    """

    accepted_suggested_field_keys: list[str] = Field(
        default_factory=list,
        max_length=50,
    )
    rejected_suggested_field_keys: list[str] = Field(
        default_factory=list,
        max_length=50,
    )


# ---------------------------------------------------------------------------
# Campaign State — Stage 6: Prompt Assembly contracts
# ---------------------------------------------------------------------------


class CampaignStateCompiledFieldRead(BaseModel):
    """Результат компиляции одного поля для prompt.

    included=False — поле исключено из prompt (truncated либо пустое);
    для empty-полей флаг остаётся False без truncated.
    """

    field_key: str
    field_id: str
    label: str
    mode: CampaignStateFieldMode
    included: bool
    truncated: bool
    rendered_text: str
    estimated_tokens: int
    items_included: int = 0
    items_total: int = 0


class CampaignStateCompiledBlock(BaseModel):
    """Детерминированно скомпилированный текст Campaign State для prompt.

    Если active state отсутствует или все поля пустые/исключены — text == "",
    used_tokens == 0, остальные списки пусты.
    """

    state_version: int | None = None
    config_version: int | None = None
    budget_tokens: int
    used_tokens: int
    truncated_fields: list[str] = Field(default_factory=list)
    empty_fields: list[str] = Field(default_factory=list)
    fields: list[CampaignStateCompiledFieldRead] = Field(default_factory=list)
    text: str = ""


class EffectiveContextBlock(BaseModel):
    """Один блок, попавший в финальный system prompt чата.

    name — стабильный ключ ("system_prompt" | "campaign_state" | "rag_context"
    | "history" | "user_message"). user_message для debug-эндпойнта всегда "",
    history рендерится строкой только если расчёт токенов выполнен на полном тексте.
    """

    name: str
    text: str
    estimated_tokens: int


class EffectiveContextRead(BaseModel):
    """Полный effective-context для дебага prompt assembly."""

    campaign_id: str | None = None
    chat_id: str | None = None
    domain_id: str | None = None
    blocks: list[EffectiveContextBlock] = Field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0
    truncated_fields: list[str] = Field(default_factory=list)
    state_version: int | None = None


class CampaignStateStaleStatus(BaseModel):
    """Текущий stale-статус Campaign State (Stage 7).

    Вычисляется на лету из Redis vault-cache + Document.md5.
    Не персистится в БД (кроме AuditLog на переходе false→true).

    Поля:
      - potentially_stale: true если хотя бы один .md source_ref активной
        версии state указывает на файл с изменённым md5 или ожидающим
        reindex (index_status ∈ {pending, stale, deleted}) или
        Document.status != indexed.
      - stale_documents: document_id в порядке обнаружения.
      - active_state_version: state_version, для которой считали; null если
        state ещё не применён.
      - checked_at: момент проверки (UTC).
    """

    potentially_stale: bool
    stale_documents: list[str] = Field(default_factory=list)
    active_state_version: int | None = None
    checked_at: datetime


# ---------------------------------------------------------------------------
# Pipeline contracts — DAG-based execution model
# ---------------------------------------------------------------------------


class PipelineStep(BaseModel):
    """Шаг пайплайна в DAG-модели.

    Правила:
    - step_id уникален в рамках одного пайплайна (проверяется в Pipeline-валидаторе)
    - after_step_ids не может содержать собственный step_id (self-loop)
    - Поля top_k, tag_ids, role, output_format, send_full_document — только для type=retrieval
    - Поля validation_prompt, options — только для type=validation
    """

    step_id: str  # user-defined slug, e.g. "analyze"
    type: Literal["retrieval", "validation"]
    name: str  # отображаемое название
    system_prompt: str  # поддерживает {STEP_ID.result}, {STEP_ID.key}, {query}
    after_step_ids: list[str] = Field(default_factory=list)  # [] = стартовый шаг

    # --- только для type=retrieval ---
    top_k: int | None = None
    tag_ids: list[str] = Field(default_factory=list)
    role: str | None = None
    output_format: Literal["text", "json"] = "text"
    # Загрузить полный текст документов под tag_ids вместо top-k чанков.
    # Источник: документы, попадающие под tag_ids в домене чата.
    # Полезно когда важный контекст описан в небольшом файле.
    # При True — top_k игнорируется, rerank не применяется, per-doc/total token-бюджеты
    # ограничивают объём (см. pipeline_executor.PER_DOC_TOKEN_LIMIT / TOTAL_TOKEN_BUDGET).
    send_full_document: bool = False

    # --- только для type=validation ---
    validation_prompt: str | None = None  # поддерживает {STEP_ID.result}
    options: list[str] | None = None  # варианты выбора (опционально)

    @model_validator(mode="after")
    def _validate_step(self) -> PipelineStep:
        # self-loop
        if self.step_id in self.after_step_ids:
            raise ValueError(
                f"Step '{self.step_id}' cannot reference itself in after_step_ids"
            )
        # поля только для retrieval
        if self.type == "validation":
            if self.top_k is not None:
                raise ValueError("top_k is only valid for type=retrieval")
            if self.tag_ids:
                raise ValueError("tag_ids is only valid for type=retrieval")
            if self.role is not None:
                raise ValueError("role is only valid for type=retrieval")
            if self.output_format != "text":
                raise ValueError("output_format is only valid for type=retrieval")
            if self.send_full_document:
                raise ValueError("send_full_document is only valid for type=retrieval")
        # поля только для validation
        if self.type == "retrieval":
            if self.validation_prompt is not None:
                raise ValueError("validation_prompt is only valid for type=validation")
            if self.options is not None:
                raise ValueError("options is only valid for type=validation")
        return self


class FinalComposition(BaseModel):
    """Финальная LLM-композиция после всех шагов пайплайна.

    Поддерживаемые переменные в system_prompt:
      {STEP_ID.result}   — полный текстовый результат шага
      {STEP_ID.key}      — ключ из JSON-результата шага (output_format=json)
      {query}            — запрос пользователя

    УДАЛЕНЫ (ломающее изменение, применяется миграционным скриптом в Этапе 2):
      {context}          — заменить на явные {STEP_ID.result}
      {collected_fields} — если нужны — передать через validation-шаг
    """

    system_prompt: str


class PipelineRead(ORMModel):
    id: str
    pipeline_id: str
    domain_id: str
    campaign_id: str | None = None  # None = общий пайплайн домена
    version: str
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition
    is_active: bool = True
    created_at: datetime | None = None


class PipelineCreate(BaseModel):
    pipeline_id: str
    domain_id: str
    campaign_id: str | None = None
    name: str
    description: str | None = None
    steps: list[PipelineStep]
    final_composition: FinalComposition

    @model_validator(mode="after")
    def _validate_unique_step_ids(self) -> PipelineCreate:
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            duplicates = [sid for sid in ids if ids.count(sid) > 1]
            raise ValueError(f"Duplicate step_ids in pipeline: {list(set(duplicates))}")
        return self


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[PipelineStep] | None = None
    final_composition: FinalComposition | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_unique_step_ids(self) -> PipelineUpdate:
        if self.steps is not None:
            ids = [s.step_id for s in self.steps]
            if len(ids) != len(set(ids)):
                duplicates = [sid for sid in ids if ids.count(sid) > 1]
                raise ValueError(
                    f"Duplicate step_ids in pipeline: {list(set(duplicates))}"
                )
        return self


class RetrievalContext(BaseModel):
    """Контекст выполнения пайплайна. vault_id оставлен для back-compat (TODO: удалить в iter4-cleanup)."""

    query: str
    vault_ids: list[str] = Field(default_factory=list)  # все enabled-Vault домена
    vault_id: str | None = None  # deprecated back-compat; используй vault_ids
    domain_id: str | None = None
    campaign_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    top_k: int = 5
    metadata_filter: dict[str, Any] | None = None


class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str
    vault_id: str | None = None
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime
    pipeline_id: str | None = None
    sources: list[MessageSource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LLM tool-call contracts (Stage 8: conditional/cyclic RAG)
# ---------------------------------------------------------------------------


class LLMToolCallFunction(BaseModel):
    """Function payload of a single OpenAI-style tool call."""

    name: str
    arguments: str  # raw JSON string from the model; parsed by the host


class LLMToolCall(BaseModel):
    """One tool call from the LLM response.

    `id` correlates the tool call with the `role=tool` message that returns its result.
    `index` is used during streaming: deltas with the same index refer to the same
    tool call (OpenAI streams them in pieces — name, then arguments by character).
    """

    id: str
    type: Literal["function"] = "function"
    function: LLMToolCallFunction
    index: int = 0


class LLMToolDefinitionFunction(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class LLMToolDefinition(BaseModel):
    """OpenAI-style tool definition (function-calling schema)."""

    type: Literal["function"] = "function"
    function: LLMToolDefinitionFunction


class LLMToolChoice(BaseModel):
    """OpenAI tool_choice payload: 'auto' | 'none' | required | specific function."""

    mode: Literal["auto", "none", "required"] = "auto"
    function_name: str | None = None

    def to_openai(self) -> str | dict[str, Any]:
        if self.mode in ("auto", "none", "required"):
            return self.mode
        if self.function_name:
            return {"type": "function", "function": {"name": self.function_name}}
        return "auto"


class LLMAssistantMessage(BaseModel):
    """Internal message that the agent loop builds after each LLM response.

    `tool_calls` is non-empty when the LLM requested tool invocations.
    `content` may be empty in that case (model emitted only tool_calls).
    """

    role: Literal["assistant"] = "assistant"
    content: str = ""
    tool_calls: list[LLMToolCall] = Field(default_factory=list)


class LLMToolMessage(BaseModel):
    """Tool-role message that the host appends after executing a tool call.

    Multiple tool calls from one assistant message each get their own
    `role=tool` message with the matching `tool_call_id`.
    """

    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str


class RetrievalPolicy(StrEnum):
    ASSISTIVE = "assistive"
    GROUNDED = "grounded"


class AgentRoundResult(BaseModel):
    """Snapshot of one round in the agent loop, for streaming and audit."""

    round: int
    queries: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    reason: str | None = None
    hits_count: int = 0
    evidence_tokens: int = 0
    scope: Literal["campaign", "domain", "empty", "no_vault"] = "domain"
    skipped_reason: str | None = None
    sources: list[MessageSource] = Field(default_factory=list)


class SearchKnowledgeRequest(BaseModel):
    queries: list[str] = Field(min_length=1)
    reason: str = ""


class SearchKnowledgeResult(BaseModel):
    queries_used: list[str] = Field(default_factory=list)
    hits: list[SearchHit] = Field(default_factory=list)
    scope: Literal["campaign", "domain", "empty", "no_vault"] = "domain"
    evidence_tokens: int = 0
    note: str | None = None


class AgentLoopResult(BaseModel):
    content: str
    rounds: list[AgentRoundResult] = Field(default_factory=list)
    tool_calls_made: int = 0
    policy: RetrievalPolicy = RetrievalPolicy.ASSISTIVE


class ChatRecord(ORMModel):
    id: str
    title: str
    vault_id: str | None = (
        None  # TODO(iter4-cleanup): удалить после полного перехода фронта на domain_id
    )
    domain_id: str | None = None
    campaign_id: str | None = None
    locked_pipeline_id: str | None = (
        None  # fix: поле отсутствовало — фронт не получал значение после lock
    )
    full_document_mode_enabled: bool = False
    sent_full_document_ids: list[str] = Field(default_factory=list)
    # --- agent-assistant (Sprint 1) ---
    # `metadata_json` is the SQLAlchemy attribute name (avoids `Base.metadata`
    # clash). Wire `validation_alias` so `from_attributes=True` still picks up
    # the column correctly. `populate_by_name` keeps dict-style construction
    # flexible for tests.
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_json",
    )
    context_update_mode: bool = False
    created_at: datetime
    updated_at: datetime


class AuditLogRead(ORMModel):
    id: str
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    actor: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class VaultConfigEntry(BaseModel):
    """Read/cache contract for a single vault's configuration.

    Mirrors the `vaults` DB table columns used by the indexer for runtime
    decisions (embedding model, chunking, git identity).
    Additions here must stay in sync with migration 0005_campaign_update_git_identity.
    """

    vault_id: str
    domain_id: str
    enabled: bool = True
    embedding_model_id: str | None = None
    expected_dimensions: int | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    entity_aware_mode: bool | None = None
    semantic_threshold: float = 0.3
    binding_status: str = "unbound"
    chunk_count: int = 0
    # Git identity fields — added by migration 0005_campaign_update_git_identity.
    # Used by indexer to sign commits; fallback to env GIT_AUTHOR_NAME/EMAIL when None.
    git_author_name: str | None = None
    git_author_email: str | None = None


class VaultConfig(BaseModel):
    vaults: dict[str, VaultConfigEntry] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    vault_id: str
    texts: list[str]
    model_id: str | None = None


class EmbeddingResponse(BaseModel):
    vault_id: str
    embeddings: list[list[float]]
    model_id: str


class IndexRequest(BaseModel):
    vault_id: str
    force: bool = False


class IndexResponse(BaseModel):
    vault_id: str
    task_id: str
    status: str


class IndexStatusResponse(BaseModel):
    vault_id: str
    task_id: str | None
    status: str
    progress_pct: int = 0
    chunks_total: int = 0
    chunks_processed: int = 0
    error: str | None = None
    files: dict[str, FileIndexState] = Field(default_factory=dict)


class CreateChatRequest(BaseModel):
    """
    domain_id — основной идентификатор контекста чата.
    vault_id оставлен nullable для back-compat (старые клиенты).
    campaign_id — опциональная привязка к кампании (iter2).
    TODO(iter4-cleanup): сделать domain_id обязательным, убрать vault_id.
    """

    domain_id: str | None = None
    vault_id: str | None = None  # deprecated back-compat
    campaign_id: str | None = None


class CreateChatResponse(BaseModel):
    chat_id: str
    title: str


class SendMessageRequest(BaseModel):
    content: str
    stream: bool = True


class ClarificationResponse(BaseModel):
    message_id: str
    role: Literal["assistant"] = "assistant"
    content: str
    clarification_id: str | None = None
    stage: str | None = None


class ClarificationAnswer(BaseModel):
    clarification_id: str
    answers: dict[str, str]


# ---------------------------------------------------------------------------
# Clarification FSM state contract
# ---------------------------------------------------------------------------


class ClarificationState(BaseModel):
    """Пыдантик-DTO состояния машины уточняющих вопросов.

    Не является ORM-моделью — живёт только в памяти и передаётся
    между clarification_fsm и chat-роутом.
    Персистируется через ClarificationState ORM-строку в БД
    (app/db/models.py :: ClarificationState).
    """

    stage: Literal["idle", "collecting", "complete", "fallback"] = "idle"
    missing_fields: list[str] = Field(default_factory=list)
    collected: dict[str, str] = Field(default_factory=dict)
    turn: int = 0
    next_question: str | None = None


class PipelineExecutionContext(BaseModel):
    """Полный контекст для запуска пайплайна.

    pipeline_id, pipeline_version, steps, final_composition — Optional:
    объект создаётся до pipeline_router.select(), затем поля дописываются.
    PipelineExecutor обязан проверять что поля заполнены перед запуском.

    step_results — накапливается в процессе выполнения DAG:
      output_format=text  → step_results[step_id] = "строка"
      output_format=json  → step_results[step_id] = dict (при ошибке парсинга — строка)
      type=validation     → step_results[step_id] = ответ пользователя (строка)
    """

    chat_id: str
    message_id: str
    query: str
    original_query: str | None = None  # оригинал до переформулировки QueryRewriter-ом
    domain_id: str | None = None
    campaign_id: str | None = None
    vault_ids: list[str] = Field(default_factory=list)
    vault_id: str | None = None  # deprecated back-compat; используй vault_ids
    # C-STREAM02: заполняются после pipeline_router.select() — не при создании объекта
    pipeline_id: str | None = None
    pipeline_version: str | None = None
    steps: list[PipelineStep] | None = None
    final_composition: FinalComposition | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_strategy: str | None = None
    # Заполняются pipeline_router.select() после выбора пайплайна
    confidence: float | None = None
    reasoning: str | None = None
    mode: str | None = None
    # Накапливается в процессе DAG-выполнения
    step_results: dict[str, Any] = Field(default_factory=dict)

    def resolve(self, template: str) -> str:
        """Подставить {STEP_ID.result} и {STEP_ID.key} из накопленных step_results.

        Также поддерживает {query} — подставляется напрямую через format_map.
        Делегирует в resolve_step_vars() из prompt_pack.
        """
        try:
            from app.services.prompt_pack import (
                resolve_step_vars,  # type: ignore[import]
            )
        except ImportError:
            from prompt_pack import resolve_step_vars  # type: ignore[import]

        resolved = template.replace("{query}", self.query)
        return resolve_step_vars(resolved, self.step_results)


class PipelineStepResult(BaseModel):
    step_id: str  # slug шага (новое поле)
    step_name: str
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    llm_output: str | None = None
    error: str | None = None


class PipelineResult(BaseModel):
    pipeline_id: str
    pipeline_version: str
    steps: list[PipelineStepResult] = Field(default_factory=list)
    final_answer: str
    error: str | None = None


# ---------------------------------------------------------------------------
# LanceDB / db-api-server contracts
# ---------------------------------------------------------------------------


class UpsertChunk(BaseModel):
    """Один чанк для записи в LanceDB."""

    document_id: str
    chunk_index: int
    text: str
    vector: list[float]
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpsertRequest(BaseModel):
    vault_id: str
    chunks: list[UpsertChunk]


class UpsertResponse(BaseModel):
    status: Literal["ok", "partial"]
    upserted_count: int = 0
    failed_indices: list[int] = Field(default_factory=list)
    error_details: list[str] = Field(default_factory=str)


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float


class Source(BaseModel):
    """Source reference for chat UI: a chunk or full document that contributed to the answer.

    `source_kind` distinguishes a single retrieved chunk from a full document that was
    sent to the LLM via `send_full_document` mode.
    """

    path: str
    page: int | None = None
    vault_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    source_kind: Literal["chunk", "full_document"] = "chunk"


class SourceGroup(BaseModel):
    """Grouped sources for one pipeline step."""

    step_id: str
    step_name: str
    sources: list[Source] = Field(default_factory=list)


class MessageSource(BaseModel):
    """Lightweight DTO persisted on `Message.sources` and returned in chat history.

    Mirrors `Source` without optional heavy fields. Used so we can restore the sources
    block on chat reload without storing full text of every chunk.
    """

    path: str
    page: int | None = None
    vault_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    source_kind: Literal["chunk", "full_document"] = "chunk"


class SearchRequest(BaseModel):
    vault_id: str
    vector: list[float]
    top_k: int = Field(default=10, ge=1, le=200)
    score_threshold: float | None = None
    filter: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Indexer task API contracts (rag-indexer/app/main.py)
# ---------------------------------------------------------------------------


class StartIndexTaskRequest(BaseModel):
    vault_id: str
    force_reindex: bool = False
    # Phase 4: targeted reindex — only process these relative markdown paths.
    # None means full-vault scan (existing behaviour, backward compatible).
    source_paths: list[str] | None = None


class StartIndexTaskResponse(BaseModel):
    task_id: str
    vault_id: str
    status: str


class TaskStateResponse(BaseModel):
    task_id: str
    vault_id: str
    status: str
    state: IndexState | None = None


# ---------------------------------------------------------------------------
# WebSocket progress messages (rag-indexer → frontend)
# ---------------------------------------------------------------------------


class WSFileChunkProgressMessage(BaseModel):
    """Прогресс обработки файла: стадия + счётчики чанков."""

    type: Literal["file_chunk_progress"] = "file_chunk_progress"
    task_id: str
    file_path: str
    stage: Literal[
        "parsing", "chunking", "indexing", "done", "error", "empty", "cancelled"
    ]
    chunks_total: int = 0
    chunks_processed: int = 0
    error: str | None = None


class WSFileStatusMessage(BaseModel):
    """Финальный статус файла после индексации."""

    type: Literal["file_status"] = "file_status"
    task_id: str
    file_path: str
    status: Literal["done", "error", "empty", "cancelled"]
    chunk_count: int = 0
    error: str | None = None


class WSTaskCancelledMessage(BaseModel):
    """Задача индексации отменена."""

    type: Literal["task_cancelled"] = "task_cancelled"
    task_id: str


class WSTaskCompleteMessage(BaseModel):
    """Задача индексации завершена успешно."""

    type: Literal["task_complete"] = "task_complete"
    task_id: str
    files_total: int = 0
    files_indexed: int = 0


# ---------------------------------------------------------------------------
# Planner contracts
# ---------------------------------------------------------------------------


class PipelineInvocation(BaseModel):
    """Пайплайн, запланированный Planner-ом к выполнению."""

    pipeline_id: str
    domain: str | None = None
    priority: int = 0


class PlannerDecision(BaseModel):
    """Решение Planner.decide(): стратегия ретривала + нужна ли кларификация."""

    retrieval_strategy: str  # "none" | "semantic" | ...
    clarification_needed: bool = False
    pipeline_invocations: list[PipelineInvocation] = Field(default_factory=list)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Campaign Update Mode — Phase 2
# ---------------------------------------------------------------------------


class UpdateModeAction(StrEnum):
    UPDATE = "update"
    CREATE = "create"


class UpdateModeOperation(StrEnum):
    APPEND_AFTER_SECTION = "append_after_section"
    APPEND_TO_FILE = "append_to_file"
    REPLACE_UNIQUE_TEXT = "replace_unique_text"
    CREATE_FILE = "create_file"
    # Phase 5: delete operations
    DELETE_SECTION = "delete_section"
    DELETE_UNIQUE_TEXT = "delete_unique_text"


#: Operations that remove content — content field MUST be empty string for these.
_DELETE_OPERATIONS: frozenset[UpdateModeOperation] = frozenset(
    {
        UpdateModeOperation.DELETE_SECTION,
        UpdateModeOperation.DELETE_UNIQUE_TEXT,
    }
)


class UpdateModeChangeStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLUTION_FAILED = "resolution_failed"


class UpdateModeVaultApplyStatus(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    FAILED = "failed"
    NO_CHANGES = "no_changes"


# --- LLM intent contracts ---


class UpdateModeAnchor(BaseModel):
    kind: Literal["markdown_heading", "exact_text"]
    value: str = Field(min_length=1, max_length=16_384)


class UpdateModeIntent(BaseModel):
    change_id: str
    action: UpdateModeAction
    description: str = Field(min_length=1, max_length=2_000)

    document_id: str | None = None
    parent_document_id: str | None = None

    operation: UpdateModeOperation
    anchor: UpdateModeAnchor | None = None

    suggested_filename: str | None = None
    # For delete operations content must be empty string "".
    # For all other operations content must be non-empty (min_length=1 enforced below).
    content: str = Field(max_length=65_536)

    @model_validator(mode="after")
    def _validate_intent_invariants(self) -> UpdateModeIntent:
        is_delete = self.operation in _DELETE_OPERATIONS

        # --- content rules ---
        if is_delete:
            if self.content != "":
                raise ValueError(
                    f"{self.operation.value} operation requires content == empty string"
                )
        else:
            if not self.content:
                raise ValueError(
                    f"{self.operation.value} operation requires non-empty content"
                )

        # --- update action rules ---
        if self.action == UpdateModeAction.UPDATE:
            if self.document_id is None:
                raise ValueError("update action requires document_id")
            if self.parent_document_id is not None:
                raise ValueError("update action must not have parent_document_id")
            if self.suggested_filename is not None:
                raise ValueError("update action must not have suggested_filename")
            valid_ops = {
                UpdateModeOperation.APPEND_AFTER_SECTION,
                UpdateModeOperation.APPEND_TO_FILE,
                UpdateModeOperation.REPLACE_UNIQUE_TEXT,
                UpdateModeOperation.DELETE_SECTION,
                UpdateModeOperation.DELETE_UNIQUE_TEXT,
            }
            if self.operation not in valid_ops:
                raise ValueError(
                    f"update action requires operation in {[o.value for o in valid_ops]}"
                )
            if (
                self.operation == UpdateModeOperation.APPEND_AFTER_SECTION
                and (self.anchor is None or self.anchor.kind != "markdown_heading")
            ):
                raise ValueError(
                    "append_after_section requires anchor.kind == markdown_heading"
                )
            if (
                self.operation == UpdateModeOperation.REPLACE_UNIQUE_TEXT
                and (self.anchor is None or self.anchor.kind != "exact_text")
            ):
                raise ValueError(
                    "replace_unique_text requires anchor.kind == exact_text"
                )
            if self.operation == UpdateModeOperation.APPEND_TO_FILE and self.anchor is not None:
                raise ValueError("append_to_file must not have anchor")
            if (
                self.operation == UpdateModeOperation.DELETE_SECTION
                and (self.anchor is None or self.anchor.kind != "markdown_heading")
            ):
                raise ValueError(
                    "delete_section requires anchor.kind == markdown_heading"
                )
            if (
                self.operation == UpdateModeOperation.DELETE_UNIQUE_TEXT
                and (self.anchor is None or self.anchor.kind != "exact_text")
            ):
                raise ValueError(
                    "delete_unique_text requires anchor.kind == exact_text"
                )

        # --- create action rules ---
        if self.action == UpdateModeAction.CREATE:
            if self.document_id is not None:
                raise ValueError("create action must not have document_id")
            if self.operation != UpdateModeOperation.CREATE_FILE:
                raise ValueError("create action requires operation == create_file")
            if self.anchor is not None:
                raise ValueError("create action must not have anchor")
            if self.suggested_filename is None:
                raise ValueError("create action requires suggested_filename")

        if self.document_id is not None and self.parent_document_id is not None:
            raise ValueError(
                "document_id and parent_document_id are mutually exclusive"
            )

        return self


class UpdateModeIntentBatch(BaseModel):
    intents: list[UpdateModeIntent] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _validate_unique_change_ids(self) -> UpdateModeIntentBatch:
        ids = [i.change_id for i in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("change_id must be unique within batch")
        return self


# --- Phase 3: executor-level DTOs ---


class IndexedContextDocument(BaseModel):
    """In-memory DTO для документа, включённого в LLM-контекст.

    Используется только внутри UpdateModeExecutor — не персистируется.
    """

    document_id: str
    vault_id: str
    source_path: str
    title: str | None
    text: str
    estimated_tokens: int


class UpdateModeGenerationResult(BaseModel):
    """Outer wrapper результата генерации LLM.

    Отличается от UpdateModeIntentBatch тем, что допускает пустой список intents
    (когда note не содержит actionable изменений). В этом случае обязателен
    no_change_reason.

    Инварианты:
    - empty intents → non-empty no_change_reason
    - non-empty intents → no_change_reason must be None

    Stage 5: дополнительно содержит state_patch (точечные операции Campaign State)
    и state_patch_questions. state_patch может быть пустым даже при наличии intents
    (Campaign Update Mode §9 — patch может быть пустым).
    """

    intents: list[UpdateModeIntent] = Field(default_factory=list, max_length=10)
    no_change_reason: str | None = Field(default=None, max_length=1_000)
    state_patch: list[CampaignStatePatchOperation] = Field(default_factory=list)
    state_patch_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_no_change_invariant(self) -> UpdateModeGenerationResult:
        if not self.intents and not self.no_change_reason:
            raise ValueError("no_change_reason is required when intents list is empty")
        if self.intents and self.no_change_reason is not None:
            raise ValueError("no_change_reason must be None when intents are present")
        return self


# --- Internal indexer API contracts ---


class UpdateModeResolveRequest(BaseModel):
    chat_id: str
    campaign_id: str
    domain_id: str
    vault_ids: list[str] = Field(min_length=1)
    intents: list[UpdateModeIntent] = Field(min_length=1, max_length=10)
    default_vault_id: str
    candidate_document_ids: list[str] = Field(
        default_factory=list, min_length=0, max_length=15
    )

    @model_validator(mode="after")
    def _validate_default_vault(self) -> UpdateModeResolveRequest:
        if self.default_vault_id not in self.vault_ids:
            raise ValueError("default_vault_id must be in vault_ids")
        return self


class ResolvedUpdateModeChange(BaseModel):
    change_id: str
    vault_id: str | None = None
    document_id: str | None = None
    file_path: str | None = None

    action: UpdateModeAction
    description: str

    # --- Operation metadata — persisted in session for multi-op batch builder ---
    # These fields allow rag-backend to reconstruct the ordered file_batches from
    # the session without re-resolving. Added in fix/update-mode-multi-patch-per-file.
    operation: UpdateModeOperation | None = None
    anchor: UpdateModeAnchor | None = None
    # Raw intent content (the text to insert/replace). For delete ops this is "".
    # NOT the same as proposed_content (which is the full proposed file after the op).
    op_content: str = ""
    # Stable index preserving the order in which intents were resolved (0-based).
    # Used by the batch builder to sort ops targeting the same file.
    # Default -1 signals a legacy session where the field was not persisted.
    resolve_order: int = -1

    original_content: str = ""
    proposed_content: str = ""
    unified_diff: str = ""
    expected_sha256: str | None = None

    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None


class UpdateModeResolveResponse(BaseModel):
    changes: list[ResolvedUpdateModeChange]


class UpdateModeApplyChange(BaseModel):
    """Single-change apply unit — deprecated in favour of UpdateModeFileChangeBatch.

    Kept for backward compatibility. rag-backend still produces these when
    talking to an old indexer; UpdateModeApplyRequest.model_validator converts
    them to file_batches automatically.
    """

    change_id: str
    vault_id: str
    file_path: str
    action: UpdateModeAction
    proposed_content: str
    expected_sha256: str | None = None
    # Fields added for multi-op backward-compat conversion.
    # Old clients that only set proposed_content will get the legacy single-op
    # path; new clients set operation + anchor + op_content.
    operation: UpdateModeOperation | None = None
    anchor: UpdateModeAnchor | None = None
    op_content: str = ""
    description: str = ""
    # Stable index for multi-op batch ordering. -1 = legacy sentinel.
    resolve_order: int = -1

    @model_validator(mode="after")
    def _validate_sha_policy(self) -> UpdateModeApplyChange:
        if self.action == UpdateModeAction.UPDATE and self.expected_sha256 is None:
            raise ValueError("update action requires expected_sha256")
        if self.action == UpdateModeAction.CREATE and self.expected_sha256 is not None:
            raise ValueError("create action must not have expected_sha256")
        return self


# ---------------------------------------------------------------------------
# Multi-op apply contracts (fix/update-mode-multi-patch-per-file)
# ---------------------------------------------------------------------------


class UpdateModeFileOp(BaseModel):
    """A single ordered operation within an UpdateModeFileChangeBatch.

    One UpdateModeFileChangeBatch may contain 1..20 ops targeting the same
    (vault_id, file_path). The applier reads the file once, applies all ops
    sequentially in-memory, then writes the final result atomically.
    """

    change_id: str
    operation: UpdateModeOperation
    anchor_value: str | None = None  # anchor.value from intent; None for APPEND_TO_FILE
    content: str  # intent content ('' for delete ops)
    # SHA-256 of the original file content at resolve time.
    # Required for ops[0] of UPDATE batches (CAS check before first write).
    # None for all subsequent ops and for CREATE batches.
    expected_sha256: str | None = None
    description: str = ""  # human-readable description for git commit message


class UpdateModeFileChangeBatch(BaseModel):
    """All operations targeting one (vault_id, file_path) pair, in apply order."""

    vault_id: str
    file_path: str
    action: UpdateModeAction  # UPDATE or CREATE
    ops: list[UpdateModeFileOp] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _validate_sha_policy(self) -> UpdateModeFileChangeBatch:
        """Enforce CAS / SHA-256 policy for ops list.

        Rules:
        - UPDATE batches: ops[0].expected_sha256 is required (CAS check);
          ops[1..] must have expected_sha256 == None.
        - CREATE batches: all ops must have expected_sha256 == None.
        """
        for i, op in enumerate(self.ops):
            if self.action == UpdateModeAction.CREATE:
                if op.expected_sha256 is not None:
                    raise ValueError(
                        f"CREATE batch: ops[{i}].expected_sha256 must be None"
                    )
            elif self.action == UpdateModeAction.UPDATE:
                if i == 0 and op.expected_sha256 is None:
                    raise ValueError(
                        "UPDATE batch: ops[0].expected_sha256 is required for CAS check"
                    )
                if i > 0 and op.expected_sha256 is not None:
                    raise ValueError(
                        f"UPDATE batch: ops[{i}].expected_sha256 must be None "
                        "(CAS check is only performed on ops[0])"
                    )
        return self


class UpdateModeApplyRequest(BaseModel):
    apply_id: str
    chat_id: str
    campaign_id: str

    # Primary field — new clients send this.
    file_batches: list[UpdateModeFileChangeBatch] = Field(default_factory=list)

    # Deprecated: accepted for backward compatibility.
    # Converted to file_batches by _normalize_and_validate below.
    accepted_changes: list[UpdateModeApplyChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> UpdateModeApplyRequest:
        # --- Uniqueness of change_id across all accepted_changes ---
        if self.accepted_changes:
            change_ids = [ch.change_id for ch in self.accepted_changes]
            duplicates = {cid for cid in change_ids if change_ids.count(cid) > 1}
            if duplicates:
                raise ValueError(
                    f"change_id must be unique within accepted_changes; duplicates: {sorted(duplicates)}"
                )
            # --- Uniqueness of (vault_id, file_path) across accepted_changes ---
            pairs = [(ch.vault_id, ch.file_path) for ch in self.accepted_changes]
            pair_dups = {p for p in pairs if pairs.count(p) > 1}
            if pair_dups:
                raise ValueError(
                    f"(vault_id, file_path) pairs must be unique in accepted_changes; "
                    f"duplicates: {sorted(pair_dups)}"
                )

        # --- Backward-compat conversion ---
        if self.accepted_changes and not self.file_batches:
            from collections import defaultdict

            groups: dict[tuple[str, str], list[UpdateModeApplyChange]] = defaultdict(
                list
            )
            for ch in self.accepted_changes:
                groups[(ch.vault_id, ch.file_path)].append(ch)
            batches: list[UpdateModeFileChangeBatch] = []
            for (vault_id, file_path), changes in groups.items():
                # Sort by resolve_order so ops are applied in correct sequence.
                # resolve_order=-1 (legacy sentinel) sorts before 0, which is
                # acceptable for single-change-per-file legacy sessions.
                changes.sort(key=lambda c: max(c.resolve_order, 0))
                if changes[0].operation is not None:
                    # New-style UpdateModeApplyChange: has operation + anchor + op_content
                    ops = [
                        UpdateModeFileOp(
                            change_id=ch.change_id,
                            operation=ch.operation,  # type: ignore[arg-type]
                            anchor_value=ch.anchor.value if ch.anchor else None,
                            content=ch.op_content,
                            expected_sha256=ch.expected_sha256 if i == 0 else None,
                        )
                        for i, ch in enumerate(changes)
                    ]
                else:
                    # Legacy-style: only proposed_content is available.
                    # proposed_content is the FULL file state after the op, not a delta.
                    # We cannot meaningfully apply multiple legacy changes to the same
                    # file — use only the last one (last-write-wins fallback).
                    if len(changes) > 1:
                        _log.warning(
                            "update-mode legacy backward-compat: %d changes share "
                            "file_path=%r but none has operation field — "
                            "using only the last change (%s) as a single "
                            "APPEND_TO_FILE op. Other changes are dropped.",
                            len(changes),
                            file_path,
                            changes[-1].change_id,
                        )
                    last = changes[-1]
                    ops = [
                        UpdateModeFileOp(
                            change_id=last.change_id,
                            operation=UpdateModeOperation.APPEND_TO_FILE,
                            anchor_value=None,
                            content=last.proposed_content,
                            expected_sha256=changes[0].expected_sha256,
                        )
                    ]
                batches.append(
                    UpdateModeFileChangeBatch(
                        vault_id=vault_id,
                        file_path=file_path,
                        action=changes[0].action,
                        ops=ops,
                    )
                )
            self.file_batches = batches

        # --- Require at least one batch ---
        if not self.file_batches:
            raise ValueError("file_batches or accepted_changes must be non-empty")

        # --- Uniqueness of (vault_id, file_path) ---
        pairs = [(b.vault_id, b.file_path) for b in self.file_batches]
        if len(pairs) != len(set(pairs)):
            raise ValueError(
                "(vault_id, file_path) pairs must be unique in file_batches"
            )

        # --- Uniqueness of change_id across file_batches.ops ---
        op_ids = [op.change_id for b in self.file_batches for op in b.ops]
        op_dups = {cid for cid in op_ids if op_ids.count(cid) > 1}
        if op_dups:
            raise ValueError(
                f"change_id must be unique across file_batches; duplicates: {sorted(op_dups)}"
            )

        return self


class UpdateModeVaultApplyResult(BaseModel):
    vault_id: str
    status: UpdateModeVaultApplyStatus
    applied_count: int = Field(ge=0)

    snapshot_commit_sha: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None

    reindex_task_id: str | None = None
    reindex_error: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    manual_recovery_required: bool = False


class UpdateModeApplyResponse(BaseModel):
    apply_id: str
    results: list[UpdateModeVaultApplyResult] = Field(min_length=1)


# --- Phase 4: Indexer apply idempotency state ---


class IndexerApplyState(BaseModel):
    """Redis-persisted idempotency record for a single apply_id on the indexer.

    Key: update_mode:apply:{apply_id}
    TTL: SESSION_TTL_SECONDS (3 hours)
    """

    apply_id: str
    request_fingerprint: str  # SHA-256 of canonical JSON payload
    status: Literal["in_progress", "completed"]
    response: UpdateModeApplyResponse | None = None
    created_at: datetime


# --- Public backend API contracts ---


class StartUpdateModeRequest(BaseModel):
    note: str = Field(min_length=1, max_length=20_000)


class StartUpdateModeResponse(BaseModel):
    chat_id: str
    expires_at: datetime
    changes: list[ResolvedUpdateModeChange]
    warnings: list[str] = Field(default_factory=list)
    state_field_snapshot: list[CampaignStateFieldSnapshot] = Field(default_factory=list)
    state_patch_operations: list[UpdateModeStatePatchEntry] = Field(
        default_factory=list
    )


class UpdateModeSessionResponse(BaseModel):
    chat_id: str
    campaign_id: str
    domain_id: str
    vault_ids: list[str]
    expires_at: datetime
    changes: list[ResolvedUpdateModeChange]
    warnings: list[str] = Field(default_factory=list)
    state_field_snapshot: list[CampaignStateFieldSnapshot] = Field(default_factory=list)
    state_patch_operations: list[UpdateModeStatePatchEntry] = Field(
        default_factory=list
    )


class UpdateModeReviewRequest(BaseModel):
    accepted_change_ids: list[str] = Field(default_factory=list, max_length=10)
    rejected_change_ids: list[str] = Field(default_factory=list, max_length=10)

    # Stage 5: optional state-patch decisions. None для back-compat со старыми клиентами.
    state_patch_decisions: UpdateModeStatePatchDecisions | None = None

    # Sprint 3: optional schema-change decisions. None если в proposal-е
    # нет field_change_operations или клиент ещё на старой версии API.
    field_change_decisions: UpdateModeStateFieldChangeDecisions | None = None

    @model_validator(mode="after")
    def _validate_no_overlap(self) -> UpdateModeReviewRequest:
        accepted = set(self.accepted_change_ids)
        rejected = set(self.rejected_change_ids)
        overlap = accepted & rejected
        if overlap:
            raise ValueError(
                f"change_ids cannot be both accepted and rejected: {overlap}"
            )
        if (
            not accepted
            and not rejected
            and self.state_patch_decisions is None
            and self.field_change_decisions is None
        ):
            raise ValueError(
                "review request must contain at least one accepted or rejected change_id, "
                "a non-empty state_patch_decisions, or field_change_decisions"
            )
        return self


class ApplyUpdateModeRequest(BaseModel):
    apply_id: str | None = None


class ApplyUpdateModeResponse(BaseModel):
    apply_id: str
    results: list[UpdateModeVaultApplyResult]
    # Stage 5: state patch apply result. None если нет state field snapshot
    # или все state-patch ops отклонены.
    state_patch_result: UpdateModeStatePatchApplyResult | None = None
    # Sprint 3: schema-change apply result. None если нет schema операций
    # или все field_change ops отклонены.
    field_changes_result: UpdateModeStateFieldChangeApplyResult | None = None


class CancelUpdateModeResponse(BaseModel):
    status: Literal["cancelled"]


# ---------------------------------------------------------------------------
# Campaign Update Mode — Stage 5: state_patch in proposal
# ---------------------------------------------------------------------------


class CampaignStateFieldSnapshot(BaseModel):
    """Снимок метаданных enabled-поля Campaign State на момент start Update Mode.

    Хранится в Redis-сессии Update Mode, чтобы:
      - UI мог показывать человеко-читаемые названия (label) без повторного lookup;
      - сервер мог валидировать edited-текст без обращения к БД.
    """

    field_id: str
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8 * 1024)
    mode: CampaignStateFieldMode
    display_order: int = Field(ge=0)


class UpdateModeStatePatchEntry(BaseModel):
    """Одна Campaign State patch-операция в proposal Update Mode.

    op_index — стабильный индекс внутри сессии (0..N-1). Используется в
    PATCH /review и POST /apply для ссылки на конкретную операцию.
    """

    op_index: int = Field(ge=0)
    field_key: str = Field(min_length=1, max_length=64)
    field_label: str = Field(min_length=1, max_length=256)
    mode: CampaignStateFieldMode
    operation: CampaignStatePatchOperation
    previous_text: str | None = None
    proposed_text: str | None = None
    edited_text: str | None = None
    status: Literal["pending", "accepted", "rejected"] = "pending"


class UpdateModeStatePatchEdit(BaseModel):
    """Inline-правка текста state-patch операции на review-этапе.

    Допустимо только для операций с text-полем (replace_single, update_list_item,
    add_list_item). Для остальных типов backend игнорирует edit (warning в логах).
    """

    op_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=8192)


class UpdateModeStatePatchDecisions(BaseModel):
    """Решения пользователя по state-patch операциям в PATCH /review.

    Семантика:
      - accepted_op_indexes + rejected_op_indexes: пользовательский выбор;
      - edited: inline-правки текста (применяются поверх operation.text).
    """

    accepted_op_indexes: list[int] = Field(default_factory=list)
    rejected_op_indexes: list[int] = Field(default_factory=list)
    edited: list[UpdateModeStatePatchEdit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_no_overlap(self) -> UpdateModeStatePatchDecisions:
        accepted = set(self.accepted_op_indexes)
        rejected = set(self.rejected_op_indexes)
        overlap = accepted & rejected
        if overlap:
            raise ValueError(
                f"state_patch op_indexes cannot be both accepted and rejected: {sorted(overlap)}"
            )
        edited_indexes = {e.op_index for e in self.edited}
        if edited_indexes & rejected:
            raise ValueError(
                f"edited state_patch op_indexes cannot be rejected: {sorted(edited_indexes & rejected)}"
            )
        return self


class UpdateModeStatePatchApplyResult(BaseModel):
    """Результат применения state-patch внутри POST /apply.

    Отсутствует (None), если state_field_snapshot пустой или все state-ops
    были rejected. Не валится apply file changes, даже если state patch
    заканчивается failed_operations.
    """

    applied_state_version: int = 0
    config_version: int = 0
    applied_op_indexes: list[int] = Field(default_factory=list)
    failed_op_indexes: list[int] = Field(default_factory=list)
    failed_reasons: dict[str, str] = Field(default_factory=dict)


# --- Redis session contract ---


class UpdateModeSession(BaseModel):
    session_id: str
    chat_id: str
    campaign_id: str
    domain_id: str

    vault_ids: list[str]
    default_vault_id: str
    candidate_document_ids: list[str]

    note: str
    warnings: list[str] = Field(default_factory=list)
    changes: list[ResolvedUpdateModeChange]

    created_at: datetime
    expires_at: datetime

    apply_id: str | None = None
    apply_started_at: datetime | None = None
    # Phase 4: apply lifecycle state
    apply_state: Literal["review", "in_progress", "completed"] = "review"
    # Stage 5: state-patch snapshot and operations (Campaign Update Mode §9, §6.2).
    state_field_snapshot: list[CampaignStateFieldSnapshot] = Field(default_factory=list)
    state_patch_operations: list[UpdateModeStatePatchEntry] = Field(
        default_factory=list
    )
    # Sprint 3: schema-level changes (create_field / update_field). Same
    # review + apply flow as state-patch but operates on the field config
    # (CampaignStateFieldConfig), not on field values.
    state_field_change_operations: list[UpdateModeStateFieldChangeEntry] = Field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# Sprint 3 — Model-proposed context updates
# ---------------------------------------------------------------------------


class ContextFieldChangeOperation(StrEnum):
    """Тип schema-операции, которую модель предлагает в proposal-е."""

    CREATE_FIELD = "create_field"
    UPDATE_FIELD = "update_field"
    # delete_field is intentionally absent in Sprint 3 (per spec).
    # The user can delete fields manually via the existing settings UI.


class ContextFieldChange(BaseModel):
    """Одна schema-операция Campaign State, сгенерированная моделью.

    Идемпотентно сериализуется в JSON для `propose_context_update` tool.
    `display_order` опционален (default = 1000, чтобы новые поля
    появлялись в конце).
    """

    operation: ContextFieldChangeOperation
    key: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description=(
            "Stable technical identifier. Lowercase + digits + underscore, "
            "starts with a letter. Immutable after creation."
        ),
    )
    label: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=8 * 1024)
    mode: CampaignStateFieldMode
    enabled: bool = True
    display_order: int = Field(default=1000, ge=0)


class ContextUpdateProposal(BaseModel):
    """Предложение модели на атомарное обновление контекста кампании.

    Состоит из трёх независимых секций:
    - field_changes: schema-операции (create_field / update_field)
    - state_patch: операции над значениями (replace_single, add_list_item, …)
    - file_changes: операции над .md файлами в vault (EditIntent)

    Все три секции — часть ОДНОГО proposal-а. Apply идёт в строгом порядке:
    schema → state_patch → file_changes, и любая ошибка в schema отменяет всё.

    `source_message_ids` — список ID сообщений пользователя, на основе
    которых модель сформировала proposal. Используется для audit trail.
    """

    field_changes: list[ContextFieldChange] = Field(default_factory=list)
    state_patch: list[CampaignStatePatchOperation] = Field(default_factory=list)
    file_changes: list[UpdateModeIntent] = Field(default_factory=list)

    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    reason: str = Field(default="", max_length=1024)
    source_message_ids: list[str] = Field(default_factory=list)
    review_summary: str = Field(default="", max_length=1024)

    @model_validator(mode="after")
    def _validate_non_empty_section_alignment(self) -> ContextUpdateProposal:
        """Cross-section sanity: если есть state_patch с field_key, на который
        ссылается field_changes с create_field — это OK, иначе валидация
        на стороне apply. Здесь только лёгкие sanity-проверки."""
        # Проверяем что key в create_field не конфликтует сам с собой
        # (несколько create_field с одним key).
        seen_create_keys: set[str] = set()
        for fc in self.field_changes:
            if fc.operation == ContextFieldChangeOperation.CREATE_FIELD:
                if fc.key in seen_create_keys:
                    raise ValueError(
                        f"duplicate create_field for key={fc.key!r}"
                    )
                seen_create_keys.add(fc.key)
        return self


class UpdateModeStateFieldChangeEntry(BaseModel):
    """Снимок schema-операции в proposal-е Update Mode.

    Аналог UpdateModeStatePatchEntry, но для операций над конфигурацией
    полей (create_field / update_field), а не над значениями.
    """

    op_index: int = Field(ge=0)
    operation: ContextFieldChangeOperation
    # For create_field: описание нового поля. For update_field: текущее
    # значение label/description/enabled/display_order + новые.
    key: str = Field(min_length=1, max_length=64)
    proposed_label: str | None = None
    proposed_description: str | None = None
    proposed_mode: CampaignStateFieldMode | None = None
    proposed_enabled: bool | None = None
    proposed_display_order: int | None = None
    previous_label: str | None = None
    previous_description: str | None = None
    previous_enabled: bool | None = None
    previous_display_order: int | None = None
    edited_label: str | None = None
    edited_description: str | None = None
    edited_display_order: int | None = None
    status: Literal["pending", "accepted", "rejected"] = "pending"


class UpdateModeStateFieldChangeDecisions(BaseModel):
    """Решения пользователя по schema-операциям в PATCH /review.

    Аналог UpdateModeStatePatchDecisions, но без text-edits (для schema
    изменения label/description не нужен inline-edit, достаточно решения
    accept/reject).
    """

    accepted_op_indexes: list[int] = Field(default_factory=list)
    rejected_op_indexes: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_no_overlap(self) -> UpdateModeStateFieldChangeDecisions:
        accepted = set(self.accepted_op_indexes)
        rejected = set(self.rejected_op_indexes)
        overlap = accepted & rejected
        if overlap:
            raise ValueError(
                f"field_change op_indexes cannot be both accepted and rejected: {sorted(overlap)}"
            )
        return self


class UpdateModeStateFieldChangeApplyResult(BaseModel):
    """Результат применения schema-операций внутри POST /apply.

    Аналог UpdateModeStatePatchApplyResult для schema. Если любая
    операция провалилась, флаг `had_failures=True` и весь apply
    откатывается (config_version возвращается к pre-apply значению).
    """

    applied_op_indexes: list[int] = Field(default_factory=list)
    failed_op_indexes: list[int] = Field(default_factory=list)
    failed_reasons: dict[str, str] = Field(default_factory=dict)
    new_config_version: int = 0


# Resolve forward references for the model_validate() machinery.
ContextUpdateProposal.model_rebuild()
UpdateModeSession.model_rebuild()
