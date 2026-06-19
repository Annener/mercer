from __future__ import annotations
import asyncio
import logging
import json
import math
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
from app.db.models import Tag, Document, DocumentLabel, Vault, campaign_tags
from shared_contracts.models import SearchHit, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")

# Максимальное число одновременных запросов к Ollama reranker.
# Ollama обрабатывает запросы последовательно, поэтому большой параллелизм
# приводит к таймаутам. Значение можно переопределить через env RERANK_OLLAMA_CONCURRENCY.
_RERANK_OLLAMA_CONCURRENCY = int(os.getenv("RERANK_OLLAMA_CONCURRENCY", "1"))

# Максимум токенов для ответа реранкера. Нужно только "yes"/"no" — хватит 32.
# Без ограничения Qwen3-Reranker уходит в бесконечный <think>...</think> и зависает.
_RERANK_OLLAMA_NUM_PREDICT = int(os.getenv("RERANK_OLLAMA_NUM_PREDICT", "32"))


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
    - campaign_id задан →
        1. Собственные теги кампании (Tag.campaign_id == campaign_id)
        2. Глобальные теги домена (campaign_id IS NULL), явно подключённые
           к кампании через таблицу campaign_tags
      Глобальные теги домена, НЕ добавленные в кампанию, недоступны.
    - campaign_id = None → только глобальные теги домена (campaign_id IS NULL)

    Инвариант: пустое множество = кампания существует, но тегов нет →
    вызывающий код должен вернуть document_ids=[] (не None), т.е. не расширяться на весь домен.
    """
    if campaign_id:
        camp_uuid = uuid.UUID(campaign_id)
        # 1. Собственные теги кампании
        own_stmt = select(Tag.id).where(
            Tag.domain_id == domain_id,
            Tag.campaign_id == camp_uuid,
        )
        # 2. Глобальные теги домена, явно подключённые через campaign_tags
        linked_stmt = (
            select(Tag.id)
            .join(campaign_tags, campaign_tags.c.tag_id == Tag.id)
            .where(
                Tag.domain_id == domain_id,
                Tag.campaign_id.is_(None),
                campaign_tags.c.campaign_id == camp_uuid,
            )
        )
        own = (await db.execute(own_stmt)).scalars().all()
        linked = (await db.execute(linked_stmt)).scalars().all()
        return {str(t) for t in own} | {str(t) for t in linked}
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


# ---------------------------------------------------------------------------
# Hybrid search helpers
# ---------------------------------------------------------------------------

async def _vector_search(
    vault_id: str,
    vector: list[float],
    top_k: int,
    filter_expr: dict[str, Any] | None,
) -> list[SearchHit]:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=15) as client:
        response = await client.post(
            "/index/search",
            json=SearchRequest(
                vault_id=vault_id,
                vector=vector,
                top_k=top_k,
                filter=filter_expr,
            ).model_dump(),
        )
        response.raise_for_status()
    return SearchResponse.model_validate(response.json()).results


async def _text_search(
    vault_id: str,
    query_text: str,
    limit: int,
    filter_expr: dict[str, Any] | None,
) -> list[SearchHit]:
    async with httpx.AsyncClient(base_url=STORAGE_API_URL, timeout=15) as client:
        response = await client.post(
            "/index/search/text",
            json={"vault_id": vault_id, "query_text": query_text, "limit": limit},
        )
        response.raise_for_status()
    hits = [SearchHit(**h) for h in response.json().get("results", [])]
    # Применяем document_ids фильтр вручную (text endpoint его не поддерживает)
    if filter_expr and "$in" in filter_expr.get("document_id", {}):
        doc_set = set(filter_expr["document_id"]["$in"])
        hits = [h for h in hits if h.document_id in doc_set]
    return hits


def _rrf_merge(
    vector_hits: list[SearchHit],
    text_hits: list[SearchHit],
    *,
    k: int = 60,
    top_k: int,
) -> list[SearchHit]:
    """
    Объединяет результаты vector и text поиска через Reciprocal Rank Fusion.
    Итоговый score = 1/(k+rank_vector) + 1/(k+rank_text).
    chunk_id используется как ключ дедупликации.
    """
    scores: dict[str, float] = {}
    by_id: dict[str, SearchHit] = {}

    for rank, hit in enumerate(vector_hits):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        by_id[hit.chunk_id] = hit

    for rank, hit in enumerate(text_hits):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        by_id.setdefault(hit.chunk_id, hit)  # vector-версия хита имеет приоритет

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [
        SearchHit(
            chunk_id=cid,
            document_id=by_id[cid].document_id,
            text=by_id[cid].text,
            metadata=by_id[cid].metadata,
            score=scores[cid],
        )
        for cid in sorted_ids[:top_k]
    ]


# ---------------------------------------------------------------------------
# Public retrieval API
# ---------------------------------------------------------------------------

async def retrieve(
    query: str,
    vault_id: str | None,
    *,
    document_ids: list[str] | None = None,
    top_k: int | None = None,
    strategy: str = "hybrid",
    config: AppConfig | None = None,
    db: AsyncSession | None = None,
    _embedding_model: EmbeddingModelConfig | None = None,
) -> list[SearchHit]:
    """
    document_ids = None  → поиск по всему vault без фильтра
    document_ids = []    → вернуть [] сразу, без запроса к LanceDB
    document_ids = [...] → поиск с фильтром {"document_id": {"$in": document_ids}}

    Приоритет резолюции embedding-модели:
      1. _embedding_model  — прямая передача (retrieve_multi_vault раз решает)
      2. config            — AppConfig из pipeline-пути
      3. db                — подтягивает из БД через settings_service (фаллбэк-путь)

    Стратегии:
      "hybrid"   — vector + FTS → RRF merge (дефолт)
      "semantic" — только vector search
      "none"     — пропустить retrieval
    """
    if document_ids is not None and len(document_ids) == 0:
        return []

    logger.info(
        "RETRIEVE query='%s' vault_id=%s top_k=%s doc_ids=%s strategy=%s",
        query, vault_id, top_k, document_ids, strategy,
    )
    if not vault_id or strategy == "none":
        logger.warning(
            "Retrieval skipped: vault_id=%s strategy=%s",
            vault_id, strategy
        )
        return []
    effective_top_k = top_k or await _default_top_k()
    if strategy not in ("semantic", "hybrid"):
        logger.info("Retrieval strategy is not implemented: %s", strategy)
        return []
    try:
        embedding_model = await _resolve_embedding_model(
            config=config, db=db, direct=_embedding_model
        )
        logger.info(
            "RETRIEVE embedding_model=%s provider=%s base_url=%s dimensions=%d",
            embedding_model.model_id,
            embedding_model.provider,
            embedding_model.base_url,
            embedding_model.dimensions,
        )
        vector = await _embed_query(query, embedding_model)

        filter_expr: dict[str, Any] | None = None
        if document_ids is not None:
            filter_expr = {"document_id": {"$in": document_ids}}
            search_top_k = effective_top_k * 10
        else:
            search_top_k = effective_top_k

        vector_hits = await _vector_search(vault_id, vector, search_top_k, filter_expr)

        if strategy == "hybrid":
            try:
                text_hits = await _text_search(vault_id, query, search_top_k, filter_expr)
            except Exception:
                logger.warning(
                    "RETRIEVE text_search failed for vault '%s', falling back to vector-only",
                    vault_id, exc_info=True,
                )
                text_hits = []
            if text_hits:
                raw_hits = _rrf_merge(vector_hits, text_hits, top_k=effective_top_k)
            else:
                raw_hits = vector_hits
        else:
            raw_hits = vector_hits

        logger.info(
            "RETRIEVE raw_hits=%d filter_expr=%s sample_doc_ids=%s",
            len(raw_hits),
            filter_expr,
            [h.document_id for h in raw_hits[:3]],
        )

        results = raw_hits
        if document_ids is not None:
            doc_set = set(document_ids)
            results = [
                h for h in results
                if h.document_id in doc_set
                or (h.metadata or {}).get("document_id") in doc_set
            ]
            if len(results) != len(raw_hits):
                logger.info(
                    "RETRIEVE post-filter: raw=%d → filtered=%d (doc_set sample=%s)",
                    len(raw_hits), len(results), list(doc_set)[:3],
                )
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
    strategy: str = "hybrid",
    config: AppConfig | None = None,
    db: AsyncSession | None = None,
) -> list[SearchHit]:
    """\u0418\u0449\u0435\u0442 \u0432\u043e \u0432\u0441\u0435\u0445 \u0443\u043a\u0430\u0437\u0430\u043d\u043d\u044b\u0445 vault'\u0430\u0445, \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u044f\u0435\u0442 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b, \u0441\u043e\u0440\u0442\u0438\u0440\u0443\u0435\u0442 \u043f\u043e score, \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0430\u0435\u0442 top_k.

    \u0415\u0441\u043b\u0438 vault'\u044b \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044e\u0442 \u0440\u0430\u0437\u043d\u044b\u0435 embedding-\u043c\u043e\u0434\u0435\u043b\u0438 (\u043d\u0430\u043f\u0440. \u0440\u0430\u0437\u043d\u044b\u0435 dimensions),
    \u043a\u0430\u0436\u0434\u044b\u0439 vault \u0440\u0435\u0448\u0430\u0435\u0442\u0441\u044f \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e.
    """
    if not vault_ids:
        return []
    if isinstance(document_ids, list) and len(document_ids) == 0:
        return []
    logger.info(
        "RETRIEVE_MULTI query='%s' vaults=%s top_k=%s",
        query, vault_ids, top_k
    )
    effective_top_k = top_k or await _default_top_k()

    all_hits: list[SearchHit] = []
    for vault_id in vault_ids:
        # Каждый vault может быть индексирован своей моделью —
        # решаем embedding по vault_id через Vault.embedding_model_id
        embedding_model: EmbeddingModelConfig | None = None
        if config is not None:
            embedding_model = _select_embedding_model(config)
        elif db is not None:
            embedding_model = await settings_service.get_active_embedding_config(
                db, vault_id=vault_id
            )

        if embedding_model is None:
            logger.warning("RETRIEVE_MULTI no embedding model for vault=%s, skipping", vault_id)
            continue

        hits = await retrieve(
            query,
            vault_id,
            document_ids=document_ids,
            top_k=effective_top_k,
            strategy=strategy,
            _embedding_model=embedding_model,
        )
        all_hits.extend(hits)

    all_hits.sort(key=lambda h: h.score, reverse=True)
    result = all_hits[:effective_top_k]
    if db is not None:
        result = await rerank_hits(query, result, db)
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
        doc_id = hit.document_id or ""
        if doc_id not in source_index:
            source_index[doc_id] = len(source_index) + 1
        numbered.append((source_index[doc_id], hit))

    blocks = []
    for n, hit in numbered:
        blocks.append(f"[{n}] {hit.text}")

    return "\n\n".join(blocks)


def format_context_with_role(hits: list[SearchHit], role: str) -> str:
    """
    Формирует блок контекста с заголовком роли для pipeline-шагов.
    Добавляет строку вида "=== <role> ===", затем нумерованные блоки [1], [2], ...
    Если hits пуст — возвращает пустую строку (pipeline-executor проверяет это сам).
    """
    if not hits:
        return ""

    header = f"=== {role} ===" if role else ""

    source_index: dict[str, int] = {}
    numbered: list[tuple[int, SearchHit]] = []

    for hit in hits:
        doc_id = hit.document_id or ""
        if doc_id not in source_index:
            source_index[doc_id] = len(source_index) + 1
        numbered.append((source_index[doc_id], hit))

    blocks = []
    for n, hit in numbered:
        blocks.append(f"[{n}] {hit.text}")

    body = "\n\n".join(blocks)
    return f"{header}\n{body}" if header else body


async def _default_top_k() -> int:
    return int(os.getenv("DEFAULT_TOP_K", "10"))


async def _resolve_embedding_model(
    *,
    config: AppConfig | None,
    db: AsyncSession | None,
    direct: EmbeddingModelConfig | None,
) -> EmbeddingModelConfig:
    if direct is not None:
        return direct
    if config is not None:
        return _select_embedding_model(config)
    if db is not None:
        model = await settings_service.get_active_embedding_config(db)
        if model:
            return model
    raise ValueError("No enabled embedding model configured.")


def _select_embedding_model(config: AppConfig) -> EmbeddingModelConfig:
    enabled = [m for m in config.embedding_models if m.enabled]
    if not enabled:
        raise ValueError("No enabled embedding model configured.")
    return enabled[0]


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
    """TD-02: ключ берётся напрямую из model.api_key, а не через os.getenv.
    Это устраняет гонку условий при конкурентных запросах с разными api_key.
    Фоллбэк на api_key_env оставлен для обратной совместимости с yaml-конфигами rag-indexer.
    """
    last_error: Exception | None = None
    # Приоритет: model.api_key (расшифрован из БД), фоллбэк: api_key_env (для yaml-пути)
    api_key = model.api_key or os.getenv(model.api_key_env, "") if model.api_key_env else model.api_key
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
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


# ---------------------------------------------------------------------------
# Ollama reranker helpers
# ---------------------------------------------------------------------------

_OLLAMA_RERANK_PROMPT_TEMPLATE = (
    "<Instruct>: Given a query and a document, output yes or no to indicate "
    "whether the document is relevant to the query.\n"
    "<query>: {query}\n"
    "<document>: {document}\n"
    "<response>:"
)

# Token strings that indicate yes/no relevance.
_YES_TOKENS: frozenset[str] = frozenset({"yes", "Yes", "YES"})
_NO_TOKENS: frozenset[str] = frozenset({"no", "No", "NO"})


def _score_from_response_text(response_text: str) -> float:
    """
    Извлекает relevance score из текстового ответа Ollama.

    Qwen3-Reranker и другие instruct-модели могут генерировать цепочку
    рассуждений (<think>...</think>) перед финальным ответом.
    Поэтому ищем yes/no в КОНЦЕ текста, а не в начале.

    Логика:
    1. Убираем <think>...</think> блоки если есть.
    2. Берём последнее непустое слово очищенного текста.
    3. yes-like → 1.0, no-like → 0.0, иначе 0.5 (нейтральный fallback).
    """
    import re
    # Убираем thinking-блоки
    cleaned = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL)
    # Берём последний токен (слово) из очищенного ответа
    tokens = cleaned.strip().split()
    last_token = tokens[-1].strip(".,!?;:") if tokens else ""
    if last_token in _YES_TOKENS:
        return 1.0
    if last_token in _NO_TOKENS:
        return 0.0
    # Fallback: ищем yes/no в любом месте очищенного текста (слева направо, последнее вхождение)
    found_yes = cleaned.lower().rfind("yes")
    found_no = cleaned.lower().rfind("no")
    if found_yes > found_no:
        return 1.0
    if found_no > found_yes:
        return 0.0
    return 0.5


async def _rerank_single_ollama(
    client: httpx.AsyncClient,
    base_url: str,
    model_id: str,
    query: str,
    document: str,
    idx: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, float]:
    """
    Один запрос к Ollama для одного документа.
    Возвращает (idx, score) — индекс нужен для сборки результатов после asyncio.gather.

    semaphore ограничивает параллелизм: Ollama обрабатывает запросы к одной модели последовательно.
    По умолчанию concurrency=1 (строго последовательно).

    num_predict ограничивает длину ответа: без него Qwen3-Reranker уходит в
    бесконечный <think>...</think> блок.
    """
    prompt = _OLLAMA_RERANK_PROMPT_TEMPLATE.format(
        query=query,
        document=document[:2000],
    )
    async with semaphore:
        try:
            response = await client.post(
                f"{base_url.rstrip('/')}/api/generate",
                json={
                    "model": model_id,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": _RERANK_OLLAMA_NUM_PREDICT,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise ValueError(f"Ollama error: {data['error']}")
            response_text = data.get("response", "")
            score = _score_from_response_text(response_text)
            logger.debug(
                "RERANK_OLLAMA idx=%d score=%.3f response=%r",
                idx, score, response_text.strip(),
            )
        except Exception:
            logger.warning("RERANK_OLLAMA doc idx=%d failed", idx, exc_info=True)
            score = 0.0
    return idx, score


async def _rerank_hits_ollama(
    query: str,
    hits: list[SearchHit],
    model: Any,
) -> list[SearchHit]:
    """
    Ollama-реранжирование с ограниченным параллелизмом через asyncio.Semaphore.
    """
    documents = [h.text for h in hits]
    base_url = model.base_url or ""
    model_id = model.model_id
    timeout = float(model.timeout_seconds)

    semaphore = asyncio.Semaphore(_RERANK_OLLAMA_CONCURRENCY)

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _rerank_single_ollama(client, base_url, model_id, query, doc, idx, semaphore)
            for idx, doc in enumerate(documents)
        ]
        results: list[tuple[int, float]] = await asyncio.gather(*tasks)

    results.sort(key=lambda x: x[1], reverse=True)
    reranked = [hits[idx] for idx, _ in results]
    logger.info(
        "RERANK_OLLAMA done: model='%s' hits=%d top_scores=%s",
        model_id,
        len(reranked),
        [round(s, 3) for _, s in sorted(results, key=lambda x: x[1], reverse=True)[:3]],
    )
    return reranked


async def rerank_hits(
    query: str,
    hits: list[SearchHit],
    db: AsyncSession,
) -> list[SearchHit]:
    """
    Переранжирует hits с помощью активной reranker-модели.
    Если активной модели нет, enabled=False или список пуст — возвращает hits без изменений.
    """
    logger.info("RERANK_HITS start: query='%s' hits=%d", query, len(hits))
    model = await settings_service.get_active_rerank_model(db)
    if model is None or not model.enabled or not model.is_active:
        logger.info("RERANK_HITS skipped: no active reranker model")
        return hits
    if not hits:
        logger.info("RERANK_HITS skipped: empty hits list")
        return hits

    # ── Ollama: генеративный режим ───────────────────────────────────────────
    if model.provider == "ollama":
        try:
            return await _rerank_hits_ollama(query, hits, model)
        except Exception:
            logger.warning("RERANK_HITS ollama failed, returning original hits", exc_info=True)
            return hits

    # ── Стандартные провайдеры: openai_compatible / cohere / jina ─────────────
    documents = [h.text for h in hits]
    api_key = settings_service.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else ""

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(
        timeout=model.timeout_seconds,
        headers=headers,
    ) as client:
        response = await client.post(
            f"{model.base_url.rstrip('/')}/rerank",
            json={"model": model.model_id, "query": query, "documents": documents},
        )
        response.raise_for_status()

    data = response.json()
    results = data.get("results") or data.get("data") or []
    scored: list[tuple[float, SearchHit]] = []
    for item in results:
        idx = item.get("index", item.get("corpus_id"))
        score = item.get("relevance_score") if item.get("relevance_score") is not None else item.get("score", 0.0)
        if idx is not None and idx < len(hits):
            scored.append((score, hits[idx]))

    if not scored:
        logger.info("RERANK_HITS: empty scored list, returning original hits")
        return hits

    scored.sort(key=lambda x: x[0], reverse=True)
    reranked = [hit for _, hit in scored]
    logger.info("RERANK_HITS done: reranked %d hits via model='%s'\n", len(reranked), model.model_id)
    return reranked
