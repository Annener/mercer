"""Shared text-operation markers used by preprocessing and token-anchoring.

Канонический путь для CHAR_MAP_MARKER. Раньше жил в
rag-indexer/app/update_mode/text_ops_utils.py.

CHAR_MAP_MARKER : str
    Sentinel string used in preprocess() шаг 5 and build_char_map() шаг 5
    to temporarily mark double newlines (``\\n\\n``) before
    single-newline→space substitution.
    Must be a 2-character string whose characters never appear in
    preprocessed documents. Uses Unicode Private Use Area (PUA) code
    points U+E000 and U+E001, which are guaranteed not to survive
    preprocessor filtering (PUA is not included in _ALLOWED_RANGES).
"""
from __future__ import annotations

CHAR_MAP_MARKER: str = "\uE000\uE001"

__all__ = ["CHAR_MAP_MARKER"]