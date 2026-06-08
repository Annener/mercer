from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse

from app.db.models import AuditLog, Document, Vault
from app.db.session import get_db
from shared_contracts.models import ChunkRecord, DocumentRecord, SearchHit

# Попытка импорта websockets для прокси
try:
    from websockets import connect
    from websockets.exceptions import ConnectionClosed
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    import warnings
    warnings.warn("websockets library not installed. WebSocket proxy will not work. Run: pip install websockets")

logger = logging.getLogger(__name__)

router = APIRouter(tags=["db-management"])

STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")
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


# === DB Management API ===
# Согласно спецификации V3.0: /api/db/*

@router.get("/api/db/documents", response_model=DocumentsResponse)
async def list_documents(
    vault_id: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    order_by: str = Query(default="document_id"),
) -> DocumentsResponse:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=20) as client:
        response = await client.get(
            "/index/documents",
            params={"vault_id": vault_id, "limit": limit, "offset": offset, "order_by": order_by},
        )
        _raise_upstream(response)
        return DocumentsResponse.model_validate(response.json())


@router.get("/api/db/chunks", response_model=ChunksResponse)
async def get_document_chunks(
    document_id: str = Query(..., min_length=1),
    vault_id: str = Query(..., min_length=1),
) -> ChunksResponse:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=20) as client:
        response = await client.get(
            f"/index/document/{document_id}/chunks",
            params={"vault_id": vault_id},
        )
        _raise_upstream(response)
        return ChunksResponse.model_validate(response.json())


@router.post("/api/db/search/text", response_model=TextSearchResponse)
async def text_search(req: TextSearchRequest) -> TextSearchResponse:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=30) as client:
        response = await client.post("/index/search/text", json=req.model_dump())
        _raise_upstream(response)
        return TextSearchResponse.model_validate(response.json())


@router.post("/api/db/search/domain", response_model=TextSearchResponse)
async def text_search_by_domain(
    req: TextSearchByDomainRequest,
    db: AsyncSession = Depends(get_db),
) -> TextSearchResponse:
    """
    Текстовый поиск во всех enabled vault'ах домена.
    Запросы выполняются параллельно, результаты объединяются и обрезаются до limit.
    """
    result = await db.execute(select(Vault.vault_id).where(Vault.domain_id == req.domain_id, Vault.enabled == True))
    vault_ids = list(result.scalars().all())
    if not vault_ids:
        return TextSearchResponse(results=[])

    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=30) as client:
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

    all_results = all_results[:req.limit]
    return TextSearchResponse(results=all_results)


@router.delete("/api/db/documents/{document_id}")
async def delete_document(
    document_id: str,
    vault_id: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # 1. Удаляем документ в storage (db-api-server / LanceDB)
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=20) as client:
        response = await client.delete(
            f"/index/document/{document_id}",
            params={"vault_id": vault_id},
        )
        _raise_upstream(response)
        payload = response.json()

    # 2. Синхронизируем таблицу documents в Postgres — удаляем запись по (id, vault_id).
    #    Если запись отсутствует — DELETE молча ничего не делает (идемпотентно).
    #    Если document_id не является валидным UUID — логируем предупреждение и пропускаем.
    try:
        doc_uuid = uuid.UUID(document_id)
        await db.execute(
            delete(Document).where(
                Document.id == doc_uuid,
                Document.vault_id == vault_id,
            )
        )
    except ValueError:
        logger.warning("delete_document: invalid UUID, skipping Postgres delete: document_id=%s", document_id)
    except Exception:
        logger.warning("delete_document: failed to delete from documents table: document_id=%s vault_id=%s", document_id, vault_id, exc_info=True)

    # 3. Пересчитываем chunk_count vault'а по актуальным данным из storage
    try:
        docs_response = await _fetch_documents_for_vault(vault_id)
        new_total = sum(int(doc.get("chunk_count", 0)) for doc in docs_response)
        # B02 fix: Vault.id — UUID (internal PK), vault_id — строковый slug.
        # db.get(Vault, vault_id) передавал slug как UUID → DataError.
        # Используем select по Vault.vault_id.
        vault = await _get_vault_by_slug(db, vault_id)
        if vault is not None:
            vault.chunk_count = new_total
    except Exception:
        logger.warning("Failed to recalculate vault chunk_count after document delete: vault_id=%s", vault_id, exc_info=True)

    await _audit(db, "db.document.delete", "document", document_id, {"vault_id": vault_id, **payload})
    await db.commit()
    logger.info("Deleted document via DB management: vault_id=%s document_id=%s", vault_id, document_id)
    return payload


# === Vault Reindex ===

class ReindexRequest(BaseModel):
    force_reindex: bool = False


@router.post("/vaults/{vault_id}/reindex")
async def reindex_vault(vault_id: str, req: ReindexRequest | None = None) -> dict[str, Any]:
    force = req.force_reindex if req is not None else False
    async with httpx.AsyncClient(base_url=INDEXER_API_URL, timeout=20) as client:
        response = await client.post("/api/v1/tasks", json={"vault_id": vault_id, "force_reindex": force})
        _raise_upstream(response)
        return response.json()


# === Index Tasks API ===
# Согласно спецификации V3.0: /index-tasks/* (не /indexer/tasks/*.）

@router.delete("/index-tasks/{task_id}")
async def cancel_index_task(task_id: str) -> dict[str, Any]:
    """Отмена задачи индексации. Проксирует запрос к rag-indexer."""
    async with httpx.AsyncClient(base_url=INDEXER_API_URL, timeout=10) as client:
        response = await client.post(f"/api/v1/tasks/{task_id}/cancel")
        _raise_upstream(response)
        return response.json()


@router.get("/index-tasks/{task_id}/state")
async def get_index_task_state(task_id: str) -> dict[str, Any]:
    """Получить состояние задачи индексации. Проксирует запрос к rag-indexer."""
    async with httpx.AsyncClient(base_url=INDEXER_API_URL, timeout=10) as client:
        response = await client.get(f"/api/v1/tasks/{task_id}/state")
        _raise_upstream(response)
        return response.json()


# === Vault Detach ===

@router.post("/vaults/{vault_id}/detach")
async def detach_vault(vault_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=30) as client:
        response = await client.delete(f"/index/vault/{vault_id}")
        _raise_upstream(response)
        payload = response.json()

    # B02 fix: та же проблема — db.get(Vault, vault_id) падает на строковом slug.
    vault = await _get_vault_by_slug(db, vault_id)
    if vault is not None:
        vault.binding_status = "unbound"
        vault.chunk_count = 0

    await _audit(db, "vault.detach", "vault", vault_id, payload)
    await db.commit()
    logger.info("Detached vault: vault_id=%s deleted_count=%s", vault_id, payload.get("deleted_count"))
    return {"status": "ok", "vault_id": vault_id, "storage": payload}


# === WebSocket Proxy для прогресса индексации ===
# Согласно спецификации V3.0: /ws/index-tasks/{task_id} (не /ws/indexer/tasks/.../stream)

@router.websocket("/ws/index-tasks/{task_id}")
async def websocket_index_task_proxy(websocket: WebSocket, task_id: str):
    """
    Проксирует WebSocket поток от rag-indexer к клиенту.
    Клиент подключается к этому эндпоинту вместо прямого соединения с indexer.
    """
    await websocket.accept()
    
    if not WEBSOCKETS_AVAILABLE:
        await websocket.send_text('{"error": "WebSocket proxy not available (websockets library missing)"}')
        await websocket.close()
        return

    indexer_ws_url = f"ws://rag-indexer:9000/api/v1/tasks/{task_id}/stream"
    
    try:
        async with connect(indexer_ws_url) as indexer_ws:
            while True:
                message = await indexer_ws.recv()
                await websocket.send_text(message)
    except ConnectionClosed:
        logger.info("WebSocket connection closed for task %s", task_id)
    except Exception as e:
        logger.error("WebSocket proxy error for task %s: %s", task_id, e, exc_info=True)
        try:
            await websocket.send_text(f'{{"error": "{str(e)}"}}')
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass


# === Вспомогательные функции ===

async def _get_vault_by_slug(db: AsyncSession, vault_id: str) -> Vault | None:
    """Lookup vault by string slug (vault_id), not by internal UUID PK (id)."""
    result = await db.execute(select(Vault).where(Vault.vault_id == vault_id))
    return result.scalar_one_or_none()


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


async def _fetch_documents_for_vault(vault_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=20) as client:
        response = await client.get("/index/documents", params={"vault_id": vault_id})
        _raise_upstream(response)
        payload = response.json()
        documents = payload.get("documents", payload)
        return documents if isinstance(documents, list) else []


# === Legacy UI (для обратной совместимости) ===

@router.get("/db/ui", response_class=HTMLResponse)
async def db_management_ui() -> HTMLResponse:
    return HTMLResponse(DB_MANAGEMENT_HTML)


DB_MANAGEMENT_HTML = """
<html>
<body>
<h1>DB Management (legacy)</h1>
</body>
</html>
"""
