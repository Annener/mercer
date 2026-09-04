"""source_utils.py — единые helper-функции для конвертации SearchHit → Source.

Используются во всех местах, где нужно:
- показать источники пользователю в UI (sources event);
- сохранить список источников в Message.sources для восстановления при reload.

Все конвертации идемпотентны по (path, page, vault_id, chunk_id).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from shared_contracts.models import MessageSource, SearchHit, Source, SourceGroup

logger = logging.getLogger(__name__)

# Hard cap для SSE payload tool_result — защита от раздувания трафика
# при очень больших выдачах (search_knowledge truncation по evidence_token_budget
# обычно ограничивает сильнее, но это страховка).
MAX_SOURCES_PER_TOOL_RESULT = 50


def hits_to_sources(
    hits: list[SearchHit],
    *,
    cap: int | None = None,
) -> list[Source]:
    """Превращает SearchHit → Source с дедупликацией.

    Дедупликация по (path, page, vault_id, chunk_id). Сохраняется порядок первого
    появления. Если `cap` задан — обрезает до первых N уникальных.
    """
    out: list[Source] = []
    seen: set[tuple] = set()
    for hit in hits:
        md = hit.metadata or {}
        path = md.get("source_path") or hit.document_id
        page = md.get("page_number")
        vault_id = md.get("vault_id")
        chunk_id = hit.chunk_id
        key = (path, page, vault_id, chunk_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Source(
                path=path,
                page=page,
                vault_id=vault_id,
                document_id=hit.document_id,
                chunk_id=chunk_id,
                score=hit.score,
                source_kind="chunk",
            )
        )
        if cap is not None and len(out) >= cap:
            break
    return out


def full_doc_hits_to_sources(hits: list[SearchHit]) -> list[Source]:
    """Для send_full_document шага: одна запись на document_id, source_kind='full_document'.

    `hits` в этом режиме содержат несколько SearchHit на один документ (по чанку
    на страницу). Дедуплицируем по (path, vault_id, document_id) — page игнорируем,
    т.к. в этом режиме один документ отображается как единый источник.
    """
    out: list[Source] = []
    seen_docs: set[tuple] = set()
    for hit in hits:
        md = hit.metadata or {}
        path = md.get("source_path") or hit.document_id
        vault_id = md.get("vault_id")
        doc_key = (path, vault_id, hit.document_id)
        if doc_key in seen_docs:
            continue
        seen_docs.add(doc_key)
        out.append(
            Source(
                path=path,
                page=None,  # для full_document page нерелевантен
                vault_id=vault_id,
                document_id=hit.document_id,
                chunk_id=None,
                score=hit.score,
                source_kind="full_document",
            )
        )
    return out


def dedup_sources(sources: Iterable[Source]) -> list[Source]:
    """Дополнительная дедупликация списка Source (например, для multi-round agent loop)."""
    out: list[Source] = []
    seen: set[tuple] = set()
    for s in sources:
        key = (s.path, s.page, s.vault_id, s.chunk_id, s.document_id, s.source_kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def sources_to_message_sources(sources: Iterable[Source]) -> list[MessageSource]:
    """Для персистенции в Message.sources — минимальный набор полей."""
    out: list[MessageSource] = []
    for s in sources:
        out.append(
            MessageSource(
                path=s.path,
                page=s.page,
                vault_id=s.vault_id,
                document_id=s.document_id,
                chunk_id=s.chunk_id,
                source_kind=s.source_kind,
            )
        )
    return out


def merge_sources(*lists: Iterable[Source]) -> list[Source]:
    """Объединяет несколько списков Source с дедупликацией."""
    flat: list[Source] = []
    for lst in lists:
        flat.extend(lst)
    return dedup_sources(flat)


def normalize_persisted_sources(
    raw: list[Any] | None,
) -> list[dict[str, Any]]:
    """Нормализует «сырые» источники из SSE `sources` event перед записью в БД.

    Принимает список, в котором могут встречаться как плоские `Source`-словари,
    так и `SourceGroup`-словари (`{"step_id", "step_name", "sources": [...]}`)
    — последние остались после старой логики `full_document_confirm`.

    Возвращает плоский список dict-сериализованных `MessageSource` после
    `dedup_sources` — то есть всегда в формате, который читает
    `_parse_message_sources` / `GET /chat/{id}/history`.

    Мусорные элементы пропускаются (best-effort, чтобы не падать на битых
    payload'ах).
    """
    if not raw:
        return []
    collected: list[Source] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            if "sources" in item and "step_id" in item:
                group = SourceGroup.model_validate(item)
                collected.extend(group.sources)
            else:
                collected.append(Source.model_validate(item))
        except Exception:  # noqa: BLE001 — испорченные записи пропускаем
            logger.warning("normalize_persisted_sources: skipped malformed: %r", item)
    deduped = dedup_sources(collected)
    return [s.model_dump(mode="json", exclude_none=True) for s in sources_to_message_sources(deduped)]


__all__ = [
    "MAX_SOURCES_PER_TOOL_RESULT",
    "dedup_sources",
    "full_doc_hits_to_sources",
    "hits_to_sources",
    "merge_sources",
    "normalize_persisted_sources",
    "sources_to_message_sources",
]
