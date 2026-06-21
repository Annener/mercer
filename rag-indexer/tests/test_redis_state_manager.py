import fakeredis.aioredis
import pytest
from parser.state.redis_state_manager import RedisStateManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def mgr():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisStateManager(r)


async def test_mark_file_pending_sets_status(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 5)
    await mgr.mark_file_pending("v1", "a.md")
    entry = await mgr.get_vault_file_entry("v1", "a.md")
    assert entry["index_status"] == "pending"
    # Остальные поля сохранены
    assert entry["indexed_md5"] == "abc"
    assert entry["chunks_total"] == 5


async def test_mark_file_pending_creates_entry_if_missing(mgr):
    await mgr.mark_file_pending("v1", "new.md")
    entry = await mgr.get_vault_file_entry("v1", "new.md")
    assert entry is not None
    assert entry["index_status"] == "pending"


async def test_remove_file_from_vault_cache(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 5)
    await mgr.remove_file_from_vault_cache("v1", "a.md")
    entry = await mgr.get_vault_file_entry("v1", "a.md")
    assert entry is None


async def test_get_vault_file_entry_returns_none_for_missing(mgr):
    entry = await mgr.get_vault_file_entry("v1", "nonexistent.md")
    assert entry is None


async def test_get_all_vault_file_entries_skips_empty_sentinel(mgr):
    # Имитируем пустой vault (rebuild с пустым состоянием создаёт __empty__)
    await mgr._r.hset("vault:v1:files", "__empty__", "1")
    entries = await mgr.get_all_vault_file_entries("v1")
    assert "__empty__" not in entries
    assert entries == {}


async def test_get_all_vault_file_entries_returns_all(mgr):
    await mgr.mark_file_indexed("v1", "a.md", "abc", 3)
    await mgr.mark_file_pending("v1", "b.md")
    entries = await mgr.get_all_vault_file_entries("v1")
    assert set(entries.keys()) == {"a.md", "b.md"}
    assert entries["a.md"]["index_status"] == "indexed"
    assert entries["b.md"]["index_status"] == "pending"
