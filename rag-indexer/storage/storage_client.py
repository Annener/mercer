from __future__ import annotations

import asyncio
import logging

import httpx

from shared_contracts.models import SearchRequest, SearchResponse, UpsertRequest, UpsertResponse
from storage.binding_manager import get_binding, lock_binding


logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class StorageClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def upsert_with_retry(self, req: UpsertRequest) -> UpsertResponse:
        response = await self._upsert(req)
        total_upserted = response.upserted_count
        pending_indices = list(response.failed_indices)
        error_details = list(response.error_details)

        for attempt in range(MAX_RETRIES):
            if response.status != "partial" or not pending_indices:
                break

            await asyncio.sleep(2**attempt)
            retry_request = UpsertRequest(
                vault_id=req.vault_id,
                chunks=[req.chunks[index] for index in pending_indices],
            )
            retry_response = await self._upsert(retry_request)
            total_upserted += retry_response.upserted_count

            if retry_response.status != "partial" or not retry_response.failed_indices:
                pending_indices = []
                error_details = []
                break

            pending_indices = [pending_indices[index] for index in retry_response.failed_indices]
            error_details = retry_response.error_details
            response = retry_response

        final_response = UpsertResponse(
            status="partial" if pending_indices else "ok",
            upserted_count=total_upserted,
            failed_indices=pending_indices,
            error_details=error_details if pending_indices else [],
        )

        if final_response.upserted_count > 0:
            await self._lock_binding_after_upsert(req.vault_id)

        return final_response

    async def _upsert(self, req: UpsertRequest) -> UpsertResponse:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/index/upsert", json=req.model_dump())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception("Storage upsert failed: status=%s body=%s", response.status_code, response.text)
            raise
        return UpsertResponse.model_validate(response.json())

    async def search(self, req: SearchRequest) -> SearchResponse:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/index/search", json=req.model_dump())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception("Storage search failed: status=%s body=%s", response.status_code, response.text)
            raise
        return SearchResponse.model_validate(response.json())

    async def _lock_binding_after_upsert(self, vault_id: str) -> None:
        binding = await get_binding(vault_id)
        if binding is None:
            logger.warning("Storage upsert succeeded, but no vault binding exists for vault_id=%s.", vault_id)
            return
        await lock_binding(vault_id)
