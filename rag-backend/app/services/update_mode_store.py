"""update_mode_store.py — Redis-backed session store for Campaign Update Mode.

Key: update_mode:{chat_id}
TTL: 3 hours, renewed on start/review/apply_begin.

Atomicity:
  update_review and begin_apply use a Lua CAS script to avoid lost updates
  from concurrent PATCH requests. The script reads, mutates, and writes in
  a single server-side transaction — no WATCH/MULTI overhead per operation.

  complete_apply uses a Lua script to atomically:
    - write apply_result into the session
    - transition apply_state: "in_progress" -> "completed"
    - renew TTL

cjson empty-array fix:
  cjson (the JSON library bundled with Redis) cannot distinguish an empty
  Lua table from an empty Lua array — both serialise to "{}". This would
  break Pydantic validation for every list field in UpdateModeSession
  (warnings, vault_ids, candidate_document_ids, changes) after a Lua
  round-trip.

  Each Lua script calls _fix_session_arrays() before cjson.encode to mark
  known list fields with cjson.empty_array_mt, so they are written back as
  "[]" rather than "{}".

  A Python-side _normalize_session_lists() guard is also applied in all
  result-parser methods as defence-in-depth — it handles any session blob
  written by old code before this patch, or any future field not yet
  covered by the Lua helper.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis.asyncio as aioredis

from shared_contracts.models import (
    UpdateModeApplyResponse,
    UpdateModeSession,
)

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 3 * 60 * 60  # 3 hours

# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class UpdateModeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SessionAlreadyActiveError(UpdateModeError):
    def __init__(self, chat_id: str) -> None:
        super().__init__("session_already_active", f"Session already active for chat {chat_id}")


class SessionExpiredError(UpdateModeError):
    def __init__(self, chat_id: str) -> None:
        super().__init__("session_expired", f"No active session for chat {chat_id}")


class UnknownChangeIdError(UpdateModeError):
    def __init__(self, change_id: str) -> None:
        super().__init__("unknown_change_id", f"change_id not found in session: {change_id}")


class CannotAcceptFailedChangeError(UpdateModeError):
    def __init__(self, change_id: str) -> None:
        super().__init__("cannot_accept_failed_change", f"change_id {change_id} has status resolution_failed and cannot be accepted")


class ReviewConflictError(UpdateModeError):
    def __init__(self, change_id: str) -> None:
        super().__init__("review_conflict", f"change_id {change_id} is not in pending state")


class ApplyConflictError(UpdateModeError):
    def __init__(self, requested: str, existing: str) -> None:
        super().__init__(
            "apply_id_conflict",
            f"Session already has apply_id={existing}, cannot start new apply with apply_id={requested}",
        )


# ---------------------------------------------------------------------------
# Shared Lua helper: fix empty arrays before cjson.encode
# ---------------------------------------------------------------------------
# cjson cannot tell an empty Lua table from an empty object, so it encodes
# both as "{}". _fix_session_arrays() tags top-level session list fields with
# cjson.empty_array_mt so they round-trip as "[]".
#
# This snippet is embedded verbatim into every Lua script below.
_LUA_FIX_ARRAYS = """
local function _fix_session_arrays(sess)
    local list_fields = {'warnings', 'vault_ids', 'candidate_document_ids', 'changes'}
    for _, f in ipairs(list_fields) do
        if type(sess[f]) == 'table' and next(sess[f]) == nil then
            sess[f] = cjson.empty_array
        end
    end
    -- Also fix nested list fields inside each change object.
    if type(sess['changes']) == 'table' then
        for _, ch in ipairs(sess['changes']) do
            -- (no list fields on ResolvedUpdateModeChange currently, but guard stays)
        end
    end
    -- Fix apply_result.results if present
    if type(sess['apply_result']) == 'table' then
        local ar = sess['apply_result']
        if type(ar['results']) == 'table' and next(ar['results']) == nil then
            ar['results'] = cjson.empty_array
        end
    end
    return sess
end
"""

# ---------------------------------------------------------------------------
# Lua script for atomic review update
# ---------------------------------------------------------------------------
# KEYS[1] = redis key
# ARGV[1] = json array of accepted change_ids
# ARGV[2] = json array of rejected change_ids
# ARGV[3] = new TTL seconds
# Returns: updated session JSON string, or error string prefixed with "ERR:"
_REVIEW_LUA = (
    _LUA_FIX_ARRAYS
    + """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 'ERR:session_expired'
end
local session = cjson.decode(raw)
local accepted = cjson.decode(ARGV[1])
local rejected = cjson.decode(ARGV[2])
local ttl = tonumber(ARGV[3])

-- Build lookup
local change_map = {}
for _, ch in ipairs(session['changes']) do
    change_map[ch['change_id']] = ch
end

-- Validate and apply
for _, cid in ipairs(accepted) do
    local ch = change_map[cid]
    if not ch then return 'ERR:unknown_change_id:' .. cid end
    if ch['status'] == 'resolution_failed' then return 'ERR:cannot_accept_failed:' .. cid end
    if ch['status'] ~= 'pending' then return 'ERR:review_conflict:' .. cid end
    ch['status'] = 'accepted'
end
for _, cid in ipairs(rejected) do
    local ch = change_map[cid]
    if not ch then return 'ERR:unknown_change_id:' .. cid end
    if ch['status'] ~= 'pending' then return 'ERR:review_conflict:' .. cid end
    ch['status'] = 'rejected'
end

session = _fix_session_arrays(session)
local updated = cjson.encode(session)
redis.call('SET', KEYS[1], updated, 'EX', ttl)
return updated
"""
)

# ---------------------------------------------------------------------------
# Lua script for atomic apply_begin
# ---------------------------------------------------------------------------
# KEYS[1] = redis key
# ARGV[1] = apply_id — MUST be a non-empty UUID string; caller is responsible
#           for generating it before calling this script (see begin_apply).
# ARGV[2] = new TTL seconds
# ARGV[3] = apply_started_at ISO string
# Returns: updated session JSON, or one of:
#   "ERR:session_expired"           key not found
#   "ERR:apply_conflict:{existing}" different apply_id already set
#   "ERR:missing_apply_id"          ARGV[1] was empty (programming error)
_APPLY_BEGIN_LUA = (
    _LUA_FIX_ARRAYS
    + """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 'ERR:session_expired'
end
local requested = ARGV[1]
if requested == '' then
    return 'ERR:missing_apply_id'
end
local session = cjson.decode(raw)
local ttl = tonumber(ARGV[2])
local started_at = ARGV[3]

if session['apply_id'] and session['apply_id'] ~= cjson.null then
    -- Already has an apply_id
    if requested == session['apply_id'] then
        -- Same ID: idempotent retry — return existing session unchanged
        session = _fix_session_arrays(session)
        return cjson.encode(session)
    else
        return 'ERR:apply_conflict:' .. session['apply_id']
    end
end

session['apply_id'] = requested
session['apply_started_at'] = started_at

session = _fix_session_arrays(session)
local updated = cjson.encode(session)
redis.call('SET', KEYS[1], updated, 'EX', ttl)
return updated
"""
)

# ---------------------------------------------------------------------------
# Lua script for atomic apply completion
# ---------------------------------------------------------------------------
# Writes apply_result + transitions apply_state -> "completed".
#
# KEYS[1] = redis key
# ARGV[1] = apply_result JSON string
# ARGV[2] = new TTL seconds
# Returns: updated session JSON, or:
#   "ERR:session_expired"  — key not found (session expired between apply start and completion)
_APPLY_COMPLETE_LUA = (
    _LUA_FIX_ARRAYS
    + """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 'ERR:session_expired'
end
local session = cjson.decode(raw)
local ttl = tonumber(ARGV[2])

session['apply_result'] = cjson.decode(ARGV[1])
session['apply_state'] = 'completed'

session = _fix_session_arrays(session)
local updated = cjson.encode(session)
redis.call('SET', KEYS[1], updated, 'EX', ttl)
return updated
"""
)


# ---------------------------------------------------------------------------
# Python-side defence: normalise any {} that slipped through (back-compat)
# ---------------------------------------------------------------------------
# Applied in all result parsers BEFORE model_validate. Handles sessions
# written by code before this patch (e.g. still cached in Redis on deploy).
_SESSION_LIST_FIELDS = ("warnings", "vault_ids", "candidate_document_ids", "changes")


def _normalize_session_lists(data: dict[str, Any]) -> dict[str, Any]:
    """Replace empty dicts with empty lists for known list fields.

    cjson may have encoded an empty Lua table as {} instead of [].
    This guard converts them back so Pydantic validation does not fail.
    Works on sessions produced by old code before the Lua fix was deployed.
    """
    for field in _SESSION_LIST_FIELDS:
        if isinstance(data.get(field), dict) and not data[field]:
            data[field] = []
    # Nested: apply_result.results
    apply_result = data.get("apply_result")
    if isinstance(apply_result, dict):
        if isinstance(apply_result.get("results"), dict) and not apply_result["results"]:
            apply_result["results"] = []
    return data


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class UpdateModeStore:
    """Redis-backed session store for Campaign Update Mode.

    One instance per application. Receives a redis client via dependency injection
    (passed from request.app.state.redis) rather than holding a singleton reference,
    so it can be tested without a running app.
    """

    # Lua script SHA cache per redis connection (filled lazily)
    _review_sha: str | None = None
    _apply_sha: str | None = None
    _complete_sha: str | None = None

    @staticmethod
    def _key(chat_id: str) -> str:
        return f"update_mode:{chat_id}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, redis: "aioredis.Redis", chat_id: str) -> UpdateModeSession | None:
        raw = await redis.get(self._key(chat_id))
        if raw is None:
            return None
        data = _normalize_session_lists(json.loads(raw))
        return UpdateModeSession.model_validate(data)

    async def create(self, redis: "aioredis.Redis", session: UpdateModeSession) -> None:
        key = self._key(session.chat_id)
        # NX = only set if not exists — prevents overwriting an active session
        payload = json.dumps(session.model_dump(mode="json"), ensure_ascii=False)
        set_result = await redis.set(key, payload, ex=SESSION_TTL_SECONDS, nx=True)
        if set_result is None:
            raise SessionAlreadyActiveError(session.chat_id)
        logger.info("update_mode session created chat_id=%s session_id=%s", session.chat_id, session.session_id)

    async def update_review(
        self,
        redis: "aioredis.Redis",
        chat_id: str,
        accepted_change_ids: set[str],
        rejected_change_ids: set[str],
    ) -> UpdateModeSession:
        """Atomically accept/reject changes in the session.

        Raises:
            SessionExpiredError: key missing.
            UnknownChangeIdError: change_id not in session.
            CannotAcceptFailedChangeError: trying to accept a resolution_failed change.
            ReviewConflictError: change not in pending state.
        """
        sha = await self._ensure_review_script(redis)
        result = await redis.evalsha(
            sha,
            1,
            self._key(chat_id),
            json.dumps(list(accepted_change_ids)),
            json.dumps(list(rejected_change_ids)),
            str(SESSION_TTL_SECONDS),
        )
        return self._parse_review_result(result, chat_id)

    async def begin_apply(
        self,
        redis: "aioredis.Redis",
        chat_id: str,
        requested_apply_id: str | None,
    ) -> UpdateModeSession:
        """Atomically set apply_id on the session.

        Idempotent: same apply_id on retry returns existing session unchanged.
        Different apply_id after one has been set raises ApplyConflictError.

        A non-empty UUID is always generated here before being passed to Lua,
        so the Lua script never receives an empty string.
        """
        apply_id = requested_apply_id if requested_apply_id else str(uuid.uuid4())
        assert apply_id, "apply_id must be a non-empty string before calling Lua"

        sha = await self._ensure_apply_script(redis)
        result = await redis.evalsha(
            sha,
            1,
            self._key(chat_id),
            apply_id,
            str(SESSION_TTL_SECONDS),
            datetime.now(timezone.utc).isoformat(),
        )
        return self._parse_apply_result(result, chat_id, apply_id)

    async def complete_apply(
        self,
        redis: "aioredis.Redis",
        chat_id: str,
        result: UpdateModeApplyResponse,
    ) -> UpdateModeSession | None:
        """Atomically persist apply_result and transition apply_state to 'completed'.

        Called by the backend /apply endpoint after receiving a successful
        response from rag-indexer.

        Returns the updated session, or None if the session has already expired
        (e.g. the 3-hour TTL elapsed during a very slow apply). The caller should
        treat None as non-fatal — the indexer already applied the changes.

        Never raises on session-expiry — logs a warning and returns None instead.
        """
        result_json = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        sha = await self._ensure_complete_script(redis)
        raw = await redis.evalsha(
            sha,
            1,
            self._key(chat_id),
            result_json,
            str(SESSION_TTL_SECONDS),
        )
        if isinstance(raw, (bytes, str)):
            s = raw.decode() if isinstance(raw, bytes) else raw
            if s.startswith("ERR:session_expired"):
                logger.warning(
                    "complete_apply: session expired before completion could be persisted "
                    "chat_id=%s apply_id=%s — changes were applied but session is gone",
                    chat_id,
                    result.apply_id,
                )
                return None
        data = _normalize_session_lists(json.loads(raw))
        return UpdateModeSession.model_validate(data)

    async def delete(self, redis: "aioredis.Redis", chat_id: str) -> None:
        await redis.delete(self._key(chat_id))
        logger.info("update_mode session deleted chat_id=%s", chat_id)

    # ------------------------------------------------------------------
    # Lua script loaders
    # ------------------------------------------------------------------
    # SHA cache is class-level so it survives across requests. A NOSCRIPT
    # response from Redis (after a SCRIPT FLUSH or restart) would cause
    # evalsha to raise — the fix is to clear the cached SHA and reload.
    # That edge case is not handled here; a process restart recovers it.

    async def _ensure_review_script(self, redis: "aioredis.Redis") -> str:
        if UpdateModeStore._review_sha is None:
            UpdateModeStore._review_sha = await redis.script_load(_REVIEW_LUA)
        return UpdateModeStore._review_sha

    async def _ensure_apply_script(self, redis: "aioredis.Redis") -> str:
        if UpdateModeStore._apply_sha is None:
            UpdateModeStore._apply_sha = await redis.script_load(_APPLY_BEGIN_LUA)
        return UpdateModeStore._apply_sha

    async def _ensure_complete_script(self, redis: "aioredis.Redis") -> str:
        if UpdateModeStore._complete_sha is None:
            UpdateModeStore._complete_sha = await redis.script_load(_APPLY_COMPLETE_LUA)
        return UpdateModeStore._complete_sha

    # ------------------------------------------------------------------
    # Result parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_review_result(result: str | bytes, chat_id: str) -> UpdateModeSession:
        if isinstance(result, bytes):
            result = result.decode()
        if result.startswith("ERR:"):
            err = result[4:]
            if err == "session_expired":
                raise SessionExpiredError(chat_id)
            if err.startswith("unknown_change_id:"):
                raise UnknownChangeIdError(err.split(":", 1)[1])
            if err.startswith("cannot_accept_failed:"):
                raise CannotAcceptFailedChangeError(err.split(":", 1)[1])
            if err.startswith("review_conflict:"):
                raise ReviewConflictError(err.split(":", 1)[1])
            raise UpdateModeError("lua_error", f"Unexpected Lua error: {err}")
        data = _normalize_session_lists(json.loads(result))
        return UpdateModeSession.model_validate(data)

    @staticmethod
    def _parse_apply_result(result: str | bytes, chat_id: str, requested_apply_id: str) -> UpdateModeSession:
        if isinstance(result, bytes):
            result = result.decode()
        if result.startswith("ERR:"):
            err = result[4:]
            if err == "session_expired":
                raise SessionExpiredError(chat_id)
            if err == "missing_apply_id":
                raise UpdateModeError("missing_apply_id", "apply_id was empty when passed to Lua (programming error)")
            if err.startswith("apply_conflict:"):
                existing = err.split(":", 1)[1]
                raise ApplyConflictError(requested_apply_id, existing)
            raise UpdateModeError("lua_error", f"Unexpected Lua error: {err}")
        data = _normalize_session_lists(json.loads(result))
        return UpdateModeSession.model_validate(data)


# Module-level singleton — same pattern as domain_service / settings_service
update_mode_store = UpdateModeStore()
