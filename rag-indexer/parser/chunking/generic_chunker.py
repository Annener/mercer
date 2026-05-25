from __future__ import annotations

import re
import uuid
from shared_contracts.models import ChunkRecord


def chunk_text(
    text: str,
    document_id: str,
    vault_id: str,
    chunk_size: int = 1600,
    overlap: int = 64,
    metadata: dict | None = None,
) -> list[ChunkRecord]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[ChunkRecord] = []
    base_metadata = dict(metadata or {})

    # 1. Разделяем текст по Markdown-заголовкам (сохраняя сам заголовок)
    heading_pattern = re.compile(r'^(#{1,6}\s+.+)$', re.MULTILINE)
    parts = heading_pattern.split(text)

    sections: list[str] = []
    current_heading = ""
    for part in parts:
        stripped = part.strip()
        if heading_pattern.match(stripped):
            current_heading = stripped
        elif stripped:
            content = f"{current_heading}\n\n{stripped}".strip()
            sections.append(content)
            current_heading = ""

    # Если заголовков нет, обрабатываем весь текст как одну секцию
    if not sections:
        sections = [text]

    # 2. Обрабатываем каждую секцию
    global_word_offset = 0
    for section in sections:
        words = section.split()
        section_len = len(words)

        if section_len == 0:
            continue

        if section_len <= chunk_size:
            # Секция влезает в лимит → сохраняем целиком (семантически корректно)
            chunk_metadata = dict(base_metadata)
            chunk_metadata["word_start"] = global_word_offset
            chunk_metadata["word_end"] = global_word_offset + section_len
            chunks.append(
                ChunkRecord(
                    chunk_id=f"chk_{uuid.uuid4().hex[:12]}",
                    document_id=document_id,
                    vault_id=vault_id,
                    text=section,
                    vector=None,
                    metadata=chunk_metadata,
                    summary=None,
                )
            )
            global_word_offset += section_len
        else:
            # Секция слишком длинная → применяем скользящее окно с перекрытием
            step = max(1, chunk_size - overlap)
            for start in range(0, section_len, step):
                chunk_words = words[start : start + chunk_size]
                if not chunk_words:
                    break

                chunk_metadata = dict(base_metadata)
                chunk_metadata["word_start"] = global_word_offset + start
                chunk_metadata["word_end"] = global_word_offset + start + len(chunk_words)
                chunks.append(
                    ChunkRecord(
                        chunk_id=f"chk_{uuid.uuid4().hex[:12]}",
                        document_id=document_id,
                        vault_id=vault_id,
                        text=" ".join(chunk_words),
                        vector=None,
                        metadata=chunk_metadata,
                        summary=None,
                    )
                )
                if start + chunk_size >= section_len:
                    break
            global_word_offset += section_len

    return chunks