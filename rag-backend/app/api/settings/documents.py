from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.models import Document, DocumentLabel, Tag, Vault
from app.db.session import get_db
from shared_contracts.models import DocumentLabelWrite, DocumentRead, TagRead

logger = logging.getLogger(__name__)

try:
    from app.services.retrieval import delete_document_chunks
except ImportError:
    async def delete_document_chunks(document_id: str, vault_id: str) -> None:  # type: ignore[misc]
        logger.warning("delete_document_chunks not available; skipping chunk deletion for doc=%s", document_id)

router = APIRouter(prefix="/documents", tags=["documents"])


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    """Parse UUID string, raise HTTP 422 with a clear message on failure."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid UUID for {field_name}: '{value}'. Expected a UUID string like '550e8400-e29b-41d4-a716-446655440000'.",
        )


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    vault_id: str | None = None,
    domain_id: str | None = None,
    status: str | None = None,
    tag_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    """
    Возвращает документы.
    - Если передан domain_id — возвращает документы всех Vault этого домена.
    - Если передан vault_id — фильтрует по конкретному Vault (обратная совместимость).
    - Параметры status и tag_id работают в обоих режимах.
    """
    if domain_id:
        vaults_result = await db.execute(
            select(Vault.vault_id).where(Vault.domain_id == domain_id)
        )
        vault_ids = [row[0] for row in vaults_result.all()]
        if not vault_ids:
            return []
        stmt = select(Document).where(Document.vault_id.in_(vault_ids))
    elif vault_id:
        stmt = select(Document).where(Document.vault_id == vault_id)
    else:
        raise HTTPException(400, "Either domain_id or vault_id is required")

    if status:
        stmt = stmt.where(Document.status == status)
    if tag_id:
        tag_uuid = _parse_uuid(tag_id, "tag_id")
        stmt = stmt.join(DocumentLabel, DocumentLabel.document_id == Document.id).where(
            DocumentLabel.tag_id == tag_uuid
        )

    stmt = stmt.order_by(Document.created_at.desc())
    result = await db.execute(stmt)
    docs = result.scalars().all()
    return [await _doc_with_tags(d, db) for d in docs]


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)) -> DocumentRead:
    doc = await db.get(Document, _parse_uuid(document_id, "document_id"))
    if not doc:
        raise HTTPException(404, "Document not found")
    return await _doc_with_tags(doc, db)


@router.put("/{document_id}/labels", response_model=DocumentRead)
async def replace_document_labels(
    document_id: str,
    req: DocumentLabelWrite,
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    """Full replacement of document tags. Validates all tag_ids are valid UUIDs and belong to the same domain."""
    doc_uuid = _parse_uuid(document_id, "document_id")
    doc = await db.get(Document, doc_uuid)
    if not doc:
        raise HTTPException(404, "Document not found")

    # Validate each tag_id is a valid UUID before any DB work
    parsed_tag_ids: list[uuid.UUID] = []
    for raw in req.tag_ids:
        parsed_tag_ids.append(_parse_uuid(raw, f"tag_ids[{raw}]"))

    # Validate domain ownership of tags
    vault = await db.execute(select(Vault).where(Vault.vault_id == doc.vault_id))
    vault_obj = vault.scalar_one_or_none()
    doc_domain_id = vault_obj.domain_id if vault_obj else None

    if doc_domain_id and parsed_tag_ids:
        tags_result = await db.execute(
            select(Tag).where(Tag.id.in_(parsed_tag_ids))
        )
        tags = tags_result.scalars().all()
        # Check all requested tag IDs exist
        found_ids = {t.id for t in tags}
        missing = [str(tid) for tid in parsed_tag_ids if tid not in found_ids]
        if missing:
            raise HTTPException(404, f"Tags not found: {missing}")
        # Check domain ownership
        for tag in tags:
            if tag.domain_id != doc_domain_id:
                raise HTTPException(
                    400,
                    f"Tag '{tag.name}' (id={tag.id}) belongs to domain '{tag.domain_id}', "
                    f"but document belongs to domain '{doc_domain_id}'",
                )

    await db.execute(
        delete(DocumentLabel).where(DocumentLabel.document_id == doc_uuid)
    )
    for tag_uuid in parsed_tag_ids:
        db.add(DocumentLabel(
            document_id=doc_uuid,
            tag_id=tag_uuid,
        ))
    await db.commit()
    return await _doc_with_tags(doc, db)


@router.post("/labels/batch", status_code=204)
async def batch_label_documents(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Bulk labelling: add tags to multiple documents (does not replace existing). Skips duplicates."""
    document_ids: list[str] = payload.get("document_ids", [])
    tag_ids: list[str] = payload.get("tag_ids", [])
    for doc_id in document_ids:
        doc_uuid = _parse_uuid(doc_id, "document_ids")
        for tag_id in tag_ids:
            tag_uuid = _parse_uuid(tag_id, "tag_ids")
            db.add(DocumentLabel(
                document_id=doc_uuid,
                tag_id=tag_uuid,
            ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Re-insert one by one, skipping duplicates
        for doc_id in document_ids:
            doc_uuid = _parse_uuid(doc_id, "document_ids")
            for tag_id in tag_ids:
                tag_uuid = _parse_uuid(tag_id, "tag_ids")
                try:
                    db.add(DocumentLabel(document_id=doc_uuid, tag_id=tag_uuid))
                    await db.flush()
                except IntegrityError:
                    await db.rollback()
        await db.commit()


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Удаляет документ:
    1. Удаляет чанки из LanceDB (если vault_id доступен)
    2. Удаляет запись из PostgreSQL (CASCADE на document_labels)
    Физический файл НЕ удаляется.
    """
    doc = await db.get(Document, _parse_uuid(document_id, "document_id"))
    if not doc:
        raise HTTPException(404, "Document not found")

    if doc.vault_id:
        await delete_document_chunks(document_id, doc.vault_id)
    else:
        logger.warning("Document %s has no vault_id; skipping LanceDB chunk deletion", document_id)

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
