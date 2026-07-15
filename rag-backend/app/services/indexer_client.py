"""indexer_client.py — async HTTP proxy to rag-indexer internal update mode API.

rag-backend delegates heavy filesystem/git work to rag-indexer.
This client is a thin typed wrapper; it does NOT retry — let FastAPI
HTTP exception propagate so the caller (update_mode.py router) can
return the correct HTTP status to the frontend.

Environment variables:
  INDEXER_API_URL  base URL of rag-indexer service, default "http://rag-indexer:8001"
  INDEXER_TIMEOUT  per-request timeout seconds, default 60
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from shared_contracts.models import (
    UpdateModeApplyRequest,
    UpdateModeApplyResponse,
    UpdateModeResolveRequest,
    UpdateModeResolveResponse,
)

logger = logging.getLogger(__name__)

_INDEXER_API_URL = os.getenv("INDEXER_API_URL", "http://rag-indexer:8001")
_INDEXER_TIMEOUT = float(os.getenv("INDEXER_TIMEOUT", "60"))


class IndexerUnavailableError(Exception):
    """rag-indexer returned a non-2xx response or network error."""

    def __init__(self, status_code: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class IndexerConflictError(Exception):
    """rag-indexer returned 409 (CAS conflict during apply)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class IndexerClient:
    """Async proxy to the rag-indexer internal update mode API.

    Uses a shared httpx.AsyncClient per-request (via async context manager)
    rather than a connection pool singleton to avoid stale connection issues
    in long-running FastAPI processes.  The overhead is negligible because
    rag-backend and rag-indexer are on the same Docker bridge network.
    """

    def __init__(
        self,
        base_url: str = _INDEXER_API_URL,
        timeout: float = _INDEXER_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def resolve(
        self,
        request: UpdateModeResolveRequest,
    ) -> UpdateModeResolveResponse:
        """POST /internal/update-mode/resolve

        Asks rag-indexer to look up documents, generate diffs, and return
        ResolvedUpdateModeChange objects.  May take several seconds if
        documents are large.

        Raises:
            IndexerUnavailableError: HTTP error or network failure.
        """
        url = f"{self._base_url}/internal/update-mode/resolve"
        payload = request.model_dump(mode="json")
        logger.info(
            "indexer_client.resolve chat_id=%s n_intents=%d url=%s",
            request.chat_id,
            len(request.intents),
            url,
        )
        data = await self._post(url, payload)
        return UpdateModeResolveResponse.model_validate(data)

    async def apply(
        self,
        request: UpdateModeApplyRequest,
    ) -> UpdateModeApplyResponse:
        """POST /internal/update-mode/apply

        Asks rag-indexer to write accepted changes to the vault filesystems
        and re-index.  Idempotent for the same apply_id.

        Raises:
            IndexerUnavailableError: HTTP error or network failure.
            IndexerConflictError: 409 — SHA mismatch / concurrent write.
        """
        url = f"{self._base_url}/internal/update-mode/apply"
        payload = request.model_dump(mode="json")
        logger.info(
            "indexer_client.apply apply_id=%s chat_id=%s n_changes=%d url=%s",
            request.apply_id,
            request.chat_id,
            len(request.accepted_changes),
            url,
        )
        data = await self._post(url, payload, allow_conflict=True)
        return UpdateModeApplyResponse.model_validate(data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        allow_conflict: bool = False,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TransportError as exc:
            raise IndexerUnavailableError(
                status_code=None,
                detail=f"Network error reaching rag-indexer: {exc}",
            ) from exc

        if response.status_code == 409 and allow_conflict:
            detail = self._extract_detail(response)
            raise IndexerConflictError(detail)

        if response.status_code >= 400:
            detail = self._extract_detail(response)
            logger.error(
                "indexer_client error status=%d url=%s detail=%s",
                response.status_code,
                url,
                detail,
            )
            raise IndexerUnavailableError(
                status_code=response.status_code,
                detail=detail,
            )

        return response.json()

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                return body.get("detail", str(body))
            return str(body)
        except Exception:
            return response.text[:512]


# Module-level singleton — same pattern as domain_service / settings_service
indexer_client = IndexerClient()
