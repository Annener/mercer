"""Tests for applier._apply_vault() with multiple ops per file.

TODO: implement
  - two intents on the same file both applied, result is correct
  - ops applied in _OPERATION_ORDER (delete before append)
  - AnchorNotFoundError on second op → FAILED, manual_recovery_required=True
    when first file already written
  - applied_count equals total ops applied, not files written
  - single git commit for the whole vault
"""
import pytest


@pytest.mark.skip(reason="TODO: not yet implemented")
def test_placeholder() -> None:
    pass
