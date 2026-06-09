"""
Препроцессор текста — копия rag-indexer/parser/preprocessing/preprocessor.py.

Намеренно хранится отдельным файлом (не импортируется из rag-indexer),
чтобы sidecar оставался автономным и не зависел от структуры контейнера.

При изменении оригинала в rag-indexer — синхронизировать этот файл.
Версия: V3.0
"""
from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

CHAR_MAP: dict[str, str] = {
    "\uFFFD": " ",
    "\u25A1": " ",
    "\u2212": "-",
    "\u00A0": " ",
    "\u00AD": "",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
}

_SUSPICIOUS_CHARS_SEEN: dict[str, int] = {}

_ALLOWED_RANGES: list[tuple[int, int]] = [
    (0x0020, 0x007E),
    (0x00A0, 0x024F),
    (0x0300, 0x036F),
    (0x0400, 0x04FF),
    (0x2000, 0x206F),
    (0x2010, 0x2015),
    (0x2100, 0x214F),
    (0x2200, 0x22FF),
]

_ALLOWED_SINGLE: set[int] = {0x000A, 0x000D, 0x0009}


def _is_allowed_char(char: str) -> bool:
    cp = ord(char)
    if cp in _ALLOWED_SINGLE:
        return True
    for start, end in _ALLOWED_RANGES:
        if start <= cp <= end:
            return True
    return False


def _detect_suspicious_chars(text: str, source_hint: str) -> None:
    for char in text:
        if not _is_allowed_char(char):
            cp_hex = f"U+{ord(char):04X}"
            if cp_hex not in _SUSPICIOUS_CHARS_SEEN:
                _SUSPICIOUS_CHARS_SEEN[cp_hex] = 1
                logger.warning(
                    "[SUSPICIOUS CHAR] %s %r — впервые встречен в: %s",
                    cp_hex,
                    char,
                    source_hint[:80] if source_hint else "<unknown>",
                )
            else:
                _SUSPICIOUS_CHARS_SEEN[cp_hex] += 1


def preprocess(text: str, source_hint: str = "") -> str:
    _detect_suspicious_chars(text, source_hint)
    text = unicodedata.normalize("NFC", text)
    for bad, good in CHAR_MAP.items():
        text = text.replace(bad, good)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    # 4. Склеивание с \n
    text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)
    # 4a. Склеивание когда \n уже заменён пробелом: "выва- ливается" → "вываливается"
    # Не затрагивает «эльф-обыватель», «2023-01-01», «978-5-04» — у них нет пробела после дефиса.
    text = re.sub(r"(\w+)-\s+(\w)", r"\1\2", text)
    text = text.replace("\n\n", "\u2400\u2400")
    text = text.replace("\n", " ")
    text = text.replace("\u2400\u2400", "\n\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def reset_suspicious_chars_cache() -> None:
    _SUSPICIOUS_CHARS_SEEN.clear()
