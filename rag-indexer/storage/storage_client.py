from __future__ import annotations

import asyncio
import logging

import httpx

from shared_contracts.models import SearchRequest, SearchResponse, UpsertRequest, UpsertResponse


logger = logging.getLogger(__name__)

MAX_RETRIES = 3


# Таймаут для upsert — увеличен, т.к. большой PDF (1000+ чанков с Qwen3-4B embedding)
# может занимать 30-40 минут embedding + запись в LanceDB.
# Используем httpx.Timeout с раздельными настройками: connect и read отдельно.
_UPSERT_TIMEOUT = httpx.Timeout(connect=10.0, read=3600.0, write=300.0, pool=10.0)
_SEARCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


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

        return final_response

    async def _upsert(self, req: UpsertRequest) -> UpsertResponse:
        # Используем раздельный timeout: connect короткий, read длинный (embedding тяжёлые)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=_UPSERT_TIMEOUT) as client:
            response = await client.post("/index/upsert", json=req.model_dump())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception("Storage upsert failed: status=%s body=%s", response.status_code, response.text)
            raise
        return UpsertResponse.model_validate(response.json())

    async def search(self, req: SearchRequest) -> SearchResponse:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=_SEARCH_TIMEOUT) as client:
            response = await client.post("/index/search", json=req.model_dump())
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception("Storage search failed: status=%s body=%s", response.status_code, response.text)
            raise
        return SearchResponse.model_validate(response.json())

    async def delete_document(self, document_id: str, vault_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=_SEARCH_TIMEOUT) as client:
            response = await client.delete(f"/index/document/{document_id}", params={"vault_id": vault_id})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception("Storage document delete failed: status=%s body=%s", response.status_code, response.text)
            raise
        return response.json()
