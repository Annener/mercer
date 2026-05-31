from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentLabel, Tag
from app.db.session import get_db
from app.services.retrieval import delete_document_chunks
from shared_contracts.models import DocumentLabelWrite, DocumentRead, TagRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    vault_id: str,
    status: str | None = None,
    tag_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    stmt = select(Document).where(Document.vault_id == vault_id)
    if status:
        stmt = stmt.where(Document.status == status)
    if tag_id:
        stmt = stmt.join(DocumentLabel, DocumentLabel.document_id == Document.id).where(
            DocumentLabel.tag_id == uuid.UUID(tag_id)
        )
    result = await db.execute(stmt)
    docs = result.scalars().all()
    return [await _doc_with_tags(d, db) for d in docs]


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)) -> DocumentRead:
    doc = await db.get(Document, uuid.UUID(document_id))
    if not doc:
        raise HTTPException(404, "Document not found")
    return await _doc_with_tags(doc, db)


@router.put("/{document_id}/labels", response_model=DocumentRead)
async def replace_document_labels(
    document_id: str,
    req: DocumentLabelWrite,
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    """Полная замена тегов документа."""
    doc = await db.get(Document, uuid.UUID(document_id))
    if not doc:
        raise HTTPException(404, "Document not found")

    await db.execute(
        delete(DocumentLabel).where(DocumentLabel.document_id == uuid.UUID(document_id))
    )
    for tag_id in req.tag_ids:
        db.add(DocumentLabel(
            document_id=uuid.UUID(document_id),
            tag_id=uuid.UUID(tag_id),
        ))
    await db.commit()
    return await _doc_with_tags(doc, db)


@router.post("/labels/batch", status_code=204)
async def batch_label_documents(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Массовая разметка: добавить теги к нескольким документам (не заменяет существующие)."""
    document_ids: list[str] = payload.get("document_ids", [])
    tag_ids: list[str] = payload.get("tag_ids", [])
    for doc_id in document_ids:
        for tag_id in tag_ids:
            db.add(DocumentLabel(
                document_id=uuid.UUID(doc_id),
                tag_id=uuid.UUID(tag_id),
            ))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Удаляет документ:
    1. Удаляет чанки из LanceDB
    2. Удаляет запись из PostgreSQL (CASCADE на document_labels)
    Физический файл НЕ удаляется.
    """
    doc = await db.get(Document, uuid.UUID(document_id))
    if not doc:
        raise HTTPException(404, "Document not found")

    await delete_document_chunks(document_id, doc.vault_id)
    await db.delete(doc)
    await db.commit()


async def _doc_with_tags(doc: Document, db: AsyncSession) -> DocumentRead:
    stmt = (
        select(Tag)
        .join(DocumentLabel, DocumentLabel.tag_id == Tag.id)
        .where(DocumentLabel.document_id == doc.id)
    )
    result = await db.execute(stmt)
    tags = [TagRead.model_validate(t, from_attributes=True) for t in result.scalars().all()]
    data = DocumentRead.model_validate(doc, from_attributes=True)
    data.tags = tags
    return data
