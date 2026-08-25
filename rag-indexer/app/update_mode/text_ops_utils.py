"""Shared text-operation utilities.

CHAR_MAP_MARKER re-exported from shared_contracts.text.markers (canonical
location). ``build_anchor_pattern`` remains here — it's orthogonal to the
preprocessing refactor (used only by token_anchor / text_ops internally).

New code should import ``CHAR_MAP_MARKER`` directly from
``shared_contracts.text.markers``.
"""
from __future__ import annotations

import re

# Re-export для обратной совместимости с token_anchor.py и text_ops.py.
# Канонический путь: shared_contracts.text.markers.CHAR_MAP_MARKER.
from shared_contracts.text.markers import CHAR_MAP_MARKER  # noqa: F401


def build_anchor_pattern(anchor_value: str) -> re.Pattern[str]:
    """Build a whitespace-tolerant regex that matches *anchor_value* in text.

    The pattern splits *anchor_value* on whitespace and re-joins the escaped
    tokens with ``\\s+``, so the regex matches the same words even when the
    original and the target string differ in whitespace (spaces, newlines,
    tabs, etc.).

    Parameters
    ----------
    anchor_value:
        The anchor string as produced by the LLM (normalised text).  May
        contain arbitrary internal whitespace.

    Returns
    -------
    re.Pattern[str]
        A compiled pattern with ``re.DOTALL`` so that ``\\s+`` also matches
        newlines inside multi-line anchors.

    Examples
    --------
    >>> p = build_anchor_pattern("hello   world")
    >>> bool(p.search("hello\\nworld"))
    True
    """
    tokens = re.split(r"\s+", anchor_value.strip())
    tokens = [t for t in tokens if t]
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    return re.compile(pattern, re.DOTALL)