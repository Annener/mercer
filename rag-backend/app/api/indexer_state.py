"""indexer_state.py — Redis-direct endpoints для состояния индексации.

GET  /index-tasks/{task_id}/state       — состояние задачи (читает Redis напрямую)
GET  /vaults/{vault_id}/index-state     — сводка по vault-кэшу в Redis
GET  /api/v1/indexer/tasks              — НОВЫЙ: глобальный статус всех активных задач
                                          + последняя завершённая (без привязки к vault)
POST /api/v1/indexer/tasks/{id}/cancel  — НОВЫЙ: запросить отмену задачи

rag-backend НЕ импортирует RedisStateManager из rag-indexer.
Все чтения выполняются через redis.asyncio напрямую.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(tags=["indexer-state"])


# ---------------------------------------------------------------------------
# Существующие endpoints — не изменены
# ---------------------------------------------------------------------------

@router.get("/index-tasks/{task_id}/state")
async def get_task_state(task_id: str, request: Request) -> dict:
    """Возвращает состояние задачи индексации, читая Redis напрямую."""
    redis = request.app.state.redis

    task_data = await redis.hgetall(f"task:{task_id}")
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    files_raw = await redis.hgetall(f"task:{task_id}:files")
    files = {path: json.loads(data) for path, data in files_raw.items()}

    return {**task_data, "files": files}


@router.get("/vaults/{vault_id}/index-state")
async def get_vault_index_state(vault_id: str, request: Request) -> dict:
    """Возвращает сводку по состоянию файлов vault'а из Redis-кэша."""
    redis = request.app.state.redis

    files_raw = await redis.hgetall(f"vault:{vault_id}:files")
    if not files_raw:
        raise HTTPException(status_code=404, detail="Vault not found in cache")

    files = {path: json.loads(data) for path, data in files_raw.items()}

    by_status: dict[str, int] = {}
    for f in files.values():
        s = f.get("index_status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "vault_id": vault_id,
        "files_total": len(files),
        "by_status": by_status,
        "files": files,
    }


# ---------------------------------------------------------------------------
# НОВЫЙ: глобальный статус индексации для экрана «Файлы»
# ---------------------------------------------------------------------------

@router.get("/indexer/tasks")
async def get_all_indexer_tasks(request: Request) -> dict:
    """Возвращает все активные задачи + последнюю завершённую.

    Не требует знания task_id. Читает:
      - SET  active_tasks        — множество task_id активных задач
      - STRING last_task_id      — id последней завершённой/отменённой задачи
      - HASH task:{id}           — метаданные задачи
      - HASH task:{id}:files     — состояние файлов

    Response schema:
    {
      "tasks": [
        {
          "task_id":        str,
          "vault_id":       str,
          "status":         "running" | "done" | "error" | "cancelled",
          "started_at":     str (ISO 8601),
          "finished_at":    str (ISO 8601 или ""),
          "files_total":    int,
          "files_to_index": int,
          "files_skipped":  int,
          "files_done":     int,
          "error":          str,
          "files": {
            "relative/path.md": {
              "stage":        str,
              "chunks_total": int,
              "chunks_done":  int,
              "error":        str | null
            }
          }
        }
      ],
      "has_active": bool
    }
    """
    redis = request.app.state.redis

    # 1. Активные task_id из SET active_tasks
    active_ids: set[str] = await redis.smembers("active_tasks") or set()

    # 2. Если активных нет — подтягиваем last_task_id как fallback
    #    (показывает финальный статус последней задачи при следующем открытии страницы)
    extra_ids: set[str] = set()
    if not active_ids:
        last_task_id = await redis.get("last_task_id")
        if last_task_id:
            extra_ids.add(last_task_id)

    all_ids = active_ids | extra_ids
    if not all_ids:
        return {"tasks": [], "has_active": False}

    # 3. Batch-читаем метаданные всех тасков через pipeline (1 round-trip)
    ordered_ids = list(all_ids)
    pipe = redis.pipeline()
    for tid in ordered_ids:
        pipe.hgetall(f"task:{tid}")
    task_metas: list[dict] = await pipe.execute()

    # 4. Batch-читаем файлы для всех тасков через второй pipeline (1 round-trip)
    pipe2 = redis.pipeline()
    for tid in ordered_ids:
        pipe2.hgetall(f"task:{tid}:files")
    task_files_list: list[dict] = await pipe2.execute()

    tasks = []
    has_active = False

    for tid, meta, files_raw in zip(ordered_ids, task_metas, task_files_list):
        if not meta:
            # Ключ протух или не существует — пропускаем
            continue

        status = meta.get("status", "unknown")
        if status == "running":
            has_active = True

        # Парсим файлы с graceful fallback на повреждённые записи
        files: dict[str, dict] = {}
        for path, raw in (files_raw or {}).items():
            try:
                files[path] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                files[path] = {"stage": "unknown", "error": "parse error"}

        tasks.append({
            "task_id":        tid,
            "vault_id":       meta.get("vault_id", ""),
            "status":         status,
            "started_at":     meta.get("started_at", ""),
            "finished_at":    meta.get("finished_at", ""),
            "files_total":    _to_int(meta.get("files_total", 0)),
            "files_to_index": _to_int(meta.get("files_to_index", 0)),
            "files_skipped":  _to_int(meta.get("files_skipped", 0)),
            "files_done":     _to_int(meta.get("files_done", 0)),
            "error":          meta.get("error", ""),
            "files":          files,
        })

    # Сортировка: running задачи вперёд, внутри группы — по started_at desc
    tasks.sort(key=lambda t: (
        0 if t["status"] == "running" else 1,
        t.get("started_at", ""),
    ), reverse=False)
    # Внутри running-группы сортируем по started_at desc (новее = первее)
    running = [t for t in tasks if t["status"] == "running"]
    finished = [t for t in tasks if t["status"] != "running"]
    running.sort(key=lambda t: t.get("started_at", ""), reverse=True)
    finished.sort(key=lambda t: t.get("started_at", ""), reverse=True)
    tasks = running + finished

    return {"tasks": tasks, "has_active": has_active}


# ---------------------------------------------------------------------------
# НОВЫЙ: отмена задачи индексации
# ---------------------------------------------------------------------------

@router.post("/indexer/tasks/{task_id}/cancel")
async def cancel_indexer_task(task_id: str, request: Request) -> dict:
    """Запрашивает отмену задачи индексации.

    Устанавливает ключ cancel:{task_id} в Redis.
    Воркер rag-indexer проверяет этот ключ в is_cancelled() и завершает задачу.

    Возвращает 404 если задача не найдена или уже завершена.
    """
    redis = request.app.state.redis

    # Проверяем что задача существует и ещё активна
    task_data = await redis.hgetall(f"task:{task_id}")
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")

    status = task_data.get("status", "unknown")
    if status not in ("running", "queued"):
        return {"cancelled": False, "task_id": task_id, "reason": f"Task is already {status}"}

    # Устанавливаем флаг отмены — воркер увидит его на следующей итерации
    await redis.set(f"cancel:{task_id}", "1", ex=3600)
    logger.info("Cancel requested for task_id=%s", task_id)

    return {"cancelled": True, "task_id": task_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_int(v: object) -> int:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
