"""Cleanup-script: удаляет все campaign_state_versions с source_kind='patch'.

Зачем:
    В предыдущих версиях бэкенда failed apply мог оставить осиротевшие
    patch versions без values и list_items. По умолчанию cleanup
    удаляет ВСЕ patch versions — это безопасно для failed patches,
    но может затронуть успешные patches с данными.

Использование:
    # Dry-run (по умолчанию) — только отчёт, без удаления:
    python scripts/cleanup_orphan_state_versions.py

    # Применить удаление:
    python scripts/cleanup_orphan_state_versions.py --apply

WARNING:
    Удаляет ВСЕ patch versions для ВСЕХ кампаний. Перед --apply
    проверьте dry-run отчёт. Если нужно сохранить какие-то patch versions,
    используйте более точечный скрипт или ручной SQL.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Подключаем rag-backend как importable. Запускается из корня репо:
#   cd mercer && python scripts/cleanup_orphan_state_versions.py
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rag-backend")),
)
from app.db.session import DATABASE_URL  # type: ignore[import-not-found]

logger = logging.getLogger("cleanup_orphan_state_versions")


async def find_patch_versions(conn) -> list[dict]:
    """Найти все patch versions с метаданными (values/list_items count)."""
    result = await conn.execute(
        text(
            """
            SELECT
                v.id,
                v.campaign_id,
                c.name AS campaign_name,
                v.state_version,
                v.config_version,
                v.source_kind,
                v.created_at,
                (SELECT COUNT(*) FROM campaign_state_values
                 WHERE version_id = v.id) AS values_count,
                (SELECT COUNT(*) FROM campaign_state_list_items
                 WHERE version_id = v.id) AS list_items_count
            FROM campaign_state_versions v
            JOIN campaigns c ON c.id = v.campaign_id
            WHERE v.source_kind = 'patch'
            ORDER BY v.created_at DESC
            """
        )
    )
    return [dict(row._mapping) for row in result]


async def delete_version(conn, version_id: str) -> None:
    """Удалить version и связанные values/list_items (FK CASCADE)."""
    # Foreign keys: campaign_state_values.version_id ON DELETE CASCADE,
    # campaign_state_list_items.version_id ON DELETE CASCADE,
    # поэтому удаление version автоматически уберёт зависимости.
    # Но для надёжности удаляем явно.
    await conn.execute(
        text("DELETE FROM campaign_state_values WHERE version_id = :vid"),
        {"vid": version_id},
    )
    await conn.execute(
        text("DELETE FROM campaign_state_list_items WHERE version_id = :vid"),
        {"vid": version_id},
    )
    await conn.execute(
        text("DELETE FROM campaign_state_versions WHERE id = :vid"),
        {"vid": version_id},
    )


async def main(apply: bool) -> int:
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            versions = await find_patch_versions(conn)

            if not versions:
                logger.info("No patch versions found. Nothing to clean up.")
                return 0

            logger.info(
                "Found %d patch version(s):",
                len(versions),
            )
            for v in versions:
                logger.info(
                    "  - %s v%d (id=%s, values=%d, list_items=%d, created=%s)",
                    v["campaign_name"],
                    v["state_version"],
                    v["id"],
                    v["values_count"],
                    v["list_items_count"],
                    v["created_at"],
                )

            if not apply:
                logger.info(
                    "Dry-run mode. Re-run with --apply to delete. "
                    "WARNING: this will delete ALL patch versions, "
                    "including any with values/list_items.",
                )
                return 0

            total_values = sum(v["values_count"] for v in versions)
            total_list_items = sum(v["list_items_count"] for v in versions)
            logger.warning(
                "DELETING %d patch version(s) "
                "(may include %d value(s) and %d list_item(s))",
                len(versions),
                total_values,
                total_list_items,
            )
            for v in versions:
                logger.info(
                    "Deleting %s v%d (id=%s)",
                    v["campaign_name"],
                    v["state_version"],
                    v["id"],
                )
                await delete_version(conn, str(v["id"]))
            logger.info("Done. Deleted %d patch version(s).", len(versions))
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cleanup orphan patch versions (dry-run by default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the versions. Default is dry-run.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stdout,
    )
    sys.exit(asyncio.run(main(apply=args.apply)))
