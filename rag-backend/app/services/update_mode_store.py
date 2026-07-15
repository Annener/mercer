"""update_mode_store.py — Redis-backed session store for Campaign Update Mode.

Key: update_mode:{chat_id}
TTL: 3 hours, renewed on start/review/apply_begin.

Atomicity:
  update_review and begin_apply use a Lua CAS script to avoid lost updates
  from concurrent PATCH requests. The script reads, mutates, and writes in
  a single server-side transaction — no WATCH/MULTI overhead per operation.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeChangeStatus,
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
# Lua script for atomic review update
# ---------------------------------------------------------------------------
# KEYS[1] = redis key
# ARGV[1] = json array of accepted change_ids
# ARGV[2] = json array of rejected change_ids
# ARGV[3] = new TTL seconds
# Returns: updated session JSON string, or error string prefixed with "ERR:"
_REVIEW_LUA = """
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

local updated = cjson.encode(session)
redis.call('SET', KEYS[1], updated, 'EX', ttl)
return updated
"""

# Lua script for atomic apply_begin
# KEYS[1] = redis key
# ARGV[1] = requested apply_id (may be empty string = generate)
# ARGV[2] = new TTL seconds
# ARGV[3] = apply_started_at ISO string
# Returns: updated session JSON, or "ERR:session_expired", or "ERR:apply_conflict:{existing}"
_APPLY_BEGIN_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 'ERR:session_expired'
end
local session = cjson.decode(raw)
local requested = ARGV[1]
local ttl = tonumber(ARGV[2])
local started_at = ARGV[3]

if session['apply_id'] and session['apply_id'] ~= cjson.null then
    -- Already has an apply_id
    if requested == '' or requested == session['apply_id'] then
        -- Same or no specific request — idempotent: return existing session
        return cjson.encode(session)
    else
        return 'ERR:apply_conflict:' .. session['apply_id']
    end
end

local new_id = requested
if new_id == '' then
    -- generate deterministic UUID-like id from timestamp+random is not possible in Lua;
    -- caller should always pass a pre-generated UUID; empty means use session_id+timestamp hash
    new_id = session['session_id'] .. '-apply'
end
session['apply_id'] = new_id
session['apply_started_at'] = started_at

local updated = cjson.encode(session)
redis.call('SET', KEYS[1], updated, 'EX', ttl)
return updated
"""


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
        return UpdateModeSession.model_validate(json.loads(raw))

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
        """
        apply_id = requested_apply_id or str(uuid.uuid4())
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

    async def delete(self, redis: "aioredis.Redis", chat_id: str) -> None:
        await redis.delete(self._key(chat_id))
        logger.info("update_mode session deleted chat_id=%s", chat_id)

    # ------------------------------------------------------------------
    # Lua helpers
    # ------------------------------------------------------------------

    async def _ensure_review_script(self, redis: "aioredis.Redis") -> str:
        if UpdateModeStore._review_sha is None:
            UpdateModeStore._review_sha = await redis.script_load(_REVIEW_LUA)
        return UpdateModeStore._review_sha

    async def _ensure_apply_script(self, redis: "aioredis.Redis") -> str:
        if UpdateModeStore._apply_sha is None:
            UpdateModeStore._apply_sha = await redis.script_load(_APPLY_BEGIN_LUA)
        return UpdateModeStore._apply_sha

    # ------------------------------------------------------------------
    # Result parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_review_result(result: str, chat_id: str) -> UpdateModeSession:
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
        return UpdateModeSession.model_validate(json.loads(result))

    @staticmethod
    def _parse_apply_result(result: str, chat_id: str, requested_apply_id: str) -> UpdateModeSession:
        if result.startswith("ERR:"):
            err = result[4:]
            if err == "session_expired":
                raise SessionExpiredError(chat_id)
            if err.startswith("apply_conflict:"):
                existing = err.split(":", 1)[1]
                raise ApplyConflictError(requested_apply_id, existing)
            raise UpdateModeError("lua_error", f"Unexpected Lua error: {err}")
        return UpdateModeSession.model_validate(json.loads(result))


# Module-level singleton — same pattern as domain_service / settings_service
update_mode_store = UpdateModeStore()
