from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse

from app.config import AppConfig
from app.config_loader import get_config
from app.db.models import AuditLog, VaultBinding
from app.db.session import get_db
from shared_contracts.models import ChunkRecord, DocumentRecord, SearchHit


logger = logging.getLogger(__name__)

router = APIRouter(tags=["db-management"])

DB_API_URL = os.getenv("DB_API_URL", "http://db-api-server:8080")
INDEXER_API_URL = os.getenv("INDEXER_API_URL", "http://rag-indexer:9000")


class DocumentsResponse(BaseModel):
    documents: list[DocumentRecord]


class ChunksResponse(BaseModel):
    chunks: list[ChunkRecord]


class TextSearchRequest(BaseModel):
    vault_id: str
    query_text: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)


class TextSearchByDomainRequest(BaseModel):
    domain_id: str
    query_text: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)


class TextSearchResponse(BaseModel):
    results: list[SearchHit]


@router.get("/db/documents", response_model=DocumentsResponse)
async def list_documents(
    vault_id: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    order_by: str = Query(default="document_id"),
) -> DocumentsResponse:
    async with httpx.AsyncClient(base_url=DB_API_URL, timeout=20) as client:
        response = await client.get(
            "/index/documents",
            params={"vault_id": vault_id, "limit": limit, "offset": offset, "order_by": order_by},
        )
    _raise_upstream(response)
    return DocumentsResponse.model_validate(response.json())


@router.get("/db/docs/{document_id}/chunks", response_model=ChunksResponse)
async def get_document_chunks(
    document_id: str,
    vault_id: str = Query(..., min_length=1),
) -> ChunksResponse:
    async with httpx.AsyncClient(base_url=DB_API_URL, timeout=20) as client:
        response = await client.get(
            f"/index/document/{document_id}/chunks",
            params={"vault_id": vault_id},
        )
    _raise_upstream(response)
    return ChunksResponse.model_validate(response.json())


@router.post("/db/search/text", response_model=TextSearchResponse)
async def text_search(req: TextSearchRequest) -> TextSearchResponse:
    async with httpx.AsyncClient(base_url=DB_API_URL, timeout=30) as client:
        response = await client.post("/index/search/text", json=req.model_dump())
    _raise_upstream(response)
    return TextSearchResponse.model_validate(response.json())


@router.post("/db/search/text/by-domain", response_model=TextSearchResponse)
async def text_search_by_domain(
    req: TextSearchByDomainRequest,
    config: AppConfig = Depends(get_config),
) -> TextSearchResponse:
    """
    Текстовый поиск во всех enabled vault'ах домена.
    Запросы выполняются параллельно, результаты объединяются и обрезаются до limit.
    """
    vault_ids = [
        v.vault_id
        for v in config.vaults.values()
        if v.domain_id == req.domain_id and v.enabled
    ]
    
    if not vault_ids:
        return TextSearchResponse(results=[])
    
    async with httpx.AsyncClient(base_url=DB_API_URL, timeout=30) as client:
        async def _search(vault_id: str) -> list[SearchHit]:
            try:
                resp = await client.post(
                    "/index/search/text",
                    json={"vault_id": vault_id, "query_text": req.query_text, "limit": req.limit},
                )
                if not resp.is_success:
                    logger.warning("Text search failed for vault=%s: %s", vault_id, resp.status_code)
                    return []
                data = resp.json()
                return [SearchHit.model_validate(r) for r in data.get("results", [])]
            except Exception:
                logger.warning("Text search error for vault=%s", vault_id, exc_info=True)
                return []
        
        results_per_vault = await asyncio.gather(*[_search(vid) for vid in vault_ids])
    
    all_results: list[SearchHit] = []
    for hits in results_per_vault:
        all_results.extend(hits)
    
    # Сортируем по score (score здесь = 1.0 для точного совпадения, так что сохраняем порядок)
    all_results = all_results[: req.limit]
    return TextSearchResponse(results=all_results)


@router.delete("/db/docs/{document_id}")
async def delete_document(
    document_id: str,
    vault_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=DB_API_URL, timeout=20) as client:
        response = await client.delete(
            f"/index/document/{document_id}",
            params={"vault_id": vault_id},
        )
    _raise_upstream(response)
    payload = response.json()
    await _audit(db, "db.document.delete", "document", document_id, {"vault_id": vault_id, **payload})
    await db.commit()
    logger.info("Deleted document via DB management: vault_id=%s document_id=%s", vault_id, document_id)
    return payload


class ReindexRequest(BaseModel):
    force_reindex: bool = False


@router.post("/vaults/{vault_id}/reindex")
async def reindex_vault(vault_id: str, req: ReindexRequest | None = None) -> dict[str, Any]:
    # req=None не должно приводить к force=True: если тело не пришло,
    # всё равно используем инкрементальный режим (force_reindex=False).
    force = req.force_reindex if req is not None else False
    async with httpx.AsyncClient(base_url=INDEXER_API_URL, timeout=20) as client:
        response = await client.post("/api/v1/tasks", json={"vault_id": vault_id, "force_reindex": force})
    _raise_upstream(response)
    return response.json()


@router.post("/indexer/tasks/{task_id}/cancel")
async def cancel_indexer_task(task_id: str) -> dict[str, Any]:
    """Проксирует запрос отмены задачи к rag-indexer.
    Фронтенд обращается сюда вместо прямых запросов на localhost:9000 (избегаем CORS-ошибку)."""
    async with httpx.AsyncClient(base_url=INDEXER_API_URL, timeout=10) as client:
        response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
    _raise_upstream(response)
    return response.json()


@router.get("/indexer/tasks/{task_id}/state")
async def get_indexer_task_state(task_id: str) -> dict[str, Any]:
    """Проксирует запрос состояния задачи к rag-indexer."""
    async with httpx.AsyncClient(base_url=INDEXER_API_URL, timeout=10) as client:
        response = await client.get(f"/api/v1/tasks/{task_id}/state")
    _raise_upstream(response)
    return response.json()


@router.post("/vaults/{vault_id}/detach")
async def detach_vault(vault_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await db.execute(delete(VaultBinding).where(VaultBinding.vault_id == vault_id))
    async with httpx.AsyncClient(base_url=DB_API_URL, timeout=30) as client:
        response = await client.delete(f"/index/vault/{vault_id}")
    _raise_upstream(response)
    payload = response.json()
    await _audit(db, "vault.detach", "vault", vault_id, payload)
    await db.commit()
    logger.info("Detached vault: vault_id=%s deleted_count=%s", vault_id, payload.get("deleted_count"))
    return {"status": "ok", "vault_id": vault_id, "storage": payload}


@router.get("/db/ui", response_class=HTMLResponse)
async def db_management_ui(config: AppConfig = Depends(get_config)) -> HTMLResponse:
    if not config.ui.db_management_enabled:
        raise HTTPException(status_code=404, detail="DB management UI is disabled")
    return HTMLResponse(DB_MANAGEMENT_HTML)


async def _audit(
    db: AsyncSession,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(AuditLog(action=action, entity_type=entity_type, entity_id=entity_id, details=details or {}))


def _raise_upstream(response: httpx.Response) -> None:
    if response.is_success:
        return
    raise HTTPException(status_code=response.status_code, detail=response.text)


DB_MANAGEMENT_HTML = """<html><body><h1>DB Management (legacy)</h1></body></html>"""