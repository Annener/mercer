from __future__ import annotations
import asyncio
import logging
import os
import httpx
from app.config import AppConfig, EmbeddingModelConfig
from shared_contracts.models import SearchHit, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")

async def retrieve(
    query: str,
    vault_id: str | None,
    top_k: int,
    strategy: str,
    config: AppConfig,
) -> list[SearchHit]:
    if not config.retrieval.enabled or not vault_id or strategy == "none":
        return []
    if strategy != "semantic":
        logger.info("Retrieval strategy is not implemented yet: %s", strategy)
        return []
    try:
        embedding_model = _select_embedding_model(config)
        vector = await _embed_query(query, embedding_model)
        async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=15) as client:
            response = await client.post(
                "/index/search",
                json=SearchRequest(vault_id=vault_id, vector=vector, top_k=top_k).model_dump(),
            )
            response.raise_for_status()
        search_response = SearchResponse.model_validate(response.json())
        logger.info("Retrieval completed: vault_id=%s hits=%s", vault_id, len(search_response.results))
        return search_response.results
    except Exception:
        logger.warning("Retrieval failed; continuing without context: vault_id=%s", vault_id, exc_info=True)
        return []

async def retrieve_multi_vault(
    query: str,
    vault_ids: list[str],
    top_k: int,
    strategy: str,
    config: AppConfig,
) -> list[SearchHit]:
    """Ищет во всех указанных vault'ах, объединяет результаты, сортирует по score, возвращает top_k."""
    if not vault_ids:
        return []
    all_hits: list[SearchHit] = []
    for vault_id in vault_ids:
        hits = await retrieve(query, vault_id, top_k, strategy, config)
        all_hits.extend(hits)
    all_hits.sort(key=lambda h: h.score, reverse=True)
    return all_hits[:top_k]

def format_context(hits: list[SearchHit]) -> str:
    """
    Формирует стандартный структурированный блок контекста для LLM.
    Использует Markdown + XML-теги для чёткого разделения источников и чанков.
    """
    if not hits:
        return "<retrieved_context>\nКонтекст не найден в базе знаний. Опирайся на общие правила, но явно укажи отсутствие локальных данных.\n</retrieved_context>"
    
    parts = ["<retrieved_context>"]
    for index, hit in enumerate(hits, start=1):
        source = hit.metadata.get("source_path") or hit.document_id or "unknown"
        score = hit.score
        tags = ", ".join(hit.metadata.get("tags", [])) or "none"
        content_type = hit.metadata.get("content_type", "general")
        text = hit.text.strip()
        
        parts.append(f"### Источник {index} | Файл: `{source}` | Тип: `{content_type}` | Теги: `{tags}` | Score: {score:.3f}")
        parts.append(f"<chunk>{text}</chunk>")
    
    parts.append("</retrieved_context>")
    return "\n\n".join(parts)

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