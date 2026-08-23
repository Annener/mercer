"""campaign_state_initial_service.py — оркестратор Initial Campaign State (Stage 3).

Пайплайн preview:
  1. Валидация document_ids (только .md, indexed, estimated_tokens ≤ 32k).
  2. Параллельный fetch полных текстов через reconstruct_full_text.
  3. Построение source_snapshot (document_id + md5 + meta).
  4. System prompt из конфигурации полей кампании (key/label/description/mode/order).
  5. User message с <document id=... sha=...>...</document> секциями.
  6. _call_provider_with_repair (1 attempt + 1 repair) → CampaignStateInitialProposal.
  7. Нормализация source_refs (только doc_id из snapshot).
  8. Сохранение в Redis (TTL 3h).
  9. Возврат CampaignStateInitialProposalRead.

Пайплайн apply:
  1. Загрузить proposal из Redis.
  2. Проверить expires_at, config_version.
  3. Делегировать в CampaignStateValueService.apply_initial (там же snapshot freshness).
  4. Удалить Redis-ключ.
  5. Вернуть CampaignStateVersionRead.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, CampaignStateFieldConfig, Document
from app.services.campaign_state_initial_store import (
    campaign_state_initial_store,
)
from app.services.campaign_state_value_service import (
    CampaignStateValueError,
    campaign_state_value_service,
)
from app.services.full_document_service import (
    FULL_DOC_TOKEN_LIMIT,
    reconstruct_full_text,
)
from app.services.settings_service import settings_service
from shared_contracts.models import (
    CampaignStateInitialApplyRequest,
    CampaignStateInitialProposal,
    CampaignStateInitialProposalRead,
    DocumentSnapshot,
)

logger = logging.getLogger(__name__)

# Консистентно с Update Mode (update_mode_executor._TOTAL_TOKEN_BUDGET = 64_000).
_TOTAL_TOKEN_BUDGET = 64_000
_PER_DOC_TOKEN_LIMIT = FULL_DOC_TOKEN_LIMIT  # 32_000

_DB_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class CampaignStateInitialError(Exception):
    """Base for all Initial State service errors."""

    code: str = "campaign_state_initial_error"
    http_status: int = 400

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


class CampaignNotFoundError(CampaignStateInitialError):
    code, http_status = "campaign_not_found", 404


class GenerationProviderUnavailableError(CampaignStateInitialError):
    code, http_status = "generation_provider_unavailable", 503


class InvalidGenerationOutputError(CampaignStateInitialError):
    code, http_status = "invalid_generation_output", 503


class NoMarkdownDocumentsError(CampaignStateInitialError):
    code, http_status = "no_markdown_documents", 422


class DocumentNotMarkdownError(CampaignStateInitialError):
    code, http_status = "document_not_markdown", 422


class DocumentNotFoundError(CampaignStateInitialError):
    code, http_status = "document_not_found", 404


class DocumentNotIndexedError(CampaignStateInitialError):
    code, http_status = "document_not_indexed", 422


class ProposalNotFoundError(CampaignStateInitialError):
    code, http_status = "proposal_not_found", 404


class ProposalExpiredError(CampaignStateInitialError):
    code, http_status = "proposal_expired", 410


# ---------------------------------------------------------------------------
# Constants for LLM prompt and source_ref validation
# ---------------------------------------------------------------------------

# source_ref для initial принимает только формат file:<doc_id>:sha:<md5_hex_32>
import re

_INITIAL_SOURCE_REF_RE = re.compile(
    r"^file:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}:sha:[0-9a-fA-F]{32}$"
)

_MAX_SOURCE_REFS_PER_VALUE = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http_from_error(exc: CampaignStateInitialError) -> Any:
    """Маппинг сервисных исключений в HTTPException (для роутера)."""
    from fastapi import HTTPException

    return HTTPException(status_code=exc.http_status, detail=exc.code)


def _validate_documents_md(
    docs: list[Document],
) -> None:
    """Проверка, что все документы — .md (raises DocumentNotMarkdownError)."""
    bad: list[str] = []
    for d in docs:
        if not d.source_path.lower().endswith(".md"):
            bad.append(f"{d.id}:{d.source_path}")
    if bad:
        raise DocumentNotMarkdownError(f"non-markdown documents: {bad}")


def _validate_documents_indexed(
    docs: list[Document],
) -> None:
    """Проверка, что все документы в status='indexed' (raises DocumentNotIndexedError)."""
    bad: list[str] = []
    for d in docs:
        if d.status != "indexed":
            bad.append(f"{d.id}:status={d.status}")
    if bad:
        raise DocumentNotIndexedError(f"unindexed documents: {bad}")


def _filter_by_per_doc_limit(
    docs: list[Document],
    warnings: list[str],
) -> list[Document]:
    """Отфильтровать документы, превышающие _PER_DOC_TOKEN_LIMIT.

    Если у документа estimated_tokens отсутствует или None — оставляем,
    warning в список.
    """
    out: list[Document] = []
    for d in docs:
        if d.estimated_tokens is None:
            warnings.append(f"missing_size_metadata:{d.id}")
            continue
        if d.estimated_tokens > _PER_DOC_TOKEN_LIMIT:
            warnings.append(f"document_too_large_for_initial:{d.id}")
            continue
        out.append(d)
    return out


def _apply_total_budget(
    docs: list[Document],
    warnings: list[str],
) -> list[Document]:
    """Применить total budget 64_000 в порядке входных document_ids.

    Документы, не помещающиеся в бюджет — пропускаются (с warning).
    """
    out: list[Document] = []
    total = 0
    for d in docs:
        assert d.estimated_tokens is not None
        if total + d.estimated_tokens > _TOTAL_TOKEN_BUDGET:
            warnings.append(f"total_budget_exceeded:{d.id}")
            continue
        out.append(d)
        total += d.estimated_tokens
    return out


def _build_system_prompt(fields: list[CampaignStateFieldConfig]) -> str:
    """Системный промпт для LLM, описывающий конфигурацию полей кампании."""
    lines: list[str] = [
        "You are a campaign-state initializer.",
        "",
        "You receive:",
        "- a user-described campaign context (no notes; this is an INITIAL state);",
        "- one or more full-text indexed Markdown documents belonging to the campaign.",
        "",
        "Your task: propose initial values for each configured field of the Campaign State.",
        "Do not invent facts that are not present in the supplied documents.",
        "If information for a field is missing or contradictory, mark the field accordingly.",
        "",
        "FIELD CONFIGURATION (ordered, respect display order):",
        "",
    ]
    for f in fields:
        if not f.enabled:
            continue
        desc = (f.description or "").strip()
        desc_line = f"  Description: {desc}" if desc else "  Description: (none)"
        lines.append(
            f"- key={f.key!r}, label={f.label!r}, mode={f.mode}\n"
            f"{desc_line}"
        )
    lines.extend(
        [
            "",
            "RULES:",
            "- For each enabled field above, return exactly one entry in `fields`.",
            "- mode=single: status='proposed' → set `single_value.text` (1..8192 chars);",
            "  status='empty' → no reliable data;",
            "  status='needs_clarification' → set `status.clarification_question`.",
            "- mode=list: status='proposed' → set `list_value.items` array of {text, source_refs};",
            "  status='empty' → leave `list_value.items` empty or omit;",
            "  status='needs_clarification' → set `status.clarification_question`.",
            "- source_refs MUST be of the form `file:<document_id>:sha:<md5>` where",
            "  document_id and md5 are taken EXACTLY from the document header below.",
            "  Use 1..3 refs per value, prefer the most relevant document.",
            "- Do not return fields for disabled or unknown keys.",
            "- If the documents contradict each other, mark the field as 'needs_clarification'",
            "  and provide a precise clarification_question.",
            "- Use the language of the documents for all user-facing strings.",
            "",
            "OUTPUT SCHEMA (return JSON only, no prose, no markdown fences):",
            "{",
            '  "fields": [',
            "    {",
            '      "field_key": "...",',
            '      "mode": "single" | "list",',
            '      "status": {',
            '        "status": "proposed" | "empty" | "needs_clarification",',
            '        "clarification_question": "... (required only if needs_clarification)"',
            "      },",
            '      "single_value": { "text": "...", "source_refs": ["file:..:sha:.."] },  // mode=single + status=proposed',
            '      "list_value":   { "items": [ { "text": "...", "source_refs": ["..."] } ] }  // mode=list + status=proposed',
            "    }",
            "  ],",
            '  "questions": ["...optional general questions..."]',
            "}",
        ]
    )
    return "\n".join(lines)


def _build_user_message(
    snapshots: list[DocumentSnapshot],
    docs_text: dict[str, str],
) -> str:
    """User message: <document id=... sha=...>...</document> per doc."""
    parts: list[str] = ["<allowed_documents>"]
    for s in snapshots:
        text = docs_text.get(s.document_id, "")
        title_attr = f' title="{s.title}"' if s.title else ""
        parts.append(
            f'<document id="{s.document_id}" vault_id="{s.vault_id}" '
            f'source_path="{s.source_path}" sha="{s.content_sha}"{title_attr}>\n'
            f'<indexed_content>\n{text}\n</indexed_content>\n'
            f'</document>'
        )
    parts.append("</allowed_documents>")
    return "\n".join(parts)


def _normalize_source_refs(
    refs: list[str],
    snapshot_doc_ids: set[str],
    warnings: list[str],
    field_key: str,
) -> list[str]:
    """Оставить только file:<doc_id>:sha:<md5_32>, где doc_id ∈ snapshot.

    Невалидные / неизвестные refs → отбрасываются с warning.
    """
    normalized: list[str] = []
    for ref in refs:
        if not isinstance(ref, str):
            warnings.append(f"invalid_source_ref:{field_key}:non_string")
            continue
        if not _INITIAL_SOURCE_REF_RE.match(ref):
            warnings.append(f"invalid_source_ref_format:{field_key}:{ref!r}")
            continue
        # ref = "file:<uuid>:sha:<32hex>"
        parts = ref.split(":")
        # parts = ["file", "<uuid>", "sha", "<32hex>"]
        if len(parts) != 4 or parts[0] != "file" or parts[2] != "sha":
            warnings.append(f"invalid_source_ref_format:{field_key}:{ref!r}")
            continue
        doc_id = parts[1]
        if doc_id not in snapshot_doc_ids:
            warnings.append(f"source_ref_unknown_document:{field_key}:{doc_id}")
            continue
        normalized.append(ref)
        if len(normalized) >= _MAX_SOURCE_REFS_PER_VALUE:
            warnings.append(f"source_refs_truncated:{field_key}")
            break
    return normalized


def _normalize_proposal(
    raw: dict[str, Any],
    fields_by_key: dict[str, CampaignStateFieldConfig],
    snapshot_doc_ids: set[str],
    warnings: list[str],
) -> CampaignStateInitialProposal:
    """Привести сырой dict от LLM к Pydantic + отфильтровать неизвестные/disabled поля."""
    raw_fields = raw.get("fields") or []
    kept: list[dict[str, Any]] = []

    for rf in raw_fields:
        if not isinstance(rf, dict):
            warnings.append("invalid_field_entry:non_dict")
            continue
        key = rf.get("field_key")
        if not isinstance(key, str):
            warnings.append(f"invalid_field_entry:missing_key:{rf!r}")
            continue
        field = fields_by_key.get(key)
        if field is None:
            warnings.append(f"unknown_field_key:{key}")
            continue
        if not field.enabled:
            warnings.append(f"disabled_field_skipped:{key}")
            continue
        if rf.get("mode") != field.mode:
            warnings.append(f"mode_mismatch:{key}")
            continue

        status_obj = rf.get("status") or {}
        status_val = status_obj.get("status") if isinstance(status_obj, dict) else None
        if status_val not in ("proposed", "empty", "needs_clarification"):
            warnings.append(f"invalid_status:{key}")
            continue

        entry: dict[str, Any] = {
            "field_key": key,
            "mode": field.mode,
            "status": {
                "status": status_val,
            },
        }
        if status_val == "needs_clarification":
            cq = status_obj.get("clarification_question")
            if not isinstance(cq, str) or not cq.strip():
                warnings.append(f"missing_clarification_question:{key}")
                continue
            entry["status"]["clarification_question"] = cq

        if status_val == "proposed":
            if field.mode == "single":
                sv = rf.get("single_value") or {}
                if not isinstance(sv, dict) or not isinstance(sv.get("text"), str):
                    warnings.append(f"missing_single_value:{key}")
                    continue
                refs = _normalize_source_refs(
                    sv.get("source_refs") or [],
                    snapshot_doc_ids,
                    warnings,
                    key,
                )
                entry["single_value"] = {
                    "text": sv["text"],
                    "source_refs": refs,
                }
            else:
                lv = rf.get("list_value") or {}
                items = lv.get("items") or []
                if not isinstance(items, list):
                    warnings.append(f"invalid_list_items:{key}")
                    continue
                normalized_items: list[dict[str, Any]] = []
                for it in items:
                    if not isinstance(it, dict) or not isinstance(it.get("text"), str):
                        warnings.append(f"invalid_list_item:{key}")
                        continue
                    refs = _normalize_source_refs(
                        it.get("source_refs") or [],
                        snapshot_doc_ids,
                        warnings,
                        key,
                    )
                    normalized_items.append(
                        {"text": it["text"], "source_refs": refs}
                    )
                entry["list_value"] = {"items": normalized_items}

        kept.append(entry)

    questions = raw.get("questions") or []
    if not isinstance(questions, list):
        questions = []
    questions_clean = [q for q in questions if isinstance(q, str)]

    return CampaignStateInitialProposal.model_validate(
        {"fields": kept, "questions": questions_clean}
    )


# ---------------------------------------------------------------------------
# LLM call with single repair attempt
# ---------------------------------------------------------------------------


async def _call_provider_with_repair(
    provider: Any,
    system_prompt: str,
    user_message: str,
) -> CampaignStateInitialProposal:
    """1 attempt + 1 repair. Raises InvalidGenerationOutputError on 2 failures."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        data = await provider.generate_json(messages)
        return CampaignStateInitialProposal.model_validate(data)
    except (ValidationError, ValueError) as first_err:
        logger.warning(
            "initial_state: first attempt invalid (%s: %s), trying repair",
            type(first_err).__name__, first_err,
        )
        first_err_str = str(first_err)

    repair_suffix = (
        f"Your previous response did not match the required schema.\n"
        f"Validation error: {first_err_str}\n\n"
        f"Return only valid JSON matching the schema. "
        f"No prose, no markdown fences, no extra keys."
    )
    repair_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message + "\n\n" + repair_suffix},
    ]

    try:
        data2 = await provider.generate_json(repair_messages)
        return CampaignStateInitialProposal.model_validate(data2)
    except (ValidationError, ValueError) as second_err:
        logger.error(
            "initial_state: repair attempt also invalid: %s", second_err,
        )
        raise InvalidGenerationOutputError(
            f"LLM returned invalid output after repair attempt: {second_err}"
        ) from second_err


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class CampaignStateInitialService:
    """Оркестратор Initial Campaign State."""

    async def assert_campaign_exists(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
    ) -> Campaign:
        campaign = await db.get(Campaign, campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(str(campaign_id))
        return campaign

    async def _load_fields(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
    ) -> list[CampaignStateFieldConfig]:
        stmt = (
            select(CampaignStateFieldConfig)
            .where(CampaignStateFieldConfig.campaign_id == campaign_id)
            .order_by(
                CampaignStateFieldConfig.display_order.asc(),
                CampaignStateFieldConfig.key.asc(),
            )
        )
        return list((await db.execute(stmt)).scalars().all())

    async def start_preview(
        self,
        db: AsyncSession,
        redis: Any,
        campaign_id: uuid.UUID,
        document_ids: list[str],
        current_user: str | None = None,
    ) -> CampaignStateInitialProposalRead:
        """Сформировать LLM-proposal Initial State из выбранных Markdown."""
        await self.assert_campaign_exists(db, campaign_id)
        fields = await self._load_fields(db, campaign_id)
        if not fields:
            raise NoMarkdownDocumentsError(
                "campaign has no configured state fields"
            )
        enabled_fields = [f for f in fields if f.enabled]
        if not enabled_fields:
            raise NoMarkdownDocumentsError(
                "campaign has no enabled state fields"
            )

        # Разрешить UUID-ы документов.
        try:
            doc_uuids = [uuid.UUID(did) for did in document_ids]
        except ValueError as exc:
            raise DocumentNotFoundError(f"invalid document_id: {exc}") from exc

        docs_stmt = select(Document).where(Document.id.in_(doc_uuids))
        docs = list((await db.execute(docs_stmt)).scalars().all())
        if len(docs) != len(set(doc_uuids)):
            found_ids = {str(d.id) for d in docs}
            missing = [str(d) for d in doc_uuids if str(d) not in found_ids]
            raise DocumentNotFoundError(f"missing documents: {missing}")

        _validate_documents_indexed(docs)
        _validate_documents_md(docs)

        warnings: list[str] = []
        # Применяем фильтры по размеру и бюджету в порядке, запрошенном клиентом.
        by_id: dict[uuid.UUID, Document] = {d.id: d for d in docs}
        ordered_docs: list[Document] = []
        for did in doc_uuids:
            d = by_id.get(did)
            if d is not None:
                ordered_docs.append(d)

        # 1) per-doc limit (estimated_tokens)
        filtered_docs: list[Document] = _filter_by_per_doc_limit(ordered_docs, warnings)

        # 2) total budget 64k
        budgeted_docs: list[Document] = _apply_total_budget(filtered_docs, warnings)
        if not budgeted_docs:
            raise NoMarkdownDocumentsError(
                "no documents remain after token budget filtering"
            )

        # Build DocumentSnapshot list (только для тех, что прошли фильтры).
        snapshots: list[DocumentSnapshot] = [
            DocumentSnapshot(
                document_id=str(d.id),
                vault_id=d.vault_id,
                source_path=d.source_path,
                title=d.title,
                content_sha=d.md5,
                estimated_tokens=d.estimated_tokens or 0,
            )
            for d in budgeted_docs
        ]

        # Параллельный fetch полных текстов.
        fetch_results: list[str | None | BaseException] = await asyncio.gather(
            *[
                reconstruct_full_text(
                    document_id=str(d.id),
                    vault_id=d.vault_id,
                    db_api_url=_DB_API_URL,
                )
                for d in budgeted_docs
            ],
            return_exceptions=True,
        )
        docs_text: dict[str, str] = {}
        for d, result in zip(budgeted_docs, fetch_results):
            if isinstance(result, BaseException):
                logger.warning(
                    "initial_state: reconstruct failed for doc=%s: %s",
                    d.id, result,
                )
                warnings.append(f"reconstruction_failed:{d.id}")
                continue
            if not result:
                warnings.append(f"reconstruction_empty:{d.id}")
                continue
            docs_text[str(d.id)] = result

        if not docs_text:
            raise NoMarkdownDocumentsError(
                "no documents with successful full-text reconstruction"
            )

        # LLM call.
        provider = settings_service.get_active_provider()
        if provider is None:
            raise GenerationProviderUnavailableError("no active provider configured")

        system_prompt = _build_system_prompt(enabled_fields)
        user_message = _build_user_message(snapshots, docs_text)

        # Первый проход: получаем сырой dict, нормализуем (фильтрация по enabled,
        # source_refs), затем валидируем Pydantic.
        snapshot_doc_ids = {s.document_id for s in snapshots}

        raw = await _call_provider_with_repair_raw(provider, system_prompt, user_message)
        proposal = _normalize_proposal(
            raw,
            {f.key: f for f in enabled_fields},
            snapshot_doc_ids,
            warnings,
        )

        now = datetime.now(timezone.utc)
        payload = CampaignStateInitialProposalRead(
            proposal_id=str(uuid.uuid4()),
            campaign_id=str(campaign_id),
            config_version=(await db.get(Campaign, campaign_id)).config_version,
            source_snapshot=snapshots,
            proposal=proposal,
            warnings=warnings,
            created_at=now,
            expires_at=now + timedelta(seconds=int(_get_ttl())),
        )
        await campaign_state_initial_store.create(redis, payload)
        logger.info(
            "campaign_state_initial.start_preview: campaign=%s sources=%d fields=%d warnings=%d",
            campaign_id, len(snapshots), len(proposal.fields), len(warnings),
        )
        return payload

    async def get_proposal(
        self,
        redis: Any,
        campaign_id: uuid.UUID,
    ) -> CampaignStateInitialProposalRead | None:
        """Вернуть текущий proposal или None (если нет/истёк)."""
        return await campaign_state_initial_store.get(redis, str(campaign_id))

    async def apply(
        self,
        db: AsyncSession,
        redis: Any,
        campaign_id: uuid.UUID,
        request: CampaignStateInitialApplyRequest,
        current_user: str | None = None,
    ) -> Any:
        """Применить proposal как первую state version кампании."""
        await self.assert_campaign_exists(db, campaign_id)

        payload = await campaign_state_initial_store.get(redis, str(campaign_id))
        if payload is None:
            raise ProposalNotFoundError(str(campaign_id))

        if payload.proposal_id != request.proposal_id:
            raise ProposalNotFoundError(
                f"proposal_id mismatch: stored={payload.proposal_id}, "
                f"client={request.proposal_id}"
            )

        now = datetime.now(timezone.utc)
        if payload.expires_at <= now:
            await campaign_state_initial_store.delete(redis, str(campaign_id))
            raise ProposalExpiredError(
                f"proposal expired at {payload.expires_at.isoformat()}"
            )

        # Мерджим client-side overrides поверх proposal из Redis (по field_key).
        # source_snapshot не затрагивается — снапшот md5 проверяется дальше.
        effective_proposal = _merge_proposal_overrides(
            base=payload.proposal,
            overrides=request.proposal_overrides,
        )

        # Делегируем в value-сервис. Он сам бросит ConfigVersionConflictError,
        # InitialAlreadyAppliedError или SourceSnapshotStaleError.
        try:
            version_read = await campaign_state_value_service.apply_initial(
                db=db,
                campaign_id=campaign_id,
                proposal=effective_proposal,
                source_snapshot=payload.source_snapshot,
                config_version=request.config_version,
                created_by=current_user,
            )
        except CampaignStateValueError:
            # Не удаляем Redis-ключ: пользователь может исправить и повторить.
            raise

        # Успех — удаляем proposal.
        await campaign_state_initial_store.delete(redis, str(campaign_id))
        return version_read


# Module-level singleton
campaign_state_initial_service = CampaignStateInitialService()


# ---------------------------------------------------------------------------
# Internal helper: merge client-side overrides into stored proposal
# ---------------------------------------------------------------------------


def _merge_proposal_overrides(
    base: CampaignStateInitialProposal,
    overrides: CampaignStateInitialProposal | None,
) -> CampaignStateInitialProposal:
    """Мерджит proposal_overrides поверх base по field_key.

    - Если overrides is None — возвращает base (fast path).
    - Для каждого поля из overrides.field_key, присутствующего в base.fields,
      заменяет соответствующее поле в base. Неизвестные field_key игнорируются
      (не пробрасываются в результат).
    - Прочие поля (questions, fields, source_snapshot) остаются от base.
    """
    if overrides is None:
        return base

    base_fields_by_key = {f.field_key: f for f in base.fields}
    merged_fields = []
    for base_field in base.fields:
        override_field = next(
            (f for f in overrides.fields if f.field_key == base_field.field_key),
            None,
        )
        if override_field is None:
            merged_fields.append(base_field)
            continue

        # Заменяем только изменяемые атрибуты. mode/status приходят всегда,
        # но оставляем защиту: если override_field.mode/status валидны — берём их.
        merged_fields.append(
            base_field.model_copy(
                update={
                    "mode": override_field.mode,
                    "status": override_field.status,
                    "single_value": override_field.single_value
                        if override_field.single_value is not None
                        else base_field.single_value,
                    "list_value": override_field.list_value
                        if override_field.list_value is not None
                        else base_field.list_value,
                }
            )
        )

    # Тихий лог о том, были ли отброшены override-поля.
    override_keys = {f.field_key for f in overrides.fields}
    base_keys = set(base_fields_by_key.keys())
    dropped = override_keys - base_keys
    if dropped:
        logger.info(
            "apply_initial: dropped %d unknown override field(s): %s",
            len(dropped),
            sorted(dropped),
        )

    return base.model_copy(update={"fields": merged_fields})


# ---------------------------------------------------------------------------
# Internal helper: raw LLM call with repair (returns dict, not Pydantic)
# ---------------------------------------------------------------------------


async def _call_provider_with_repair_raw(
    provider: Any,
    system_prompt: str,
    user_message: str,
) -> dict[str, Any]:
    """1 attempt + 1 repair. Возвращает dict, нормализация — снаружи.

    Используется вместо _call_provider_with_repair, потому что нормализация
    (фильтрация неизвестных полей, source_refs) должна произойти ДО финальной
    Pydantic-валидации — иначе ремонт не поможет, если LLM вернул enabled=false
    поле или source_refs на несуществующий doc.

    Минимальная shape-проверка (dict с ключом 'fields') выполняется здесь же,
    чтобы repair срабатывал на структурно-неправильных ответах, а не только
    на исключениях из generate_json.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    first_err_str: str | None = None

    try:
        data = await provider.generate_json(messages)
        if not isinstance(data, dict):
            raise ValueError(
                f"LLM output is not a JSON object: {type(data).__name__}"
            )
        if "fields" not in data:
            raise ValueError(
                "LLM output is missing required 'fields' key"
            )
        return data
    except (ValidationError, ValueError, TypeError) as first_err:
        logger.warning(
            "initial_state: first attempt failed (%s: %s), trying repair",
            type(first_err).__name__, first_err,
        )
        first_err_str = str(first_err)

    repair_suffix = (
        f"Your previous response did not match the required JSON schema.\n"
        f"Error: {first_err_str}\n\n"
        f"Return only a valid JSON object with keys: fields, questions. "
        f"No prose, no markdown fences."
    )
    repair_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message + "\n\n" + repair_suffix},
    ]

    try:
        data2 = await provider.generate_json(repair_messages)
        if not isinstance(data2, dict):
            raise ValueError(
                f"LLM output is not a JSON object after repair: {type(data2).__name__}"
            )
        if "fields" not in data2:
            raise ValueError(
                "LLM output is missing required 'fields' key after repair"
            )
        return data2
    except (ValidationError, ValueError, TypeError) as second_err:
        logger.error(
            "initial_state: repair attempt also failed: %s", second_err,
        )
        raise InvalidGenerationOutputError(
            f"LLM returned invalid output after repair attempt: {second_err}"
        ) from second_err


def _get_ttl() -> int:
    """TTL из store (lazy import чтобы избежать circular)."""
    from app.services.campaign_state_initial_store import INITIAL_TTL_SECONDS

    return INITIAL_TTL_SECONDS
