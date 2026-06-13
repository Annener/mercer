from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import lancedb

from shared_contracts.models import ChunkRecord, DocumentRecord, SearchHit, SearchRequest, SearchResponse, UpsertRequest, UpsertResponse


logger = logging.getLogger(__name__)


class LanceDBStore:
    def __init__(self, data_path: str) -> None:
        self.data_path = Path(data_path)
        self.db: Any | None = None
        self._vault_dimensions: dict[str, int] = {}

    def connect(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.data_path))
        logger.info("Connected to LanceDB at %s", self.data_path)
        self.build_fts_indexes()

    def build_fts_indexes(self) -> None:
        """
        Однократно создаёт/пересоздаёт FTS-индекс на колонке 'text'
        для всех существующих таблиц vault_*.
        Вызывается один раз при старте сервиса из connect().
        Ошибка для отдельной таблицы не прерывает обход остальных.
        """
        db = self._db()
        table_names = [t for t in db.table_names() if t.startswith("vault_")]
        if not table_names:
            logger.info("FTS index build: no vault tables found, skipping")
            return
        logger.info("FTS index build: found %d tables: %s", len(table_names), table_names)
        for name in table_names:
            try:
                table = db.open_table(name)
                table.create_fts_index("text", replace=True)
                logger.info("FTS index built for table '%s'", name)
            except Exception:
                logger.warning("FTS index build failed for table '%s'", name, exc_info=True)

    def upsert(self, req: UpsertRequest) -> UpsertResponse:
        if not req.chunks:
            return UpsertResponse(status="ok", upserted_count=0)

        logger.info(
            "UPSERT vault='%s' chunks=%d doc_ids=%s",
            req.vault_id,
            len(req.chunks),
            list({c.document_id for c in req.chunks}),
        )

        expected_dimensions = self._get_expected_dimensions(req.vault_id)
        if expected_dimensions is None:
            expected_dimensions = len(req.chunks[0].vector)
            self._vault_dimensions[req.vault_id] = expected_dimensions

        rows: list[dict[str, Any]] = []
        failed_indices: list[int] = []
        error_details: list[str] = []

        for index, chunk in enumerate(req.chunks):
            vector_dimensions = len(chunk.vector)
            if vector_dimensions != expected_dimensions:
                failed_indices.append(index)
                error_details.append(
                    f"Dimension mismatch at index {index}: expected {expected_dimensions}, got {vector_dimensions}"
                )
                continue
            rows.append(
                {
                    "chunk_id": _chunk_id(chunk.document_id, chunk.chunk_index),
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "vector": chunk.vector,
                    "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
                }
            )

        if rows:
            table = self._get_or_create_table(req.vault_id, rows)
            self._replace_rows(table, rows)

        status = "partial" if failed_indices else "ok"

        if failed_indices:
            logger.warning(
                "UPSERT PARTIAL vault='%s' upserted=%d failed=%d errors=%s",
                req.vault_id, len(rows), len(failed_indices), error_details[:3],
            )
        else:
            logger.info("UPSERT OK vault='%s' upserted=%d", req.vault_id, len(rows))

        return UpsertResponse(
            status=status,
            upserted_count=len(rows),
            failed_indices=failed_indices,
            error_details=error_details,
        )

    def search(self, req: SearchRequest) -> SearchResponse:
        if not self._table_exists(req.vault_id):
            return SearchResponse()

        expected_dimensions = self._get_expected_dimensions(req.vault_id)
        if expected_dimensions is not None and len(req.vector) != expected_dimensions:
            logger.warning(
                "Search dimension mismatch for vault %s: expected %s, got %s",
                req.vault_id,
                expected_dimensions,
                len(req.vector),
            )
            return SearchResponse()

        logger.info(
            "SEARCH vault='%s' top_k=%d filter=%s score_threshold=%s",
            req.vault_id,
            req.top_k,
            req.filter or "none",
            req.score_threshold,
        )
        table = self._open_table(req.vault_id)
        limit = req.top_k * 10 if req.filter else req.top_k
        query = table.search(req.vector).limit(limit)

        hits: list[SearchHit] = []
        for row in query.to_list():
            distance = float(row.get("_distance", 0.0))
            score = 1.0 - distance
            if req.score_threshold is not None and score < req.score_threshold:
                continue
            metadata = _decode_metadata(row.get("metadata"))
            if req.filter and not _matches_filter(row, metadata, req.filter):
                continue
            hits.append(
                SearchHit(
                    chunk_id=str(row["chunk_id"]),
                    document_id=str(row["document_id"]),
                    text=str(row["text"]),
                    metadata=metadata,
                    score=score,
                )
            )
            if len(hits) >= req.top_k:
                break
        logger.info(
            "SEARCH DONE vault='%s' hits=%d scores=[%s]",
            req.vault_id,
            len(hits),
            ", ".join(f"{h.score:.3f}" for h in hits[:5]),
        )
        return SearchResponse(results=hits)

    def delete_document(self, vault_id: str, document_id: str) -> int:
        if not self._table_exists(vault_id):
            return 0
        table = self._open_table(vault_id)
        before_count = self._count_rows(table)
        table.delete(f"document_id = '{_escape_sql_literal(document_id)}'")
        after_count = self._count_rows(table)
        return max(before_count - after_count, 0)

    def list_documents(
        self,
        vault_id: str,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "document_id",
    ) -> list[DocumentRecord]:
        if not self._table_exists(vault_id):
            return []

        documents: dict[str, dict[str, Any]] = {}
        for row in self._all_rows(vault_id):
            document_id = str(row["document_id"])
            metadata = _decode_metadata(row.get("metadata"))
            document = documents.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "vault_id": vault_id,
                    "source_path": str(metadata.get("source_path") or metadata.get("source") or document_id),
                    "checksum": str(metadata.get("checksum") or ""),
                    "metadata": metadata,
                    "chunk_count": 0,
                },
            )
            document["chunk_count"] += 1

        rows = list(documents.values())
        if order_by == "chunk_count":
            rows.sort(key=lambda item: int(item["chunk_count"]), reverse=True)
        else:
            rows.sort(key=lambda item: str(item.get(order_by) or item["document_id"]))
        return [DocumentRecord.model_validate(row) for row in rows[offset : offset + limit]]

    def get_document_chunks(self, vault_id: str, document_id: str) -> list[ChunkRecord]:
        if not self._table_exists(vault_id):
            return []

        chunks: list[ChunkRecord] = []
        for row in self._all_rows(vault_id):
            if str(row["document_id"]) != document_id:
                continue
            chunks.append(_chunk_record(vault_id, row))
        chunks.sort(key=lambda chunk: int(chunk.metadata.get("chunk_index", 0)))
        return chunks

    def text_search(self, vault_id: str, query_text: str, limit: int = 20) -> list[SearchHit]:
        if not self._table_exists(vault_id):
            return []
        table = self._open_table(vault_id)
        try:
            rows = table.search(query_text, query_type="fts").limit(limit).to_list()
        except Exception:
            # Фаллбэк: FTS-индекс ещё не построен — substring match
            logger.warning(
                "FTS search failed for vault '%s', falling back to substring match", vault_id,
                exc_info=True,
            )
            needle = query_text.lower()
            rows = [
                r for r in self._all_rows(vault_id)
                if needle in str(r.get("text") or "").lower()
            ][:limit]
        return [
            SearchHit(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                text=str(row.get("text") or ""),
                metadata=_decode_metadata(row.get("metadata")),
                score=1.0,
            )
            for row in rows
        ]

    def delete_vault(self, vault_id: str) -> int:
        if not self._table_exists(vault_id):
            return 0
        table = self._open_table(vault_id)
        deleted_count = self._count_rows(table)
        self._db().drop_table(_table_name(vault_id))
        self._vault_dimensions.pop(vault_id, None)
        return deleted_count

    def _get_or_create_table(self, vault_id: str, rows: list[dict[str, Any]]) -> Any:
        if self._table_exists(vault_id):
            return self._open_table(vault_id)
        table = self._db().create_table(_table_name(vault_id), data=rows)
        try:
            table.create_fts_index("text", replace=True)
            logger.info("FTS index built for new table '%s'", _table_name(vault_id))
        except Exception:
            logger.warning("FTS index build failed for new table '%s'", _table_name(vault_id), exc_info=True)
        return table

    def _replace_rows(self, table: Any, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        chunk_ids = [_escape_sql_literal(str(row["chunk_id"])) for row in rows]
        ids_list = ", ".join(f"'{cid}'" for cid in chunk_ids)
        table.delete(f"chunk_id IN ({ids_list})")
        table.add(rows)

    def _get_expected_dimensions(self, vault_id: str) -> int | None:
        if vault_id in self._vault_dimensions:
            return self._vault_dimensions[vault_id]

        if not self._table_exists(vault_id):
            return None

        table = self._open_table(vault_id)
        first_rows = table.head(1).to_pylist()
        if not first_rows:
            return None

        dimensions = len(first_rows[0].get("vector") or [])
        if dimensions > 0:
            self._vault_dimensions[vault_id] = dimensions
            return dimensions
        return None

    def _table_exists(self, vault_id: str) -> bool:
        return _table_name(vault_id) in self._db().table_names()

    def _open_table(self, vault_id: str) -> Any:
        return self._db().open_table(_table_name(vault_id))

    def _all_rows(self, vault_id: str) -> list[dict[str, Any]]:
        table = self._open_table(vault_id)
        return table.to_arrow().to_pylist()

    def _db(self) -> Any:
        if self.db is None:
            raise RuntimeError("LanceDB connection is not initialized.")
        return self.db

    @staticmethod
    def _count_rows(table: Any) -> int:
        try:
            return table.count_rows()
        except AttributeError:
            return len(table.to_list())


def _chunk_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}_{chunk_index}"


def _table_name(vault_id: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", vault_id).strip("_")
    if not sanitized:
        raise ValueError("vault_id must contain at least one alphanumeric character.")
    return f"vault_{sanitized}"


def _decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _matches_filter(row: dict[str, Any], metadata: dict[str, Any], filter_values: dict[str, Any]) -> bool:
    """
    Проверяет строку LanceDB на соответствие фильтру.
    Поля-колонки (document_id, chunk_id и др.) берутся из row,
    остальные — из metadata. Поддерживаются операторы $in и $eq,
    а также прямое сравнение значений.
    """
    for key, condition in filter_values.items():
        # Колонки строки имеют приоритет над metadata
        value = row.get(key) if key in row else metadata.get(key)
        if isinstance(condition, dict):
            if "$in" in condition:
                if value not in condition["$in"]:
                    return False
            elif "$eq" in condition:
                if value != condition["$eq"]:
                    return False
        else:
            if value != condition:
                return False
    return True


def _escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _chunk_record(vault_id: str, row: dict[str, Any]) -> ChunkRecord:
    metadata = _decode_metadata(row.get("metadata"))
    metadata["chunk_index"] = int(row.get("chunk_index") or 0)
    return ChunkRecord(
        chunk_id=str(row["chunk_id"]),
        document_id=str(row["document_id"]),
        vault_id=vault_id,
        text=str(row.get("text") or ""),
        vector=None,
        metadata=metadata,
        summary=None,
    )
