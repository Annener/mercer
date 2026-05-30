from __future__ import annotations
import asyncio
import logging
import os
from typing import Any
import httpx
from app.config import AppConfig, EmbeddingModelConfig
from app.services.settings_service import settings_service
from shared_contracts.models import SearchHit, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")

async def retrieve(
    query: str,
    vault_id: str | None,
    *,
    document_ids: list[str] | None = None,
    world_id: str | None = None,
    categories: list[str] | None = None,
    campaign_id: str | None = None,
    exclude_campaigns: list[str] | None = None,
    top_k: int | None = None,
    strategy: str = "semantic",
    config: AppConfig | None = None,
) -> list[SearchHit]:
    logger.info(
        "RETRIEVE query='%s' vault_id=%s top_k=%s world_id=%s campaign_id=%s doc_ids=%s",
        query, vault_id, top_k, world_id, campaign_id, document_ids
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
        if config is None:
            raise ValueError("Embedding configuration is not available.")
        embedding_model = _select_embedding_model(config)
        vector = await _embed_query(query, embedding_model)
        request_filter = _exact_filter(world_id=world_id, campaign_id=campaign_id)
        search_top_k = effective_top_k * 10 if _has_filters(document_ids, world_id, categories, campaign_id, exclude_campaigns) else effective_top_k
        async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=15) as client:
            response = await client.post(
                "/index/search",
                json=SearchRequest(vault_id=vault_id, vector=vector, top_k=search_top_k, filter=request_filter).model_dump(),
            )
            response.raise_for_status()
        search_response = SearchResponse.model_validate(response.json())
        results = _filter_hits(
            search_response.results,
            document_ids=document_ids,
            world_id=world_id,
            categories=categories,
            campaign_id=campaign_id,
            exclude_campaigns=exclude_campaigns,
        )[:effective_top_k]
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
    world_id: str | None = None,
    categories: list[str] | None = None,
    campaign_id: str | None = None,
    exclude_campaigns: list[str] | None = None,
    top_k: int | None = None,
    strategy: str = "semantic",
    config: AppConfig | None = None,
) -> list[SearchHit]:
    """Ищет во всех указанных vault'ах, объединяет результаты, сортирует по score, возвращает top_k."""
    if not vault_ids:
        return []
    logger.info(
        "RETRIEVE_MULTI query='%s' vaults=%s top_k=%s",
        query, vault_ids, top_k
    )
    effective_top_k = top_k or await _default_top_k()
    all_hits: list[SearchHit] = []
    for vault_id in vault_ids:
        hits = await retrieve(
            query,
            vault_id,
            document_ids=document_ids,
            world_id=world_id,
            categories=categories,
            campaign_id=campaign_id,
            exclude_campaigns=exclude_campaigns,
            top_k=effective_top_k,
            strategy=strategy,
            config=config,
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
    на фронтенде (файл 1, файл 2, ...) — группировка по уникальным (path, page) в том же порядке.
    Не используем XML/HTML-теги (типа <retrieved_context>), чтобы LLM не протаскивал их в ответ.
    """
    if not hits:
        return "Контекст не найден в базе знаний. Отвечай на основе общих знаний, но явно укажи что локальные данные не найдены."

    # Назначаем номер каждому уникальному источнику (path, page).
    # Фронтенд нумерует точно так же — по порядку появления уникального (path).
    source_index: dict[str, int] = {}  # path -> номер источника
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


def _exact_filter(*, world_id: str | None, campaign_id: str | None) -> dict[str, Any] | None:
    filter_values: dict[str, Any] = {}
    if world_id:
        filter_values["world_id"] = world_id
    if campaign_id:
        filter_values["campaign_id"] = campaign_id
    return filter_values or None


def _has_filters(*values: Any) -> bool:
    return any(bool(value) for value in values)


def _filter_hits(
    hits: list[SearchHit],
    *,
    document_ids: list[str] | None,
    world_id: str | None,
    categories: list[str] | None,
    campaign_id: str | None,
    exclude_campaigns: list[str] | None,
) -> list[SearchHit]:
    document_set = set(document_ids or [])
    category_set = set(categories or [])
    exclude_set = set(exclude_campaigns or [])
    filtered: list[SearchHit] = []
    for hit in hits:
        metadata = hit.metadata or {}
        if document_set and hit.document_id not in document_set and metadata.get("document_id") not in document_set:
            continue
        if world_id and metadata.get("world_id") != world_id:
            continue
        if category_set and metadata.get("category") not in category_set:
            continue
        if campaign_id and metadata.get("campaign_id") != campaign_id:
            continue
        if exclude_set and metadata.get("campaign_id") in exclude_set:
            continue
        filtered.append(hit)
    return filtered

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
