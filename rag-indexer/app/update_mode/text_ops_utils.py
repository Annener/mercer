"""Shared text-operation utilities for the update-mode subsystem.

This module exposes helpers that are needed by both *text_ops.py* and the
Token-Map Anchoring layer (token_anchor.py, Фаза 2).  Keeping them here
avoids importing private symbols across module boundaries.

Public API
----------
build_anchor_pattern(anchor_value) -> re.Pattern[str]
    Build a whitespace-tolerant regex for locating *anchor_value* inside
    a larger text string.
"""
from __future__ import annotations

import re


def build_anchor_pattern(anchor_value: str) -> "re.Pattern[str]":
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
