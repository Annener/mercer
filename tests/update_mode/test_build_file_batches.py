"""Tests for rag-backend _build_file_batches() helper.

TODO: implement
  - single intent → one batch, one op
  - two intents on same file → one batch, two ops sorted by resolve_order
  - two intents on different files → two batches
  - expected_sha256 only on ops[0] for UPDATE batches
  - backward-compat: change without operation field → single APPEND_TO_FILE op
    with content=proposed_content
  - backward-compat: two legacy changes on same file → warning + last change wins
"""
import pytest


@pytest.mark.skip(reason="TODO: not yet implemented")
def test_placeholder() -> None:
    pass
