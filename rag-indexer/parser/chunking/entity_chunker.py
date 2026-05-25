from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable

from shared_contracts.models import ChunkRecord, EntityRecord
from parser.chunking.generic_chunker import chunk_text

logger = logging.getLogger(__name__)

ENTITY_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "monster": [
        re.compile(r"\b([A-ZА-ЯЁ][\wА-Яа-яёЁ' -]{2,60})\s*(CR\s*([\d/]+))\b", re.IGNORECASE),
        re.compile(r"\b(Гоблин|Орк|Дракон|Скелет|Зомби|Goblin|Orc|Dragon|Skeleton|Zombie)\b", re.IGNORECASE),
    ],
    "damage": [
        re.compile(r"\b(\d+\s*[кd]\s*\d+(?:\s*[+-]\s*\d+)?)\b", re.IGNORECASE),
        re.compile(r"\bУрон:\s*([^.;\n]+)", re.IGNORECASE),
    ],
    "class": [
        re.compile(
            r"\b(Бард[а-яё]*|Воин[а-яё]*|Жрец[а-яё]*|Волшебник[а-яё]*|Плут[а-яё]*|Следопыт[а-яё]*|Паладин[а-яё]*|Друид[а-яё]*|Варвар[а-яё]*|Монах[а-яё]*|Колдун[а-яё]*|Чародей[а-яё]*|Bard|Fighter|Cleric|Wizard|Rogue|Ranger|Paladin|Druid|Barbarian|Monk|Warlock|Sorcerer)\b",
            re.IGNORECASE,
        ),
    ],
    "spell": [
        re.compile(r"\b(?:Заклинание|Spell):\s*([^\n.;]{2,80})", re.IGNORECASE),
        re.compile(r"\b(Fireball|Magic Missile|Cure Wounds|Щит|Огненный шар|Лечение ран)\b", re.IGNORECASE),
    ],
    "project": [
        re.compile(r"\b(?:Project|Проект)\s+([A-ZА-ЯЁ][\wА-Яа-яёЁ-]{2,60})", re.IGNORECASE),
    ],
    "date": [
        re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})\b"),
    ],
    "person": [
        re.compile(r"\b([A-ZА-ЯЁ][a-zа-яё]+(?:\s+[A-ZА-ЯЁ][a-zа-яё]+){1,2})\b"),
    ],
}

CONTENT_TYPE_HINTS = {
    "lore": ["лор", "история", "мир", "раса", "город", "локация", "lore", "world", "city", "region"],
    "rules": ["правило", "механика", "класс", "заклинание", "урон", "спасбросок", "rule", "mechanic", "spell", "damage"],
    "combat": ["бой", "сражение", "encounter", "монстр", "хп", "initiative", "combat", "attack"],
    "session_log": ["лог", "сессия", "запись", "играл", "бросок", "log", "session", "roll"],
}


def chunk_with_entities(
    text: str,
    document_id: str,
    vault_id: str,
    chunk_size: int = 1600,
    overlap: int = 64,
    metadata: dict | None = None,
) -> tuple[list[ChunkRecord], list[EntityRecord]]:
    try:
        chunks = chunk_text(
            text, document_id, vault_id, chunk_size=chunk_size, overlap=overlap, metadata=metadata
        )
        enriched_chunks = _enrich_chunks_with_metadata(chunks, metadata or {})
        entities = _extract_entities(enriched_chunks, metadata or {})
        logger.info(
            "Entity-aware chunking completed: document_id=%s chunks=%s entities=%s",
            document_id,
            len(enriched_chunks),
            len(entities),
        )
        return enriched_chunks, entities
    except Exception as exc:
        logger.warning("Entity-aware chunking failed, falling back to generic chunking: %s", exc)
        return chunk_text(text, document_id, vault_id, chunk_size=chunk_size, overlap=overlap, metadata=metadata), []


def _enrich_chunks_with_metadata(chunks: list[ChunkRecord], base_metadata: dict) -> list[ChunkRecord]:
    domain_id = str(base_metadata.get("domain_id") or base_metadata.get("domain") or "").lower()
    for chunk in chunks:
        tags: list[str] = []
        entity_kinds: list[str] = []

        # 1. Определяем тип контента по ключевым словам
        text_lower = chunk.text.lower()
        for ctype, keywords in CONTENT_TYPE_HINTS.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(ctype)
                break
        else:
            tags.append("general")

        # 2. Извлекаем сущности и тегируем чанк
        for kind, name, _ in _iter_entities(chunk.text, base_metadata):
            normalized_name = _normalize_name(name)
            if normalized_name:
                entity_kinds.append(kind)
                tags.append(f"{kind}:{normalized_name}")

        # 3. Вплетаем в metadata чанка
        chunk.metadata["tags"] = list(set(tags))
        chunk.metadata["content_type"] = tags[0]
        chunk.metadata["entity_kinds"] = list(set(entity_kinds))
        chunk.metadata["domain_id"] = domain_id
    return chunks


def _extract_entities(chunks: Iterable[ChunkRecord], metadata: dict) -> list[EntityRecord]:
    merged: dict[tuple[str, str], EntityRecord] = {}
    for chunk in chunks:
        for kind, name, extra in _iter_entities(chunk.text, metadata):
            normalized_name = _normalize_name(name)
            if not normalized_name:
                continue
            key = (kind, normalized_name.lower())
            entity = merged.get(key)
            if entity is None:
                entity = EntityRecord(
                    entity_id=_entity_id(kind, normalized_name),
                    kind=kind,
                    name=normalized_name,
                    metadata=dict(extra),
                    source_chunk_ids=[],
                )
                merged[key] = entity
            if chunk.chunk_id not in entity.source_chunk_ids:
                entity.source_chunk_ids.append(chunk.chunk_id)
    return sorted(merged.values(), key=lambda e: (e.kind, e.name.lower()))


def _iter_entities(text: str, metadata: dict) -> Iterable[tuple[str, str, dict]]:
    domain_id = str(metadata.get("domain_id") or metadata.get("domain") or " ").lower()
    enabled_kinds = _enabled_kinds(domain_id)
    for kind in enabled_kinds:
        for pattern in ENTITY_PATTERNS[kind]:
            for match in pattern.finditer(text):
                name = match.group(1)
                extra = {"pattern": pattern.pattern}
                if kind == "monster" and len(match.groups()) > 1 and match.group(2):
                    extra["cr"] = match.group(2)
                yield kind, name, extra


def _enabled_kinds(domain_id: str) -> list[str]:
    if domain_id == "dnd":
        return ["monster", "damage", "class", "spell"]
    if domain_id == "work":
        return ["project", "date", "person"]
    return list(ENTITY_PATTERNS.keys())


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip(" \t\n\r.,;:()[]{}\"'"))


def _entity_id(kind: str, name: str) -> str:
    digest = hashlib.sha256(f"{kind}:{name.lower()}".encode("utf-8")).hexdigest()[:16]
    return f"ent{digest}"