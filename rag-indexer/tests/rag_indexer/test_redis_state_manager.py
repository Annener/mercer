"""Unit-тесты RedisStateManager.

Запуск:
    pytest tests/rag_indexer/test_redis_state_manager.py -v
Зависимости:
    fakeredis[aioredis]>=2.0  (в requirements-dev.txt)
"""
from __future__ import annotations

import json

import fakeredis.aioredis as fakeredis
import pytest

from parser.state.redis_state_manager import RedisStateManager


@pytest.fixture
def redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mgr(redis: fakeredis.FakeRedis) -> RedisStateManager:
    return RedisStateManager(redis)


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_sets_status_running(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t1", "v1", [{"relative_path": "a.pdf"}], files_skipped=0, files_total=1)
    status = await redis.hget("task:t1", "status")
    assert status == "running"


@pytest.mark.asyncio
async def test_create_task_sets_ttl(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t2", "v1", [], files_skipped=0, files_total=0)
    ttl = await redis.ttl("task:t2")
    assert 86390 < ttl <= 86400


@pytest.mark.asyncio
async def test_create_task_adds_to_active_tasks(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t3", "v1", [], files_skipped=0, files_total=0)
    members = await redis.smembers("active_tasks")
    assert "t3" in members


@pytest.mark.asyncio
async def test_create_task_files_hash_populated(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    files = [{"relative_path": "doc.pdf"}, {"relative_path": "img.png"}]
    await mgr.create_task("t4", "v1", files, files_skipped=1, files_total=3)
    keys = await redis.hkeys("task:t4:files")
    assert "doc.pdf" in keys
    assert "img.png" in keys


# ---------------------------------------------------------------------------
# update_file_stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_file_stage(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t5", "v1", [{"relative_path": "a.pdf"}], 0, 1)
    await mgr.update_file_stage("t5", "a.pdf", stage="indexing", chunks_total=10, chunks_done=3)
    raw = await redis.hget("task:t5:files", "a.pdf")
    data = json.loads(raw)
    assert data["stage"] == "indexing"
    assert data["chunks_total"] == 10
    assert data["chunks_done"] == 3


# ---------------------------------------------------------------------------
# increment_files_done
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_increment_files_done(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t6", "v1", [], 0, 2)
    await mgr.increment_files_done("t6")
    await mgr.increment_files_done("t6")
    val = await redis.hget("task:t6", "files_done")
    assert int(val) == 2


# ---------------------------------------------------------------------------
# mark_task_done
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_task_done(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t7", "v1", [], 0, 0)
    await mgr.mark_task_done("t7")
    status = await redis.hget("task:t7", "status")
    assert status == "done"
    members = await redis.smembers("active_tasks")
    assert "t7" not in members


@pytest.mark.asyncio
async def test_mark_task_done_with_error(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("t8", "v1", [], 0, 0)
    await mgr.mark_task_done("t8", error="connection refused")
    status = await redis.hget("task:t8", "status")
    assert status == "error"
    error = await redis.hget("task:t8", "error")
    assert "connection refused" in error


# ---------------------------------------------------------------------------
# mark_task_cancelled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_task_cancelled(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    await mgr.create_task("tc", "v1", [], 0, 0)
    await mgr.mark_task_cancelled("tc")
    status = await redis.hget("task:tc", "status")
    assert status == "cancelled"
    members = await redis.smembers("active_tasks")
    assert "tc" not in members


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_cancel_and_is_cancelled(mgr: RedisStateManager) -> None:
    await mgr.request_cancel("t9")
    assert await mgr.is_cancelled("t9") is True


@pytest.mark.asyncio
async def test_is_cancelled_false_before_request(mgr: RedisStateManager) -> None:
    assert await mgr.is_cancelled("t_none") is False


@pytest.mark.asyncio
async def test_clear_cancel(mgr: RedisStateManager) -> None:
    await mgr.request_cancel("t10")
    await mgr.clear_cancel("t10")
    assert await mgr.is_cancelled("t10") is False


# ---------------------------------------------------------------------------
# rebuild_vault_cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_vault_cache_indexed(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    pg_docs = [{"relative_path": "a.pdf", "md5": "aaa", "status": "indexed", "chunks_count": 5}]
    disk_files = [{"relative_path": "a.pdf", "checksum": "aaa"}]
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "a.pdf")
    assert json.loads(raw)["index_status"] == "indexed"


@pytest.mark.asyncio
async def test_rebuild_vault_cache_stale(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    pg_docs = [{"relative_path": "b.pdf", "md5": "old", "status": "indexed", "chunks_count": 3}]
    disk_files = [{"relative_path": "b.pdf", "checksum": "new"}]
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "b.pdf")
    assert json.loads(raw)["index_status"] == "stale"


@pytest.mark.asyncio
async def test_rebuild_vault_cache_deleted(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    pg_docs = [{"relative_path": "c.pdf", "md5": "ccc", "status": "indexed", "chunks_count": 2}]
    disk_files = []  # файла нет на диске
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "c.pdf")
    assert json.loads(raw)["index_status"] == "deleted"


@pytest.mark.asyncio
async def test_rebuild_vault_cache_pending(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    pg_docs: list[dict] = []  # нет в PostgreSQL
    disk_files = [{"relative_path": "d.pdf", "checksum": "ddd"}]
    await mgr.rebuild_vault_cache("v1", pg_docs, disk_files)
    raw = await redis.hget("vault:v1:files", "d.pdf")
    assert json.loads(raw)["index_status"] == "pending"


@pytest.mark.asyncio
async def test_rebuild_vault_cache_no_ttl(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    """vault:*:files не должен иметь TTL."""
    await mgr.rebuild_vault_cache("v2", [], [])
    ttl = await redis.ttl("vault:v2:files")
    assert ttl == -1  # -1 = нет TTL


# ---------------------------------------------------------------------------
# get_task_state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_state_returns_none_for_unknown(mgr: RedisStateManager) -> None:
    result = await mgr.get_task_state("unknown")
    assert result is None


@pytest.mark.asyncio
async def test_get_task_state_returns_dict(mgr: RedisStateManager) -> None:
    await mgr.create_task("tgs", "vault-x", [{"relative_path": "f.pdf"}], 0, 1)
    state = await mgr.get_task_state("tgs")
    assert state is not None
    assert state["status"] == "running"
    assert state["vault_id"] == "vault-x"
    assert "f.pdf" in state["files"]


# ---------------------------------------------------------------------------
# mark_file_indexed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_file_indexed(mgr: RedisStateManager, redis: fakeredis.FakeRedis) -> None:
    pg_docs = [{"relative_path": "e.pdf", "md5": "old", "status": "indexed", "chunks_count": 3}]
    disk_files = [{"relative_path": "e.pdf", "checksum": "old"}]
    await mgr.rebuild_vault_cache("vx", pg_docs, disk_files)
    await mgr.mark_file_indexed("vx", "e.pdf", md5="new_md5", chunks_total=10)
    raw = await redis.hget("vault:vx:files", "e.pdf")
    entry = json.loads(raw)
    assert entry["index_status"] == "indexed"
    assert entry["indexed_md5"] == "new_md5"
    assert entry["chunks_total"] == 10
