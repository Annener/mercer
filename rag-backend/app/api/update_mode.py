"""update_mode.py — Campaign Update Mode API router.

Endpoints (all under /api/chats/{chat_id}/update-mode):

  POST   /start    — kick-off: parse note → resolve via indexer → store session
  GET    /session  — get current session status + changes list
  PATCH  /review   — accept / reject individual changes
  POST   /apply    — write accepted changes to vault filesystem + re-index
  DELETE /session  — cancel session

chat_id is the primary key for all operations.

Error mapping (POST /start):
  UpdateModeSessionAlreadyActiveError     → 409
  UpdateModeChatNotFoundError             → 404
  UpdateModeCampaignRequiredError         → 422
  UpdateModeCampaignNotFoundError         → 404
  UpdateModeCampaignDomainMismatchError   → 409
  UpdateModeCampaignTagsRequiredError     → 422
  UpdateModeNoEnabledVaultsError          → 422
  UpdateModeNoIndexedMarkdownError        → 422
  UpdateModeNoRelevantContextError        → 422
  UpdateModeNoUsableContextError          → 422
  UpdateModeGenerationProviderUnavailableError → 503
  UpdateModeInvalidGenerationOutputError  → 422
  UpdateModeIndexerUnavailableError       → 503
  UpdateModeIndexerInvalidResponseError   → 502
  UpdateModeReviewStoreUnavailableError   → 503
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign
from app.db.session import get_db
from app.services.indexer_client import (
    IndexerConflictError,
    IndexerUnavailableError,
    indexer_client,
)
from app.services.update_mode_executor import (
    UpdateModeCampaignDomainMismatchError,
    UpdateModeCampaignNotFoundError,
    UpdateModeCampaignRequiredError,
    UpdateModeCampaignTagsRequiredError,
    UpdateModeChatNotFoundError,
    UpdateModeExecutor,
    UpdateModeGenerationProviderUnavailableError,
    UpdateModeIndexerInvalidResponseError,
    UpdateModeIndexerUnavailableError,
    UpdateModeInvalidGenerationOutputError,
    UpdateModeNoEnabledVaultsError,
    UpdateModeNoIndexedMarkdownError,
    UpdateModeNoRelevantContextError,
    UpdateModeNoUsableContextError,
    UpdateModeReviewStoreUnavailableError,
    UpdateModeSessionAlreadyActiveError,
)
from app.services.update_mode_store import (
    ApplyConflictError,
    CannotAcceptFailedChangeError,
    FieldChangeReviewConflictError,
    ReviewConflictError,
    SessionExpiredError,
    StateOpReviewConflictError,
    UnknownChangeIdError,
    UnknownFieldChangeOpIndexError,
    UnknownStateOpIndexError,
    update_mode_store,
)
from shared_contracts.models import (
    ApplyUpdateModeRequest,
    ApplyUpdateModeResponse,
    CancelUpdateModeResponse,
    ResolvedUpdateModeChange,
    StartUpdateModeRequest,
    StartUpdateModeResponse,
    UpdateModeAction,
    UpdateModeApplyRequest,
    UpdateModeChangeStatus,
    UpdateModeFileChangeBatch,
    UpdateModeFileOp,
    UpdateModeOperation,
    UpdateModeReviewRequest,
    UpdateModeSession,
    UpdateModeSessionResponse,
    UpdateModeStateFieldChangeApplyResult,
    UpdateModeStatePatchApplyResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/chats/{chat_id}/update-mode",
    tags=["update-mode"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_to_response(session: UpdateModeSession) -> UpdateModeSessionResponse:
    return UpdateModeSessionResponse(
        chat_id=session.chat_id,
        campaign_id=session.campaign_id,
        domain_id=session.domain_id,
        vault_ids=session.vault_ids,
        expires_at=session.expires_at,
        changes=session.changes,
        warnings=session.warnings,
        state_field_snapshot=session.state_field_snapshot,
        state_patch_operations=session.state_patch_operations,
    )


async def _write_audit_log(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    payload: dict,
) -> None:
    """Fire-and-forget audit log write. Errors are logged but never re-raised."""
    try:
        from sqlalchemy import insert

        from app.db.models import AuditLog  # local import to avoid circular

        await db.execute(
            insert(AuditLog).values(
                id=str(uuid.uuid4()),
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor=actor,
                payload=payload,
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    except Exception:
        logger.warning("audit log write failed action=%s entity_id=%s", action, entity_id, exc_info=True)


def _build_file_batches(
    accepted: list[ResolvedUpdateModeChange],
) -> list[UpdateModeFileChangeBatch]:
    """Group accepted changes by (vault_id, file_path) and build file_batches.

    Sorting by resolve_order guarantees that multiple ops on the same file are
    applied in the order they were originally resolved (which matches the order
    LLM produced them and the order patch hunks were computed).

    Backward-compat: if a change has no operation field (session was written
    before this PR), fall back to a single overwrite op:
    - For a single legacy change: use proposed_content as a REPLACE via
      CREATE_FILE-style overwrite (the applier receives the full desired state).
    - For multiple legacy changes on the same file: last-write-wins — only
      the last change's proposed_content is used. A warning is logged.

    NOTE: proposed_content is the FULL file content after the op, not a delta.
    It must NOT be passed as content for incremental ops like APPEND_TO_FILE.
    Legacy path uses a dedicated overwrite operation (APPEND_TO_FILE with the
    full proposed_content only makes sense when the file is empty/new, which
    is not guaranteed here). For truly safe legacy overwrite semantics, the
    applier receives proposed_content as the complete desired file state via a
    synthetic single-op batch where the op replaces the entire file contents.
    """
    # Group by (vault_id, file_path), preserving vault/file_path from change
    groups: dict[tuple[str, str], list[ResolvedUpdateModeChange]] = defaultdict(list)
    skipped = 0
    for ch in accepted:
        if ch.vault_id is None or ch.file_path is None:
            logger.warning(
                "Skipping change %s: missing vault_id or file_path", ch.change_id
            )
            skipped += 1
            continue
        groups[(ch.vault_id, ch.file_path)].append(ch)

    if skipped:
        logger.info("_build_file_batches: skipped %d incomplete changes", skipped)

    batches: list[UpdateModeFileChangeBatch] = []
    for (vault_id, file_path), changes in groups.items():
        # Sort by resolve_order so multi-op patches are applied in correct sequence.
        # resolve_order=-1 is the legacy sentinel; treat as 0 for sorting purposes.
        changes.sort(key=lambda c: max(c.resolve_order, 0))

        # Detect whether any change in this group carries operation metadata.
        has_operation = any(ch.operation is not None for ch in changes)

        ops: list[UpdateModeFileOp] = []
        if has_operation:
            # New-style changes: build one op per change.
            for i, ch in enumerate(changes):
                if ch.operation is not None:
                    ops.append(
                        UpdateModeFileOp(
                            change_id=ch.change_id,
                            operation=ch.operation,
                            anchor_value=ch.anchor.value if ch.anchor else None,
                            content=ch.op_content,
                            # CAS check only on first op of UPDATE batches
                            expected_sha256=(
                                ch.expected_sha256
                                if i == 0 and ch.action == UpdateModeAction.UPDATE
                                else None
                            ),
                            description=ch.description,
                        )
                    )
                else:
                    # Mixed group: some changes have operation, some don't.
                    # This shouldn't happen in practice but handle it gracefully:
                    # skip the legacy change and log a warning.
                    logger.warning(
                        "Change %s in mixed group has no operation field — skipping",
                        ch.change_id,
                    )
        else:
            # Pure legacy group: no change has operation field.
            # proposed_content is the FULL desired file state, not a delta.
            # We cannot compose multiple legacy full-file states, so last-write-wins.
            if len(changes) > 1:
                logger.warning(
                    "update-mode legacy backward-compat: %d changes share "
                    "file_path=%r but none has operation field — "
                    "using only the last change (%s). "
                    "Other changes are dropped (last-write-wins fallback).",
                    len(changes), file_path, changes[-1].change_id,
                )
            last = changes[-1]
            # Use REPLACE_UNIQUE_TEXT is not suitable here because we don't have
            # an anchor. Instead, use a single CREATE_FILE-style op: the applier
            # will receive the full desired content and write it atomically.
            # For UPDATE batches we reuse the same action but pass proposed_content
            # as the full file — the applier's text_ops will write it via
            # APPEND_TO_FILE on an empty buffer after current content is cleared.
            # The safest legacy overwrite is: deliver proposed_content as the
            # sole op content for a CREATE_FILE operation regardless of action,
            # since proposed_content == full intended state of the file.
            # We set action=CREATE to bypass the CAS check that would otherwise
            # fire on ops[0].expected_sha256=None for an UPDATE batch.
            # This is safe because proposed_content was computed at resolve time
            # from the original and already encodes the full desired state.
            if last.action == UpdateModeAction.UPDATE:
                ops = [
                    UpdateModeFileOp(
                        change_id=last.change_id,
                        operation=UpdateModeOperation.CREATE_FILE,
                        anchor_value=None,
                        content=last.proposed_content,
                        expected_sha256=None,
                        # Legacy path: description intentionally left empty
                    )
                ]
                # Override action to CREATE so the validator and applier skip
                # the CAS check (proposed_content is already the full state).
                batches.append(
                    UpdateModeFileChangeBatch(
                        vault_id=vault_id,
                        file_path=file_path,
                        action=UpdateModeAction.CREATE,
                        ops=ops,
                    )
                )
                continue
            else:
                # action=CREATE already: write proposed_content as-is.
                ops = [
                    UpdateModeFileOp(
                        change_id=last.change_id,
                        operation=UpdateModeOperation.CREATE_FILE,
                        anchor_value=None,
                        content=last.proposed_content,
                        expected_sha256=None,
                        # Legacy path: description intentionally left empty
                    )
                ]

        if ops:
            batches.append(
                UpdateModeFileChangeBatch(
                    vault_id=vault_id,
                    file_path=file_path,
                    action=changes[0].action,
                    ops=ops,
                )
            )

    return batches


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------


@router.post("/start", response_model=StartUpdateModeResponse, status_code=200)
async def start_update_mode(
    chat_id: str,
    body: StartUpdateModeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StartUpdateModeResponse:
    """Validate campaign context, retrieve docs, generate intents, resolve via indexer,
    store Redis review session.

    campaign_id is resolved from chat.campaign_id via DB — no query param needed.
    """
    redis = request.app.state.redis

    executor = UpdateModeExecutor(
        db=db,
        store=update_mode_store,
        indexer_client=indexer_client,
    )

    try:
        session = await executor.start(chat_id=chat_id, redis=redis, note=body.note)
    except UpdateModeSessionAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=exc.code)
    except UpdateModeChatNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.code)
    except UpdateModeCampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.code)
    except UpdateModeCampaignRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeCampaignDomainMismatchError as exc:
        raise HTTPException(status_code=409, detail=exc.code)
    except UpdateModeCampaignTagsRequiredError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoEnabledVaultsError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoIndexedMarkdownError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoRelevantContextError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeNoUsableContextError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeInvalidGenerationOutputError as exc:
        raise HTTPException(status_code=422, detail=exc.code)
    except UpdateModeGenerationProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code)
    except UpdateModeIndexerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code)
    except UpdateModeIndexerInvalidResponseError as exc:
        raise HTTPException(status_code=502, detail=exc.code)
    except UpdateModeReviewStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code)

    return StartUpdateModeResponse(
        chat_id=session.chat_id,
        expires_at=session.expires_at,
        changes=session.changes,
        warnings=session.warnings,
        state_field_snapshot=session.state_field_snapshot,
        state_patch_operations=session.state_patch_operations,
    )


# ---------------------------------------------------------------------------
# GET /session
# ---------------------------------------------------------------------------


@router.get("/session", response_model=UpdateModeSessionResponse)
async def get_update_mode_session(
    chat_id: str,
    request: Request,
    response: Response,
) -> UpdateModeSessionResponse:
    redis = request.app.state.redis

    session = await update_mode_store.get(redis, chat_id)
    if session is None:
        response.headers["Cache-Control"] = "no-store"
        raise HTTPException(status_code=410, detail="session_expired")

    return _session_to_response(session)


# ---------------------------------------------------------------------------
# PATCH /review
# ---------------------------------------------------------------------------


@router.patch("/review", response_model=UpdateModeSessionResponse)
async def review_changes(
    chat_id: str,
    body: UpdateModeReviewRequest,
    request: Request,
) -> UpdateModeSessionResponse:
    redis = request.app.state.redis

    accepted_state: set[int] = set()
    rejected_state: set[int] = set()
    edited_state: dict[int, str] = {}
    if body.state_patch_decisions is not None:
        accepted_state = set(body.state_patch_decisions.accepted_op_indexes)
        rejected_state = set(body.state_patch_decisions.rejected_op_indexes)
        edited_state = {
            e.op_index: e.text for e in body.state_patch_decisions.edited
        }

    accepted_field: set[int] = set()
    rejected_field: set[int] = set()
    if body.field_change_decisions is not None:
        accepted_field = set(body.field_change_decisions.accepted_op_indexes)
        rejected_field = set(body.field_change_decisions.rejected_op_indexes)

    try:
        session = await update_mode_store.update_review(
            redis,
            chat_id,
            accepted_change_ids=set(body.accepted_change_ids),
            rejected_change_ids=set(body.rejected_change_ids),
            accepted_state_op_indexes=accepted_state,
            rejected_state_op_indexes=rejected_state,
            edited_state_ops=edited_state,
            accepted_field_op_indexes=accepted_field,
            rejected_field_op_indexes=rejected_field,
        )
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except UnknownChangeIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CannotAcceptFailedChangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except UnknownStateOpIndexError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except StateOpReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except UnknownFieldChangeOpIndexError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FieldChangeReviewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return _session_to_response(session)


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------


@router.post("/apply", response_model=ApplyUpdateModeResponse)
async def apply_changes(
    chat_id: str,
    body: ApplyUpdateModeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApplyUpdateModeResponse:
    """Delegate writing + reindex to rag-indexer. Idempotent for same apply_id.

    Builds file_batches from accepted session changes so the indexer can apply
    multiple ops to the same file in a single atomic read-modify-write cycle.

    Stage 5: additionally applies accepted Campaign State patch via
    campaign_state_value_service.apply_patch. File changes and state patch
    are accepted independently — failure of one does not roll back the other.

    After receiving the indexer response:
    - persists apply_result in the Redis session via complete_apply()
    - writes an AuditLog row (update_mode.apply)
    - writes an AuditLog row (update_mode.reject_state_patch) if any state
      ops were rejected
    - applies accepted state_patch ops and records the result in the response
    """
    redis = request.app.state.redis

    try:
        session = await update_mode_store.begin_apply(redis, chat_id, body.apply_id)
    except SessionExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except ApplyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    accepted_changes = [
        ch for ch in session.changes
        if ch.status == UpdateModeChangeStatus.ACCEPTED
    ]
    file_batches = _build_file_batches(accepted_changes) if accepted_changes else []

    has_file_changes = bool(file_batches)
    accepted_state_entries = [
        e for e in session.state_patch_operations if e.status == "accepted"
    ]
    rejected_state_entries = [
        e for e in session.state_patch_operations if e.status == "rejected"
    ]
    has_state_changes = bool(accepted_state_entries) or bool(rejected_state_entries)

    # Sprint 3: schema-change decisions.
    accepted_field_entries = [
        e for e in session.state_field_change_operations if e.status == "accepted"
    ]
    rejected_field_entries = [
        e for e in session.state_field_change_operations if e.status == "rejected"
    ]
    has_field_changes = bool(accepted_field_entries) or bool(rejected_field_entries)

    if not has_file_changes and not has_state_changes and not has_field_changes:
        raise HTTPException(
            status_code=422,
            detail=(
                "No accepted changes to apply. Use PATCH /review to accept "
                "changes, state_patch_decisions, or field_change_decisions first."
            ),
        )

    # ----- Stage A: apply accepted schema (create_field / update_field) -----
    # Schema must succeed BEFORE state_patch, because state_patch may
    # reference fields that are being created in the same proposal.
    # If schema fails, we abort the entire apply (no state_patch, no files).
    field_changes_result: UpdateModeStateFieldChangeApplyResult | None = None
    if accepted_field_entries:
        field_changes_result = await _apply_schema_changes(
            db=db,
            campaign_id_str=session.campaign_id,
            accepted_field_entries=accepted_field_entries,
        )
        if field_changes_result and field_changes_result.failed_op_indexes:
            # Schema apply failed — abort.
            await _write_audit_log(
                db=db,
                action="update_mode.apply_aborted_schema",
                entity_type="campaign",
                entity_id=session.campaign_id,
                actor=f"chat:{chat_id}",
                payload={
                    "apply_id": session.apply_id or "",
                    "failed_field_op_indexes": field_changes_result.failed_op_indexes,
                    "failed_reasons": field_changes_result.failed_reasons,
                    "rolled_back": True,
                },
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "schema_apply_failed",
                    "failed_op_indexes": field_changes_result.failed_op_indexes,
                    "failed_reasons": field_changes_result.failed_reasons,
                    "message": (
                        "Schema changes failed; state and file apply aborted. "
                        "Re-review and try again."
                    ),
                },
            )

    apply_resp = None
    if file_batches:
        apply_req = UpdateModeApplyRequest(
            apply_id=session.apply_id or str(uuid.uuid4()),
            chat_id=chat_id,
            campaign_id=session.campaign_id,
            file_batches=file_batches,
        )
        try:
            apply_resp = await indexer_client.apply(apply_req)
        except IndexerConflictError as exc:
            raise HTTPException(status_code=409, detail=f"Apply conflict: {exc.detail}")
        except IndexerUnavailableError as exc:
            raise HTTPException(status_code=502, detail=f"Indexer unavailable: {exc.detail}")

        # Persist completed result into Redis session (non-fatal if session already expired)
        await update_mode_store.complete_apply(redis, chat_id, apply_resp)

    # ----- Stage 5: apply accepted state_patch ops -----
    state_patch_result: UpdateModeStatePatchApplyResult | None = None
    if accepted_state_entries:
        state_patch_result = await _apply_state_patch(
            db=db,
            campaign_id_str=session.campaign_id,
            accepted_entries=accepted_state_entries,
            chat_id=chat_id,
        )

    # ----- Audit logs -----
    audit_payload: dict[str, Any] = {
        "apply_id": (apply_resp.apply_id if apply_resp else None),
        "chat_id": chat_id,
        "campaign_id": session.campaign_id,
        "vault_results": [],
        "state_patch": {
            "accepted_op_indexes": [e.op_index for e in accepted_state_entries],
            "rejected_op_indexes": [e.op_index for e in rejected_state_entries],
            "edited_op_indexes": [
                e.op_index
                for e in session.state_patch_operations
                if e.edited_text is not None
            ],
            "applied_state_version": (
                state_patch_result.applied_state_version if state_patch_result else 0
            ),
            "config_version": (
                state_patch_result.config_version if state_patch_result else 0
            ),
            "failed_op_indexes": (
                state_patch_result.failed_op_indexes if state_patch_result else []
            ),
            "from_state_version": (
                state_patch_result.applied_state_version - 1
                if state_patch_result and state_patch_result.applied_state_version > 0
                else None
            ),
        },
        "field_changes": {
            "accepted_op_indexes": [e.op_index for e in accepted_field_entries],
            "rejected_op_indexes": [e.op_index for e in rejected_field_entries],
            "applied_op_indexes": (
                field_changes_result.applied_op_indexes if field_changes_result else []
            ),
            "failed_op_indexes": (
                field_changes_result.failed_op_indexes if field_changes_result else []
            ),
            "new_config_version": (
                field_changes_result.new_config_version if field_changes_result else 0
            ),
        },
    }
    if apply_resp is not None:
        audit_payload["vault_results"] = [
            {
                "vault_id": r.vault_id,
                "status": r.status.value,
                "applied_count": r.applied_count,
                "commit_sha": r.commit_sha,
                "reindex_task_id": r.reindex_task_id,
            }
            for r in apply_resp.results
        ]

    await _write_audit_log(
        db=db,
        action="update_mode.apply",
        entity_type="campaign",
        entity_id=session.campaign_id,
        actor=f"chat:{chat_id}",
        payload=audit_payload,
    )

    if rejected_state_entries:
        await _write_audit_log(
            db=db,
            action="update_mode.reject_state_patch",
            entity_type="campaign",
            entity_id=session.campaign_id,
            actor=f"chat:{chat_id}",
            payload={
                "rejected_op_indexes": [e.op_index for e in rejected_state_entries],
                "ops": [
                    {
                        "op_index": e.op_index,
                        "field_key": e.field_key,
                        "type": e.operation.type,
                        "reason": e.operation.reason,
                    }
                    for e in rejected_state_entries
                ],
            },
        )

    return ApplyUpdateModeResponse(
        apply_id=(apply_resp.apply_id if apply_resp else (session.apply_id or "")),
        results=(apply_resp.results if apply_resp is not None else []),
        state_patch_result=state_patch_result,
        field_changes_result=field_changes_result,
    )


async def _apply_state_patch(
    *,
    db: AsyncSession,
    campaign_id_str: str,
    accepted_entries: list,
    chat_id: str,
) -> UpdateModeStatePatchApplyResult | None:
    """Apply accepted state_patch operations through campaign_state_value_service.

    Returns an UpdateModeStatePatchApplyResult describing what was applied.
    Never raises on state-patch conflict — the result captures failed op_indexes
    so the caller can surface them to the client without aborting file apply.
    """
    from app.services.campaign_state_value_service import (
        CampaignStateValueError,
        campaign_state_value_service,
    )

    campaign_uuid = uuid.UUID(campaign_id_str)

    active_state = await campaign_state_value_service.get_active_state(
        db, campaign_uuid
    )
    base_state_version = active_state.summary.state_version if active_state else None

    campaign = await db.get(Campaign, campaign_uuid)
    if campaign is None:
        return UpdateModeStatePatchApplyResult(
            applied_state_version=0,
            config_version=0,
            applied_op_indexes=[],
            failed_op_indexes=[e.op_index for e in accepted_entries],
            failed_reasons={"campaign": "campaign_not_found"},
        )
    server_config_version = campaign.config_version

    # Build CampaignStatePatchRequest, applying edited_text where present.
    operations = []
    applied_indexes: list[int] = []
    for e in accepted_entries:
        op = e.operation
        if e.edited_text is not None and op.type in (
            "replace_single",
            "update_list_item",
            "add_list_item",
        ):
            op = op.model_copy(update={"text": e.edited_text})
        operations.append(op)
        applied_indexes.append(e.op_index)

    try:
        from shared_contracts.models import CampaignStatePatchRequest

        req = CampaignStatePatchRequest(
            base_state_version=base_state_version,
            config_version=server_config_version,
            operations=operations,
        )
        resp = await campaign_state_value_service.apply_patch(
            db=db,
            campaign_id=campaign_uuid,
            request=req,
            created_by=f"chat:{chat_id}",
        )
    except CampaignStateValueError as exc:
        return UpdateModeStatePatchApplyResult(
            applied_state_version=0,
            config_version=server_config_version,
            applied_op_indexes=[],
            failed_op_indexes=applied_indexes,
            failed_reasons={str(i): exc.code for i in applied_indexes},
        )

    return UpdateModeStatePatchApplyResult(
        applied_state_version=resp.applied_state_version,
        config_version=resp.config_version,
        applied_op_indexes=applied_indexes,
        failed_op_indexes=[],
        failed_reasons={},
    )


# ---------------------------------------------------------------------------
# Sprint 3: _apply_schema_changes (Stage A of apply)
# ---------------------------------------------------------------------------


async def _apply_schema_changes(
    *,
    db: AsyncSession,
    campaign_id_str: str,
    accepted_field_entries: list,
) -> UpdateModeStateFieldChangeApplyResult | None:
    """Apply accepted schema operations (create_field / update_field).

    Atomic: if ANY operation fails, all previously-applied schema changes
    in this batch are rolled back. The host treats this as Stage A — if
    we fail, the rest of the apply (state_patch + files) is aborted.

    Returns an UpdateModeStateFieldChangeApplyResult. On full failure
    (had_failures=True) the caller should raise 422 and NOT proceed to
    state_patch / file apply.

    Audit log: writes one `update_mode.apply_schema` entry summarising
    applied + failed ops and the new config_version.
    """
    import uuid as _uuid

    from app.db.models import (
        AuditLog,
        Campaign,
        CampaignStateFieldConfig,
    )
    from app.services.campaign_state_service import (
        CampaignStateFieldError,
        campaign_state_field_service,
    )
    from shared_contracts.models import (
        CampaignStateFieldConfigCreate,
        CampaignStateFieldConfigUpdate,
        ContextFieldChangeOperation,
    )

    if not accepted_field_entries:
        return None

    campaign_uuid = uuid.UUID(campaign_id_str)

    # Apply in deterministic order: create_field first, then update_field.
    # Within each group, original op_index order is preserved.
    creates = [e for e in accepted_field_entries if e.operation == ContextFieldChangeOperation.CREATE_FIELD]
    updates = [e for e in accepted_field_entries if e.operation == ContextFieldChangeOperation.UPDATE_FIELD]
    ordered = creates + updates

    applied_indexes: list[int] = []
    failed_indexes: list[int] = []
    failed_reasons: dict[str, str] = {}
    # Track created fields for rollback on partial failure.
    created_field_ids: list[str] = []
    # Track field_id lookup for update_field rollback (in case a later
    # update_field fails — we won't roll those back unless create_field
    # after them also failed, since update_field doesn't add a new
    # resource the rest of apply depends on).
    pre_update_field_ids: dict[str, str] = {}  # op_index -> field_id

    had_failure = False
    for entry in ordered:
        try:
            if entry.operation == ContextFieldChangeOperation.CREATE_FIELD:
                payload = CampaignStateFieldConfigCreate(
                    key=entry.key,
                    label=entry.proposed_label or entry.key,
                    description=entry.proposed_description or "",
                    mode=entry.proposed_mode or "single",  # type: ignore[arg-type]
                    enabled=(
                        entry.proposed_enabled
                        if entry.proposed_enabled is not None
                        else True
                    ),
                    display_order=(
                        entry.proposed_display_order
                        if entry.proposed_display_order is not None
                        else 1000
                    ),
                )
                created = await campaign_state_field_service.create_field(
                    db, campaign_uuid, payload
                )
                created_field_ids.append(str(created.id))
                applied_indexes.append(entry.op_index)
            elif entry.operation == ContextFieldChangeOperation.UPDATE_FIELD:
                # Look up field_id by key.
                stmt = select(CampaignStateFieldConfig).where(
                    CampaignStateFieldConfig.campaign_id == campaign_uuid,
                    CampaignStateFieldConfig.key == entry.key,
                )
                row = (await db.execute(stmt)).scalar_one_or_none()
                if row is None:
                    raise CampaignStateFieldError(  # noqa: TRY301
                        "field_not_found",
                        f"field {entry.key!r} not found",
                    )
                pre_update_field_ids[str(entry.op_index)] = str(row.id)
                # Build partial update payload.
                update_kwargs: dict[str, Any] = {}
                if entry.proposed_label is not None:
                    update_kwargs["label"] = entry.proposed_label
                if entry.proposed_description is not None:
                    update_kwargs["description"] = entry.proposed_description
                if entry.proposed_enabled is not None:
                    update_kwargs["enabled"] = entry.proposed_enabled
                if entry.proposed_display_order is not None:
                    update_kwargs["display_order"] = entry.proposed_display_order
                if not update_kwargs:
                    # Nothing to update — record as applied (no-op).
                    applied_indexes.append(entry.op_index)
                else:
                    payload = CampaignStateFieldConfigUpdate(**update_kwargs)
                    await campaign_state_field_service.update_field(
                        db, campaign_uuid, _uuid.UUID(str(row.id)), payload
                    )
                    applied_indexes.append(entry.op_index)
        except CampaignStateFieldError as exc:
            had_failure = True
            failed_indexes.append(entry.op_index)
            failed_reasons[str(entry.op_index)] = exc.code
        except Exception as exc:  # noqa: BLE001
            had_failure = True
            failed_indexes.append(entry.op_index)
            failed_reasons[str(entry.op_index)] = str(exc)

    # If we created any fields and a later op failed, roll back the
    # created fields. The host treats this as full failure.
    if had_failure and created_field_ids:
        for fid in created_field_ids:
            try:
                await campaign_state_field_service.delete_field(
                    db, campaign_uuid, _uuid.UUID(fid)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "update_mode _apply_schema_changes: rollback of created "
                    "field %s failed: %s",
                    fid,
                    exc,
                )

    # Reload campaign to get final config_version (post any partial success).
    final_campaign = await db.get(Campaign, campaign_uuid)
    new_config_version = final_campaign.config_version if final_campaign else 0

    # Audit log.
    try:
        db.add(
            AuditLog(
                action="update_mode.apply_schema",
                entity_type="campaign",
                entity_id=campaign_id_str,
                actor="update_mode",
                payload={
                    "applied_op_indexes": applied_indexes,
                    "failed_op_indexes": failed_indexes,
                    "failed_reasons": failed_reasons,
                    "new_config_version": new_config_version,
                    "rolled_back": had_failure and bool(created_field_ids),
                },
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "update_mode _apply_schema_changes: audit log write failed: %s",
            exc,
        )

    return UpdateModeStateFieldChangeApplyResult(
        applied_op_indexes=applied_indexes,
        failed_op_indexes=failed_indexes,
        failed_reasons=failed_reasons,
        new_config_version=new_config_version,
    )


# ---------------------------------------------------------------------------
# DELETE /session
# ---------------------------------------------------------------------------


@router.delete("/session", response_model=CancelUpdateModeResponse)
async def cancel_update_mode(
    chat_id: str,
    request: Request,
) -> CancelUpdateModeResponse:
    redis = request.app.state.redis
    await update_mode_store.delete(redis, chat_id)
    return CancelUpdateModeResponse(status="cancelled")
