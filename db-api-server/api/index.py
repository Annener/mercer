from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from shared_contracts.models import ChunkRecord, DocumentRecord, SearchHit, SearchRequest, SearchResponse, UpsertRequest, UpsertResponse
from storage.lancedb_store import LanceDBStore


router = APIRouter(prefix="/index", tags=["index"])


class TextSearchRequest(BaseModel):
    vault_id: str
    query_text: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=200)


class TextSearchResponse(BaseModel):
    results: list[SearchHit]


class DocumentsResponse(BaseModel):
    documents: list[DocumentRecord]


class ChunksResponse(BaseModel):
    chunks: list[ChunkRecord]


@router.post("/upsert", response_model=UpsertResponse)
async def upsert_index(req: UpsertRequest, request: Request) -> UpsertResponse:
    try:
        return _store(request).upsert(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/search", response_model=SearchResponse)
async def search_index(req: SearchRequest, request: Request) -> SearchResponse:
    try:
        return _store(request).search(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/document/{document_id}")
async def delete_document(
    document_id: str,
    request: Request,
    vault_id: str = Query(..., min_length=1),
) -> dict[str, int | str]:
    deleted_count = _store(request).delete_document(vault_id=vault_id, document_id=document_id)
    return {"status": "ok", "deleted_count": deleted_count}


@router.get("/documents", response_model=DocumentsResponse)
async def list_documents(
    request: Request,
    vault_id: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    order_by: str = Query(default="document_id"),
) -> DocumentsResponse:
    documents = _store(request).list_documents(vault_id=vault_id, limit=limit, offset=offset, order_by=order_by)
    return DocumentsResponse(documents=documents)


@router.get("/document/{document_id}/chunks", response_model=ChunksResponse)
async def get_document_chunks(
    document_id: str,
    request: Request,
    vault_id: str = Query(..., min_length=1),
) -> ChunksResponse:
    return ChunksResponse(chunks=_store(request).get_document_chunks(vault_id=vault_id, document_id=document_id))


@router.post("/search/text", response_model=TextSearchResponse)
async def text_search(req: TextSearchRequest, request: Request) -> TextSearchResponse:
    return TextSearchResponse(results=_store(request).text_search(req.vault_id, req.query_text, req.limit))


@router.delete("/vault/{vault_id}")
async def delete_vault(vault_id: str, request: Request) -> dict[str, int | str]:
    deleted_count = _store(request).delete_vault(vault_id)
    return {"status": "ok", "deleted_count": deleted_count}


def _store(request: Request) -> LanceDBStore:
    store = getattr(request.app.state, "store", None)
    if not isinstance(store, LanceDBStore):
        raise HTTPException(status_code=503, detail="LanceDB store is not initialized.")
    return store
