#!/usr/bin/env python
"""
migrate_pipelines.py — Миграция JSONB-данных пайплайнов на новую схему (Stage 2).

KONVERTIRUET steps[].order и steps[].is_final → steps[].step_id и steps[].after_step_ids.

CAUTION: запускай только после `alembic upgrade head` (миграция 0019).

USAGE:
    # Просмотр изменений без записи:
    python tools/migrate_pipelines.py --dry-run

    # Применение миграции в БД:
    python tools/migrate_pipelines.py --apply

    # Показать только pipeline_id с заданным domain_id:
    python tools/migrate_pipelines.py --dry-run --domain-id dnd

EXIT CODES:
    0 — OK
    1 — есть пиплайны со старыми полями (выход в dry-run)
    2 — фатальная ошибка

МИГРАЦИОННАЯ ЛОГИКА (steps):
    Старая схема (есть `order`):
        steps = [
            {"order": 1, "type": "retrieval", ...},
            {"order": 2, "type": "retrieval", ...},
            {"order": 3, "type": "final",     ...},
        ]
    Новая схема:
        steps = [
            {"step_id": "step_1", "after_step_ids": [],           "type": "retrieval", ...},
            {"step_id": "step_2", "after_step_ids": ["step_1"],   "type": "retrieval", ...},
            # шаг с type=="final" превращается в FinalComposition (не в steps)
        ]
    Если `order` отсутствует, но есть `step_id` — пайплайн уже мигрирован.
    Если `step_id` тоже отсутствует — пайплайн невалиден (фатал).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _get_dsn() -> str:
    """Build DSN from env vars (same as rag-backend uses)."""
    return (
        f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
        f"port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"dbname={os.environ.get('POSTGRES_DB', 'mercer')} "
        f"user={os.environ.get('POSTGRES_USER', 'mercer')} "
        f"password={os.environ.get('POSTGRES_PASSWORD', 'mercer')}"
    )


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------

def _step_needs_migration(step: dict[str, Any]) -> bool:
    """Return True if the step uses old-schema fields (order / is_final)."""
    return "order" in step or "is_final" in step


def _migrate_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """
    Convert old-schema steps list to new-schema.

    Returns:
        (new_steps, final_composition_override)
        final_composition_override is not-None only when a type=="final" step
        is found; its system_prompt overwrites final_composition.system_prompt.
    """
    # Sort by order (ascending); steps without order keep their position.
    steps_sorted = sorted(
        [s for s in steps if s.get("type") != "final"],
        key=lambda s: s.get("order", 0),
    )
    final_steps = [s for s in steps if s.get("type") == "final"]
    final_override: dict[str, Any] | None = None
    if final_steps:
        final_override = {"system_prompt": final_steps[0].get("system_prompt", "")}

    new_steps: list[dict[str, Any]] = []
    for idx, step in enumerate(steps_sorted):
        new_step = {k: v for k, v in step.items() if k not in ("order", "is_final")}
        # Generate step_id if missing
        if "step_id" not in new_step:
            new_step["step_id"] = f"step_{idx + 1}"
        # Build after_step_ids: previous step in the sorted sequence
        if "after_step_ids" not in new_step:
            new_step["after_step_ids"] = ([new_steps[-1]["step_id"]] if idx > 0 else [])
        # Ensure output_format present
        new_step.setdefault("output_format", "text")
        new_steps.append(new_step)

    return new_steps, final_override


def _migrate_final_composition(
    final_composition: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply final_composition overrides from migrated final step."""
    if override is None:
        return final_composition
    return {**final_composition, **override}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate pipelines JSONB to new DAG schema.")
    parser.add_argument("--dry-run", action="store_true", help="Print diff without writing to DB")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--domain-id", default=None, help="Filter by domain_id")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        return 2

    dsn = _get_dsn()
    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:
        print(f"[ERROR] Cannot connect to DB: {exc}", file=sys.stderr)
        return 2

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Fetch pipelines
    if args.domain_id:
        cur.execute(
            "SELECT id, pipeline_id, domain_id, version, steps, final_composition "
            "FROM pipelines WHERE domain_id = %s ORDER BY domain_id, pipeline_id, version",
            (args.domain_id,),
        )
    else:
        cur.execute(
            "SELECT id, pipeline_id, domain_id, version, steps, final_composition "
            "FROM pipelines ORDER BY domain_id, pipeline_id, version"
        )

    rows = cur.fetchall()
    if not rows:
        print("No pipelines found.")
        conn.close()
        return 0

    needs_migration: list[dict] = []
    already_migrated: list[str] = []
    errors: list[str] = []

    for row in rows:
        steps = row["steps"]
        if not isinstance(steps, list):
            errors.append(f"{row['pipeline_id']} v{row['version']}: steps is not a list")
            continue

        if any(_step_needs_migration(s) for s in steps):
            needs_migration.append(dict(row))
        else:
            all_have_step_id = all("step_id" in s for s in steps)
            if all_have_step_id:
                already_migrated.append(f"{row['pipeline_id']} v{row['version']}")
            else:
                errors.append(
                    f"{row['pipeline_id']} v{row['version']}: "
                    f"steps have neither 'order' nor 'step_id' — manual fix required"
                )

    # Report
    print(f"\n=== Pipeline Migration Report ===")
    print(f"Total pipelines:     {len(rows)}")
    print(f"Already migrated:    {len(already_migrated)}")
    print(f"Needs migration:     {len(needs_migration)}")
    print(f"Errors:              {len(errors)}")

    if errors:
        print("\n[ERRORS]:")
        for e in errors:
            print(f"  ! {e}")

    if already_migrated:
        print("\n[Already migrated]:")
        for p in already_migrated:
            print(f"  ✓ {p}")

    if needs_migration:
        print("\n[To be migrated]:")
        for row in needs_migration:
            new_steps, final_override = _migrate_steps(row["steps"])
            new_fc = _migrate_final_composition(row["final_composition"] or {}, final_override)
            print(f"\n  Pipeline: {row['pipeline_id']} v{row['version']} (domain: {row['domain_id']})")
            print(f"    OLD steps ({len(row['steps'])} items):")
            for s in row["steps"]:
                marker = "[FINAL]" if s.get("type") == "final" else ""
                print(f"      order={s.get('order', '?')} step_id={s.get('step_id', '-')} type={s.get('type')} {marker}")
            print(f"    NEW steps ({len(new_steps)} items):")
            for s in new_steps:
                print(f"      step_id={s['step_id']} after={s['after_step_ids']} type={s['type']}")
            if final_override:
                print(f"    NEW final_composition (system_prompt extracted from old final step):")
                print(f"      system_prompt length: {len(new_fc.get('system_prompt', ''))} chars")

            if args.apply:
                try:
                    cur.execute(
                        "UPDATE pipelines SET steps = %s, final_composition = %s WHERE id = %s",
                        (
                            json.dumps(new_steps),
                            json.dumps(new_fc),
                            str(row["id"]),
                        ),
                    )
                except Exception as exc:
                    print(f"[ERROR] Failed to update {row['pipeline_id']}: {exc}", file=sys.stderr)
                    conn.rollback()
                    conn.close()
                    return 2

    if args.apply and needs_migration:
        conn.commit()
        print(f"\n[OK] Applied migration to {len(needs_migration)} pipeline(s).")
    elif args.dry_run and needs_migration:
        print(f"\n[DRY-RUN] No changes written. Run with --apply to commit.")
        conn.close()
        return 1  # signal: migration needed

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
