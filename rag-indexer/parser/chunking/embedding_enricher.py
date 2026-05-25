from __future__ import annotations

import re
from typing import Any

_MARKDOWN_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def build_embedding_text(
    chunk_text: str,
    source_path: str,
    headers: dict[str, Any] | None = None,
    content_type: str | None = None,
) -> str:
    """
    Формирует обогащённый текст для embedding:

        Документ: vault/path/file.pdf
        Раздел: Глава 2
        Подраздел: Салон Фэла
        Тип: lore
        [текст чанка]

    Для PDF headers берутся из переданного dict (результат resolve_headers_at_offset).
    Для Markdown headers извлекаются из самого chunk_text функцией extract_markdown_headers
    (вызывающий код должен это сделать заранее и передать готовый dict).

    Возвращаемая строка используется ТОЛЬКО для построения вектора.
    В БД (LanceDB) она дублируется в metadata.embedding_text для отладки.
    """
    parts: list[str] = []

    if source_path:
        parts.append(f"Документ: {source_path}")

    headers = headers or {}

    section = (
        headers.get("section")
        or headers.get("h1")
        or headers.get("h2")
    )
    subsection = (
        headers.get("subsection")
        or headers.get("h3")
        or headers.get("h4")
    )

    if section:
        parts.append(f"Раздел: {section}")
    if subsection and subsection != section:
        parts.append(f"Подраздел: {subsection}")

    if content_type:
        parts.append(f"Тип: {content_type}")

    parts.append(chunk_text)

    return "\n".join(parts)


def extract_markdown_headers(chunk_text: str) -> dict[str, str]:
    """
    Извлекает H1/H2/H3 из первой строки чанка (Markdown-ветка).

    generic_chunker режет текст по regex `^#{1,6}\\s+.+$`, поэтому первая строка
    чанка — это заголовок секции, если он был. Возвращает dict вида:
        {"h1": "Title", "section": "Title"}   или
        {"h2": "Subsection", "section": "Subsection"}   или
        {"h3": "Sub-sub", "subsection": "Sub-sub"}

    Если заголовка нет — возвращает пустой dict.
    """
    result: dict[str, str] = {}
    if not chunk_text:
        return result

    first_line = chunk_text.split("\n", 1)[0].strip()
    match = _MARKDOWN_HEADER_RE.match(first_line)
    if not match:
        return result

    level = len(match.group(1))
    text = match.group(2).strip()
    if not text:
        return result

    # Нормализация пробелов на случай, если текст содержит переводы строк
    text = re.sub(r"\s+", " ", text).strip()

    key = f"h{level}"
    result[key] = text

    if level in (1, 2):
        result["section"] = text
    elif level == 3:
        result["subsection"] = text

    return result