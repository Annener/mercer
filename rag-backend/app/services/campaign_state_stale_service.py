"""campaign_state_stale_service.py — Stale-detection для Campaign State (Stage 7).

Алгоритм:
  1. Получить active state version кампании.
  2. Собрать уникальные source_refs формата `file:<uuid>:sha:<hex>` из
     CampaignStateValue + CampaignStateListItem активной версии.
  3. Для каждого document_id загрузить Document.md5/vault_id/source_path/status.
  4. PDF-фильтр: source_path не *.md → skip (никогда не считается stale).
  5. Прочитать vault:{vault_id}:files в Redis. Если ключ отсутствует —
     fallback на Document.md5 vs Document.md5 (не сигнализируем false positive).
  6. Сравнить:
        indexed_md5 != Document.md5 → stale
        index_status in {pending, stale, deleted} → stale
        Document.status != indexed → stale
  7. Вернуть CampaignStateStaleStatus + сторона-эффект AuditLog при переходе
     false→true (см. _maybe_log_stale_transition).

Этап НЕ персистит potentially_stale в БД: всё вычисляется на лету.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Campaign,
    CampaignStateListItem,
    CampaignStateValue,
    CampaignStateVersion,
    Document,
)
from shared_contracts.models import CampaignStateStaleStatus

logger = logging.getLogger(__name__)


# Redis-ключ для отслеживания предыдущего stale-снимка кампании.
# Используется для AuditLog: пишем только на переходе false→true или при
# появлении нового stale-документа. TTL 1 час — больше polling interval (30s).
_PREV_STALE_KEY_TPL = "campaign:{campaign_id}:prev_stale"
_PREV_STALE_TTL_SEC = 3600


# ---------------------------------------------------------------------------
# Typed exceptions (минимальный набор; большинство ошибок идёт через 404
# на стороне роутера, как в campaign_state_value_service)
# ---------------------------------------------------------------------------


class CampaignStateStaleError(Exception):
    """Base for stale-service errors."""

    code: str = "campaign_state_stale_error"
    http_status: int = 400

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


class CampaignNotFoundError(CampaignStateStaleError):
    code, http_status = "campaign_not_found", 404


# ---------------------------------------------------------------------------
# Source_ref parsing
# ---------------------------------------------------------------------------


# Локальный regex: дублирует _SOURCE_REF_RE из campaign_state_value_service,
# чтобы stale-service не зависел от value_service и не поднимал лишних импортов.
_FILE_REF_RE_PREFIX = "file:"


def _parse_file_refs(source_refs: list[str]) -> set[str]:
    """Извлечь document_id из source_refs формата `file:<uuid>:sha:<hex>`."""
    doc_ids: set[str] = set()
    for ref in source_refs:
        if not isinstance(ref, str):
            continue
        if not ref.startswith(_FILE_REF_RE_PREFIX):
            continue
        parts = ref.split(":")
        if len(parts) != 4:
            continue
        _, doc_id, sha_label, _sha = parts
        if sha_label != "sha" or not doc_id:
            continue
        doc_ids.add(doc_id)
    return doc_ids


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CampaignStateStaleService:
    """Service для вычисления potentially_stale Campaign State."""

    async def assert_campaign_exists(
        self,
        db: AsyncSession,
        campaign_id: uuid.UUID,
    ) -> Campaign:
        campaign = await db.get(Campaign, campaign_id)
        if campaign is None:
            raise CampaignNotFoundError(str(campaign_id))
        return campaign

    async def compute_stale_status(
        self,
        db: AsyncSession,
        redis: Any,
        campaign_id: uuid.UUID,
    ) -> CampaignStateStaleStatus:
        """Вычислить potentially_stale для активной версии Campaign State.

        Возвращает CampaignStateStaleStatus. Никогда не выбрасывает на пустых
        данных: кампания без state version → potentially_stale=False, пустой
        список. Кампания не найдена → CampaignNotFoundError (404).
        """
        await self.assert_campaign_exists(db, campaign_id)

        version = await _latest_version(db, campaign_id)
        checked_at = datetime.now(timezone.utc)

        if version is None:
            return CampaignStateStaleStatus(
                potentially_stale=False,
                stale_documents=[],
                active_state_version=None,
                checked_at=checked_at,
            )

        doc_ids = await _collect_source_doc_ids(db, version.id)
        if not doc_ids:
            return CampaignStateStaleStatus(
                potentially_stale=False,
                stale_documents=[],
                active_state_version=version.state_version,
                checked_at=checked_at,
            )

        documents = await _load_documents(db, doc_ids)
        stale_doc_ids = await _detect_stale_documents(
            redis=redis,
            documents=documents,
        )

        status = CampaignStateStaleStatus(
            potentially_stale=bool(stale_doc_ids),
            stale_documents=sorted(stale_doc_ids),
            active_state_version=version.state_version,
            checked_at=checked_at,
        )

        await _maybe_log_stale_transition(
            redis=redis,
            db=db,
            campaign_id=campaign_id,
            status=status,
        )

        logger.info(
            "campaign_state_stale.compute: campaign=%s state_version=%s "
            "stale=%d stale_documents=%s",
            campaign_id,
            version.state_version,
            len(stale_doc_ids),
            status.stale_documents,
        )

        return status


campaign_state_stale_service = CampaignStateStaleService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _latest_version(
    db: AsyncSession, campaign_id: uuid.UUID
) -> CampaignStateVersion | None:
    stmt = (
        select(CampaignStateVersion)
        .where(CampaignStateVersion.campaign_id == campaign_id)
        .order_by(CampaignStateVersion.state_version.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _collect_source_doc_ids(
    db: AsyncSession,
    version_id: uuid.UUID,
) -> set[str]:
    """Собрать уникальные document_id из source_refs values + list_items."""
    doc_ids: set[str] = set()

    values_stmt = select(CampaignStateValue.source_refs).where(
        CampaignStateValue.version_id == version_id,
    )
    for row in (await db.execute(values_stmt)).scalars().all():
        doc_ids.update(_parse_file_refs(list(row or [])))

    items_stmt = select(CampaignStateListItem.source_refs).where(
        CampaignStateListItem.version_id == version_id,
    )
    for row in (await db.execute(items_stmt)).scalars().all():
        doc_ids.update(_parse_file_refs(list(row or [])))

    return doc_ids


async def _load_documents(
    db: AsyncSession,
    doc_ids: set[str],
) -> list[Document]:
    if not doc_ids:
        return []
    stmt = select(Document).where(Document.id.in_(doc_ids))
    return list((await db.execute(stmt)).scalars().all())


def _is_pdf(document: Document) -> bool:
    """PDF-защита: state source_refs теоретически не должен содержать PDF
    (initial/patch валидация отсекает), но явно проверяем здесь.
    """
    path = (document.source_path or "").lower()
    return not path.endswith(".md")


async def _detect_stale_documents(
    redis: Any,
    documents: list[Document],
) -> list[str]:
    """Вернуть document_id, которые считаются stale.

    Алгоритм:
      - PDF → skip
      - Document.status != indexed → stale
      - иначе читаем vault:{vault_id}:files из Redis.
        - ключ отсутствует целиком → не сигнализируем (indexer cold start).
        - ключ есть, но файла нет → stale (deleted).
        - ключ есть, index_status ∈ {pending, stale, deleted} → stale.
        - ключ есть, indexed_md5 != Document.md5 → stale.
        - иначе → fresh.
    """
    if redis is None:
        return []

    stale: list[str] = []
    # cache[ vault_id ] = (raw_exists, {path: entry}) — нужно отличать
    # "ключ отсутствует" от "ключ есть, но файл удалён".
    cache: dict[str, tuple[bool, dict[str, dict[str, Any]]]] = {}

    for doc in documents:
        doc_id = str(doc.id)

        if _is_pdf(doc):
            continue

        if doc.status != "indexed":
            stale.append(doc_id)
            continue

        # Ленивая загрузка vault-кэша по vault_id.
        if doc.vault_id not in cache:
            cache[doc.vault_id] = await _read_vault_cache(redis, doc.vault_id)

        key_exists, vault_files = cache[doc.vault_id]
        if not key_exists:
            # Ключа нет — indexer ещё не rebuild'ил vault. Не сигнализируем
            # false positive.
            continue

        entry = vault_files.get(doc.source_path)
        if entry is None:
            # Ключ есть, файла нет → удалён с диска.
            stale.append(doc_id)
            continue

        index_status = str(entry.get("index_status", "")).strip().lower()
        if index_status in ("pending", "stale", "deleted"):
            stale.append(doc_id)
            continue

        indexed_md5 = str(entry.get("indexed_md5", "")).strip()
        if indexed_md5 and indexed_md5 != doc.md5:
            stale.append(doc_id)
            continue

    return stale


async def _read_vault_cache(
    redis: Any,
    vault_id: str,
) -> tuple[bool, dict[str, dict[str, Any]]]:
    """Прочитать vault:{vault_id}:files из Redis.

    Возвращает (key_exists, entries). entries: {relative_path: entry_dict}.

    key_exists=False если ключа нет в Redis или Redis недоступен —
    отличает cold-start от "файл удалён с диска".
    """
    try:
        raw = await redis.hgetall(f"vault:{vault_id}:files")
    except Exception:
        logger.warning(
            "campaign_state_stale: Redis read failed vault_id=%s",
            vault_id,
            exc_info=True,
        )
        return False, {}

    if not raw:
        return False, {}

    result: dict[str, dict[str, Any]] = {}
    for path, value in raw.items():
        if path == "__empty__":
            continue
        try:
            result[path] = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
    return True, result


# ---------------------------------------------------------------------------
# AuditLog transition tracking
# ---------------------------------------------------------------------------


async def _maybe_log_stale_transition(
    redis: Any,
    db: AsyncSession,
    campaign_id: uuid.UUID,
    status: CampaignStateStaleStatus,
) -> None:
    """Записать AuditLog при переходе false→true или появлении нового stale.

    prev_stale хранится в Redis-ключе `campaign:{id}:prev_stale` (JSON):
      {"potentially_stale": bool, "stale_documents": list[str]}

    Условия записи:
      - prev отсутствует И potentially_stale=True → пишем (первая фиксация)
      - prev.potentially_stale=False И status.potentially_stale=True → пишем
      - prev.potentially_stale=True И set(prev.stale_documents) !=
        set(status.stale_documents) → пишем (новый stale)
      - иначе → не пишем

    Сбрасываем prev в None при potentially_stale=False, чтобы следующий
    переход true корректно зафиксировался.
    """
    if redis is None:
        return

    key = _PREV_STALE_KEY_TPL.format(campaign_id=campaign_id)

    try:
        prev_raw = await redis.get(key)
    except Exception:
        logger.warning(
            "campaign_state_stale: Redis prev_stale read failed campaign=%s",
            campaign_id,
            exc_info=True,
        )
        return

    prev: dict[str, Any] | None = None
    if prev_raw:
        try:
            prev = json.loads(prev_raw)
        except (TypeError, json.JSONDecodeError):
            prev = None

    should_log = _should_log_transition(prev, status)

    new_value = json.dumps(
        {
            "potentially_stale": status.potentially_stale,
            "stale_documents": status.stale_documents,
        },
        ensure_ascii=False,
    )

    try:
        await redis.set(key, new_value, ex=_PREV_STALE_TTL_SEC)
    except Exception:
        logger.warning(
            "campaign_state_stale: Redis prev_stale write failed campaign=%s",
            campaign_id,
            exc_info=True,
        )

    if should_log:
        await _write_stale_audit_log(db, campaign_id, status)


def _should_log_transition(
    prev: dict[str, Any] | None,
    status: CampaignStateStaleStatus,
) -> bool:
    if not status.potentially_stale:
        return False
    if prev is None:
        return True
    if not prev.get("potentially_stale"):
        return True
    prev_docs = set(prev.get("stale_documents") or [])
    cur_docs = set(status.stale_documents)
    return prev_docs != cur_docs


async def _write_stale_audit_log(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    status: CampaignStateStaleStatus,
) -> None:
    """INSERT AuditLog: action=campaign_state_potentially_stale.

    Не блокирует основной путь: ошибка записи логируется и проглатывается.
    """
    try:
        await db.execute(
            insert(AuditLog).values(
                id=str(uuid.uuid4()),
                action="campaign_state_potentially_stale",
                entity_type="campaign",
                entity_id=str(campaign_id),
                actor=None,
                payload={
                    "stale_documents": status.stale_documents,
                    "active_state_version": status.active_state_version,
                    "checked_at": status.checked_at.isoformat(),
                },
            )
        )
        await db.commit()
        logger.info(
            "campaign_state_stale: audit transition logged campaign=%s "
            "stale_documents=%s",
            campaign_id,
            status.stale_documents,
        )
    except Exception:
        logger.warning(
            "campaign_state_stale: AuditLog write failed campaign=%s",
            campaign_id,
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception as exc:  # noqa: BLE001  # best-effort rollback
            logger.debug("rollback failed: %s", exc)