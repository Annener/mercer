from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Карта замен проблемных символов, характерных для PDF-экстракции
CHAR_MAP: dict[str, str] = {
    "\uFFFD": " ",   # U+FFFD: символ замены (кракозябры/битые кодировки)
    "\u25A1": " ",   # U+25A1: пустой квадрат (артефакт рендера)
    "\u2212": "-",   # U+2212: математический минус → обычный дефис-минус
    "\u00A0": " ",   # U+00A0: неразрывный пробел → обычный пробел
    "\u00AD": "",    # U+00AD: Soft hyphen (мягкий перенос)
    "\u2010": "-",   # Hyphen
    "\u2011": "-",   # Non-breaking hyphen
    "\u2012": "-",   # Figure dash
    "\u2013": "-",   # En dash → дефис для единообразия
    "\u2014": "-",   # Em dash → дефис для единообразия
}

# ---------------------------------------------------------------------------
# Глобальный кэш suspicious Unicode-символов (V3.0)
# Ключ — "U+XXXX", значение — количество встреч (для статистики).
# Каждое новое значение логируется ОДИН РАЗ за жизнь процесса.
# ---------------------------------------------------------------------------
_SUSPICIOUS_CHARS_SEEN: dict[str, int] = {}

# Разрешённые Unicode-диапазоны
_ALLOWED_RANGES: list[tuple[int, int]] = [
    (0x0020, 0x007E),  # ASCII printable
    (0x00A0, 0x024F),  # Latin Extended
    (0x0300, 0x036F),  # Combining diacritical marks
    (0x0400, 0x04FF),  # Кириллица
    (0x2000, 0x206F),  # General punctuation
    (0x2010, 0x2015),  # Dashes / hyphens
    (0x2100, 0x214F),  # Letterlike symbols
    (0x2200, 0x22FF),  # Mathematical operators
]

# Отдельные разрешённые control-символы
_ALLOWED_SINGLE: set[int] = {0x000A, 0x000D, 0x0009}  # \n, \r, \t


def _is_allowed_char(char: str) -> bool:
    """Проверяет, входит ли символ в список разрешённых диапазонов."""
    cp = ord(char)
    if cp in _ALLOWED_SINGLE:
        return True
    for start, end in _ALLOWED_RANGES:
        if start <= cp <= end:
            return True
    return False


def _detect_suspicious_chars(text: str, source_hint: str) -> None:
    """
    Логирует каждый неизвестный Unicode-символ ОДИН РАЗ за всю жизнь процесса.
    Предотвращает спам в логах при индексации больших vault'ов.
    """
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
    """
    Глубокая очистка текста перед эмбеддингом.
    В V3.0 вызывается НА КАЖДОМ чанке отдельно (после чанкинга),
    поэтому source_hint включает идентификатор чанка.

    Порядок операций критичен: от юникода → к структуре → к пробелам.
    """
    # 0. Детекция suspicious chars (логирует только новые символы)
    _detect_suspicious_chars(text, source_hint)

    # 1. NFC-нормализация: комбинирующие диакритики сливаются с базовыми буквами
    text = unicodedata.normalize("NFC", text)

    # 2. Замена специфичных артефактов
    for bad, good in CHAR_MAP.items():
        text = text.replace(bad, good)

    # 3. Удаление строк, состоящих ТОЛЬКО из цифр (номера страниц PDF, футеры, артефакты)
    # Оставляет пустые строки между абзацами, не ломая структуру
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

    # 4. Склеивание дефисных переносов: "спо-\nсобность" → "способность"
    # Учитывает возможные пробелы вокруг дефиса и переноса строки
    text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)

    # 5. Нормализация структуры абзацев:
    # Одиночный \n внутри текста → пробел (сшивает разорванные строки PDF)
    # \n\n или более → сохраняет как разделитель абзацев
    text = text.replace("\n\n", "\u2400\u2400")  # Временный маркер для двойного переноса
    text = text.replace("\n", " ")                # Одинарные переносы → пробелы
    text = text.replace("\u2400\u2400", "\n\n")   # Восстанавливаем абзацы

    # 6. Финальная нормализация пробелов и чистка мусора
    text = re.sub(r"[ \t]+", " ", text)           # Множественные пробелы/табы → один
    text = re.sub(r" +\n", "\n", text)            # Убираем пробелы после переносов абзацев
    text = re.sub(r"\n{3,}", "\n\n", text)        # 3+ переносов → максимум 2

    return text.strip()


def reset_suspicious_chars_cache() -> None:
    """
    Сбрасывает глобальный кэш suspicious-символов.
    Используется в тестах и при необходимости "чистого" запуска.
    """
    _SUSPICIOUS_CHARS_SEEN.clear()