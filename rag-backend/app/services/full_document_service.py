"""Full Document Service — Stage 3.

Три публичных функции:
  collect_document_candidates()  — собирает кандидатов из хитов, помечает already_sent
  reconstruct_full_text()        — запрашивает чанки документа из db-api-server, собирает полный текст
  assemble_hybrid_context()      — собирает гибридный контекст: полные тексты + остаточные чанки

Не изменяет существующую логику pipeline/retrieval — только читает и агрегирует.

Сторадж-endpoint для чанков:
    GET {db_api_url}/index/document/{document_id}/chunks?vault_id={vault_id}
    → ChunksResponse: {"chunks": [{chunk_id, document_id, vault_id, text, metadata, ...}]}
    чанки уже сортированы по metadata.chunk_index на стороне lancedb_store.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from shared_contracts.models import DocumentCandidate, SearchHit

logger = logging.getLogger(__name__)

# Максимальный размер документа, который можно добавить целиком (в токенах).
FULL_DOC_TOKEN_LIMIT = 32_000


# ---------------------------------------------------------------------------
# collect_document_candidates
# ---------------------------------------------------------------------------

async def collect_document_candidates(
    hits: list[SearchHit],
    sent_full_document_ids: list[str],
    db: AsyncSession,
) -> list[DocumentCandidate]:
    """Собирает уникальных кандидатов на полную отправку из поисковых хитов.

    Алгоритм:
    1. Дедуплицировать document_id из хитов, сохраняя порядок (по убыванию score).
    2. Загрузить Document-записи из БД одним IN-запросом.
    3. Отфильтровать документы без size-метаданных (char_count IS NULL).
    4. Отфильтровать документы, превышающие FULL_DOC_TOKEN_LIMIT.
    5. Пометить already_sent.

    Возвращает список DocumentCandidate, отсортированный по порядку появления в хитах.
    """
    if not hits:
        return []

    # 1. Уникальные document_id в порядке первого появления
    seen: set[str] = set()
    ordered_doc_ids: list[str] = []
    for hit in hits:
        if hit.document_id not in seen:
            seen.add(hit.document_id)
            ordered_doc_ids.append(hit.document_id)

    # 2. Загрузить Document-записи из БД
    import uuid as _uuid
    try:
        uuids = [_uuid.UUID(did) for did in ordered_doc_ids]
    except ValueError as exc:
        logger.warning("collect_document_candidates: invalid uuid in hits: %s", exc)
        return []

    result = await db.execute(
        select(Document).where(Document.id.in_(uuids))
    )
    docs_by_id: dict[str, Document] = {
        str(row.id): row for row in result.scalars().all()
    }

    sent_set = set(sent_full_document_ids)
    candidates: list[DocumentCandidate] = []

    for doc_id in ordered_doc_ids:
        doc = docs_by_id.get(doc_id)
        if doc is None:
            logger.debug("collect_document_candidates: doc %s not found in DB", doc_id)
            continue
        # 3. Пропустить без size-метаданных
        if doc.char_count is None or doc.estimated_tokens is None:
            logger.debug(
                "collect_document_candidates: doc %s has no size metadata — skipping",
                doc_id,
            )
            continue
        # 4. Пропустить слишком большие документы
        if doc.estimated_tokens > FULL_DOC_TOKEN_LIMIT:
            logger.info(
                "collect_document_candidates: doc %s too large (%d tokens > %d limit) — skipping",
                doc_id, doc.estimated_tokens, FULL_DOC_TOKEN_LIMIT,
            )
            continue
        # 5. Пометить already_sent
        candidates.append(DocumentCandidate(
            document_id=doc_id,
            title=doc.title or doc.source_path,
            source_path=doc.source_path,
            char_count=doc.char_count,
            chunk_count=doc.chunk_count,
            estimated_tokens=doc.estimated_tokens,
            already_sent=doc_id in sent_set,
        ))

    return candidates


# ---------------------------------------------------------------------------
# reconstruct_full_text
# ---------------------------------------------------------------------------

async def reconstruct_full_text(
    document_id: str,
    vault_id: str,
    db_api_url: str,
) -> str | None:
    """Собирает полный текст документа из db-api-server через /index/document/{id}/chunks.

    Реальный endpoint:
        GET {db_api_url}/index/document/{document_id}/chunks?vault_id={vault_id}
        → {"chunks": [{chunk_id, document_id, vault_id, text, metadata: {chunk_index: N}, ...}]}

    Чанки уже сортированы по chunk_index на стороне lancedb_store — сортировка здесь for safety.

    Возвращает строку с текстом или None при ошибке.
    """
    url = f"{db_api_url.rstrip('/')}/index/document/{document_id}/chunks"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, params={"vault_id": vault_id})
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            chunks: list[dict[str, Any]] = data.get("chunks", [])
            if not chunks:
                logger.warning(
                    "reconstruct_full_text: no chunks for doc=%s vault=%s",
                    document_id, vault_id,
                )
                return None
            # Сортировка for safety: lancedb_store уже сортирует, но защищаемся
            chunks.sort(key=lambda c: int((c.get("metadata") or {}).get("chunk_index", 0)))
            text = "\n".join(c.get("text", "") for c in chunks)
            if not text.strip():
                logger.warning(
                    "reconstruct_full_text: empty text after join for doc=%s vault=%s",
                    document_id, vault_id,
                )
                return None
            return text
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "reconstruct_full_text: HTTP %d for doc=%s vault=%s: %s",
            exc.response.status_code, document_id, vault_id, exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "reconstruct_full_text: error for doc=%s vault=%s: %s",
            document_id, vault_id, exc,
        )
        return None


# ---------------------------------------------------------------------------
# assemble_hybrid_context
# ---------------------------------------------------------------------------

def assemble_hybrid_context(
    selected_doc_ids: list[str],
    full_texts: dict[str, str],
    hits: list[SearchHit],
    candidates: list[DocumentCandidate],
) -> str:
    """Собирает гибридный контекст из полных текстов и остаточных чанков.

    Логика:
    - Для документов из selected_doc_ids, у которых есть full_text — добавляет полный текст.
    - Для остальных хитов (из документов, не выбранных для полной отправки) — добавляет
      чанк как обычно (как в format_context_with_role).
    - Дубли чанков из selected-документов не добавляются.

    Формат секции полного документа:
        [FULL DOCUMENT: {title}]\n{text}\n[END DOCUMENT]

    Формат секции чанков (остаточные):
        [CHUNK from {title}]\n{text}
    """
    selected_set = set(selected_doc_ids)
    candidates_by_id: dict[str, DocumentCandidate] = {
        c.document_id: c for c in candidates
    }

    parts: list[str] = []

    # 1. Полные тексты выбранных документов
    for doc_id in selected_doc_ids:
        text = full_texts.get(doc_id)
        if not text:
            logger.warning(
                "assemble_hybrid_context: no full text for selected doc=%s, will use chunks",
                doc_id,
            )
            continue
        candidate = candidates_by_id.get(doc_id)
        title = candidate.title if candidate else doc_id
        parts.append(f"[FULL DOCUMENT: {title}]\n{text}\n[END DOCUMENT]")

    # 2. Остаточные чанки из НЕвыбранных документов
    seen_chunks: set[str] = set()
    for hit in hits:
        if hit.document_id in selected_set:
            continue  # чанки этого документа не нужны — уже есть полный текст
        if hit.chunk_id in seen_chunks:
            continue
        seen_chunks.add(hit.chunk_id)
        candidate = candidates_by_id.get(hit.document_id)
        source = candidate.title if candidate else hit.metadata.get("source_path", hit.document_id)
        parts.append(f"[CHUNK from {source}]\n{hit.text}")

    return "\n\n".join(parts)
