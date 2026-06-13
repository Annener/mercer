from __future__ import annotations

# Embedding cache has been removed.
# The cache was causing stale-vector bugs: its key depended only on chunk
# text + model + dimensions, not on the parent file's md5. Unchanged chunks
# from a re-indexed file would silently reuse old vectors even after the
# file was modified.
#
# Document-level deduplication (md5 + mtime in the documents table) already
# prevents unnecessary re-embedding for truly unchanged files, so this cache
# provided no real benefit.
#
# Stubs are kept so any remaining imports resolve without error.
# This file can be deleted entirely once all call sites are cleaned up.


def get_cached(text: str, model_name: str, dimensions: int) -> None:  # noqa: ARG001
    """No-op stub. Always returns None (cache miss)."""
    return None


def save_cache(  # noqa: ARG001
    text: str,
    model_name: str,
    dimensions: int,
    vector: list[float],
) -> None:
    """No-op stub. Does nothing."""
    return
