from __future__ import annotations
import asyncio
import logging
import json
import os
import uuid
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import AppConfig, EmbeddingModelConfig
from app.services.settings_service import settings_service
from app.db.models import Tag, Document, DocumentLabel, Vault
from shared_contracts.models import SearchHit, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")


async def delete_document_chunks(document_id: str, vault_id: str) -> None:
    """
    Удаляет чанки документа из LanceDB через storage API.
    Физический файл НЕ удаляется.
    """
    try:
        async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=15) as client:
            response = await client.delete(
                f"/index/documents/{document_id}",
                params={"vault_id": vault_id},
            )
            if response.status_code not in (200, 204, 404):
                response.raise_for_status()
    except Exception:
        logger.warning(
            "Failed to delete chunks for document_id=%s vault_id=%s",
            document_id, vault_id,
            exc_info=True,
        )


async def get_allowed_tag_ids(
    domain_id: str,
    campaign_id: str | None,
    db: AsyncSession,
) -> set[str]:
    """
    Возвращает множество tag_id доступных в данном контексте.

    Теги принадлежат домену (не Vault):
    - campaign_id задан → теги этой кампании + глобальные теги домена (campaign_id IS NULL)
    - campaign_id = None → только глобальные теги домена

    Инвариант: пустое множество = кампания существует, но тегов нет →
    вызывающий код должен вернуть document_ids=[] (не None), т.е. не расширяться на весь домен.
    """
    if campaign_id:
        stmt = select(Tag.id).where(
            Tag.domain_id == domain_id,
            or_(
                Tag.campaign_id.is_(None),
                Tag.campaign_id == uuid.UUID(campaign_id),
            )
        )
    else:
        stmt = select(Tag.id).where(
            Tag.domain_id == domain_id,
            Tag.campaign_id.is_(None),
        )
    result = await db.execute(stmt)
    return {str(row) for row in result.scalars().all()}


async def get_document_ids_by_tags(
    tag_ids: list[str],
    domain_id: str,
    db: AsyncSession,
) -> list[str]:
    """
    OR-логика: документ попадает если имеет хотя бы один из тегов.
    Только документы со status='indexed'.
    Документы ищутся через Vault.domain_id — т.е. по всем Vault'ам домена.
    Если tag_ids пустой → вернуть [] без запроса к БД.
    """
    if not tag_ids:
        return []
    stmt = (
        select(Document.id)
        .join(DocumentLabel, DocumentLabel.document_id == Document.id)
        .join(Vault, Vault.vault_id == Document.vault_id)
        .where(
            Vault.domain_id == domain_id,
            Vault.enabled == True,
            Document.status == "indexed",
            DocumentLabel.tag_id.in_([uuid.UUID(t) for t in tag_ids]),
        )
        .distinct()
    )
    result = await db.execute(stmt)
    return [str(row) for row in result.scalars().all()]


async def retrieve(
    query: str,
    vault_id: str | None,
    *,
    document_ids: list[str] | None = None,
    top_k: int | None = None,
    strategy: str = "semantic",
    config: AppConfig | None = None,
    db: AsyncSession | None = None,
) -> list[SearchHit]:
    """
    document_ids = None  → поиск по всему vault без фильтра
    document_ids = []    → вернуть [] сразу, без запроса к LanceDB
    document_ids = [...] → поиск с фильтром {"document_id": {"$in": document_ids}}

    config=None + db → embedding-модель берётся из БД через settings_service.
    config=None + db=None → падает ValueError.
    """
    if document_ids is not None and len(document_ids) == 0:
        return []

    logger.info(
        "RETRIEVE query='%s' vault_id=%s top_k=%s doc_ids=%s",
        query, vault_id, top_k, document_ids,
    )
    if not vault_id or strategy == "none":
        logger.warning(
            "Retrieval skipped: vault_id=%s strategy=%s",
            vault_id, strategy
        )
        return []
    effective_top_k = top_k or await _default_top_k()
    if strategy != "semantic":
        logger.info("Retrieval strategy is not implemented yet: %s", strategy)
        return []
    try:
        embedding_model = await _resolve_embedding_model(config, db)
        vector = await _embed_query(query, embedding_model)

        filter_expr: dict[str, Any] | None = None
        if document_ids is not None:
            filter_expr = {"document_id": {"$in": document_ids}}
            search_top_k = effective_top_k * 10
        else:
            search_top_k = effective_top_k

        async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=15) as client:
            response = await client.post(
                "/index/search",
                json=SearchRequest(
                    vault_id=vault_id,
                    vector=vector,
                    top_k=search_top_k,
                    filter=filter_expr,
                ).model_dump(),
            )
            response.raise_for_status()
        search_response = SearchResponse.model_validate(response.json())

        results = search_response.results
        if document_ids is not None:
            doc_set = set(document_ids)
            results = [
                h for h in results
                if h.document_id in doc_set
                or (h.metadata or {}).get("document_id") in doc_set
            ]
        results = results[:effective_top_k]

        logger.info(
            "RETRIEVE DONE vault='%s' hits=%d top_scores=[%s] top_docs=[%s]",
            vault_id,
            len(results),
            ", ".join(f"{h.score:.3f}" for h in results[:3]),
            ", ".join(
                (h.metadata.get("source_path") or h.document_id or "?").split("/")[-1]
                for h in results[:3]
            ),
        )
        return results
    except Exception:
        logger.warning("Retrieval failed; continuing without context: vault_id=%s", vault_id, exc_info=True)
        return []


async def retrieve_multi_vault(
    query: str,
    vault_ids: list[str],
    *,
    document_ids: list[str] | None = None,
    top_k: int | None = None,
    strategy: str = "semantic",
    config: AppConfig | None = None,
    db: AsyncSession | None = None,
) -> list[SearchHit]:
    """Ищет во всех указанных vault'ах, объединяет результаты, сортирует по score, возвращает top_k.

    config=None + db → embedding-модель берётся из БД через settings_service.
    """
    if not vault_ids:
        return []
    # Инвариант: пустой document_ids = нет документов → не запускать retrieve
    if isinstance(document_ids, list) and len(document_ids) == 0:
        return []
    logger.info(
        "RETRIEVE_MULTI query='%s' vaults=%s top_k=%s",
        query, vault_ids, top_k
    )
    effective_top_k = top_k or await _default_top_k()

    # Раз решаем embedding-модель, чтобы не делать н-запросов к БД
    resolved_config = config
    if resolved_config is None and db is not None:
        emb_model = await settings_service.get_active_embedding_config(db)
        if emb_model is not None:
            # Пакуем как AppConfig с одной embedding-моделью
            from app.config import AppConfig
            resolved_config = AppConfig(
                embedding_models={emb_model.model_id: emb_model},
                generation_models={},
            )

    all_hits: list[SearchHit] = []
    for vault_id in vault_ids:
        hits = await retrieve(
            query,
            vault_id,
            document_ids=document_ids,
            top_k=effective_top_k,
            strategy=strategy,
            config=resolved_config,
            db=db,
        )
        all_hits.extend(hits)
    all_hits.sort(key=lambda h: h.score, reverse=True)
    result = all_hits[:effective_top_k]
    logger.info(
        "RETRIEVE_MULTI DONE query='%s' total_hits=%d after_merge=%d",
        query, len(all_hits), len(result)
    )
    return result


def format_context(hits: list[SearchHit]) -> str:
    """
    Формирует блок контекста для LLM.
    Нумерация блоков [1], [2], ... строго соответствует нумерации карточек источников
    на фронтенде.
    """
    if not hits:
        return "Контекст не найден в базе знаний. Отвечай на основе общих знаний, но явно укажи что локальные данные не найдены."

    source_index: dict[str, int] = {}
    numbered: list[tuple[int, SearchHit]] = []

    for hit in hits:
        path = hit.metadata.get("source_path") or hit.document_id or "unknown"
        if path not in source_index:
            source_index[path] = len(source_index) + 1
        idx = source_index[path]
        numbered.append((idx, hit))

    parts = []
    for idx, hit in numbered:
        text = hit.text.strip()
        page = hit.metadata.get("page_number")
        page_hint = f" (стр. {page})" if page is not None else ""
        parts.append(f"[{idx}]{page_hint}\n{text}")

    return "\n\n---\n\n".join(parts)


ROLE_HEADERS = {
    "methodology": "=== МЕТОДОЛОГИЯ ===",
    "lore": "=== ЗНАНИЯ О МИРЕ ===",
    "campaign_context": "=== КОНТЕКСТ КАМПАНИИ ===",
    "character_sheet": "=== ЛИСТ ПЕРСОНАЖА ===",
    "session_log": "=== ЖУРНАЛ СЕССИИ ===",
    "rules": "=== ПРАВИЛА ===",
}


def format_context_with_role(hits: list[SearchHit], role: str) -> str:
    if not hits:
        return ""
    header = ROLE_HEADERS.get(role, f"=== {role.upper()} ===")
    parts = [header]
    for index, hit in enumerate(hits, start=1):
        parts.append(f"[{index}]\n{hit.text.strip()}\n---")
    return "\n\n".join(parts)


async def _default_top_k() -> int:
    try:
        return int(await settings_service.get("retrieval.top_k"))
    except KeyError:
        return 10


async def _resolve_embedding_model(
    config: AppConfig | None,
    db: AsyncSession | None,
) -> EmbeddingModelConfig:
    """Returns the active EmbeddingModelConfig.

    Priority:
      1. config (AppConfig) — used by pipeline executor path
      2. settings_service.get_active_embedding_config(db) — used by fallback path
    """
    if config is not None:
        return _select_embedding_model(config)
    if db is not None:
        model = await settings_service.get_active_embedding_config(db)
        if model is not None:
            return model
    raise ValueError("Embedding configuration is not available.")


def _select_embedding_model(config: AppConfig) -> EmbeddingModelConfig:
    for embedding_model in config.embedding_models.values():
        if embedding_model.enabled:
            return embedding_model
    raise ValueError("No enabled embedding model configured.")


async def _embed_query(query: str, model: EmbeddingModelConfig) -> list[float]:
    if model.provider == "ollama":
        return await _embed_ollama(query, model)
    if model.provider == "openai_compatible":
        return await _embed_openai_compatible(query, model)
    raise ValueError(f"Unsupported embedding provider: {model.provider}")


async def _embed_ollama(query: str, model: EmbeddingModelConfig) -> list[float]:
    last_error: Exception | None = None
    for attempt in range(model.max_retries):
        try:
            async with httpx.AsyncClient(timeout=_timeout(model)) as client:
                response = await client.post(
                    f"{model.base_url.rstrip('/')}/api/embeddings",
                    json={"model": model.model_name, "prompt": query},
                )
                response.raise_for_status()
                vector = response.json().get("embedding")
                return _validate_vector(vector, model.dimensions)
        except Exception as exc:
            last_error = exc
            if attempt < model.max_retries - 1:
                await asyncio.sleep(2**attempt)
    raise RuntimeError("Embedding provider is unavailable.") from last_error


async def _embed_openai_compatible(query: str, model: EmbeddingModelConfig) -> list[float]:
    last_error: Exception | None = None
    api_key_env = getattr(model, "api_key_env", "OPENAI_API_KEY")
    headers = {"Authorization": f"Bearer {os.getenv(api_key_env, '')}"}
    for attempt in range(model.max_retries):
        try:
            async with httpx.AsyncClient(timeout=_timeout(model), headers=headers) as client:
                response = await client.post(
                    f"{model.base_url.rstrip('/')}/embeddings",
                    json={"model": model.model_name, "input": query},
                )
                response.raise_for_status()
                data = response.json().get("data")
                vector = data[0].get("embedding") if isinstance(data, list) and data else None
                return _validate_vector(vector, model.dimensions)
        except Exception as exc:
            last_error = exc
            if attempt < model.max_retries - 1:
                await asyncio.sleep(2**attempt)
    raise RuntimeError("Embedding provider is unavailable.") from last_error


def _validate_vector(vector: object, dimensions: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise ValueError("Embedding vector dimension mismatch.")
    return [float(value) for value in vector]


def _timeout(model: EmbeddingModelConfig) -> httpx.Timeout:
    return httpx.Timeout(min(float(model.timeout_seconds), 10.0), connect=min(float(model.timeout_seconds), 3.0))
