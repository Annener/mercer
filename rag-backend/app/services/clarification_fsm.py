from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ClarificationState as ClarificationStateRow
from app.services.prompt_pack import PromptPack, format_prompt
from shared_contracts.models import ClarificationState


logger = logging.getLogger(__name__)

FIELD_LABELS = {
    "topic": "тему или объект вопроса",
    "subject": "конкретный класс, расу, заклинание или предмет",
}


async def get_state(db: AsyncSession, chat_id: uuid.UUID) -> ClarificationState:
    row = await db.get(ClarificationStateRow, chat_id)
    if row is None:
        row = ClarificationStateRow(chat_id=chat_id)
        db.add(row)
        await db.flush()
    return _to_contract(row)


async def save_state(db: AsyncSession, chat_id: uuid.UUID, state: ClarificationState) -> None:
    row = await db.get(ClarificationStateRow, chat_id)
    if row is None:
        row = ClarificationStateRow(chat_id=chat_id)
        db.add(row)
    row.stage = state.stage
    row.missing_fields = list(state.missing_fields)
    row.collected = dict(state.collected)
    row.turn = state.turn
    row.next_question = state.next_question
    await db.flush()
    logger.info(
        "Clarification state saved: chat_id=%s stage=%s missing_fields=%s turn=%s",
        chat_id,
        state.stage,
        state.missing_fields,
        state.turn,
    )


async def start_collecting(
    db: AsyncSession,
    chat_id: uuid.UUID,
    missing_fields: list[str],
    prompt_pack: PromptPack,
) -> ClarificationState:
    state = ClarificationState(
        stage="collecting",
        missing_fields=missing_fields,
        collected={},
        turn=0,
        next_question=generate_next_question(missing_fields, {}, prompt_pack),
    )
    await save_state(db, chat_id, state)
    return state


def process_clarification_answer(
    state: ClarificationState,
    user_message: str,
    max_turns: int,
    prompt_pack: PromptPack,
) -> ClarificationState:
    collected = dict(state.collected)
    missing_fields = list(state.missing_fields)

    for field in list(missing_fields):
        value = _extract_field_value(field, user_message)
        if not value:
            continue
        collected[field] = value
        missing_fields.remove(field)

    turn = state.turn + 1
    if not missing_fields:
        next_state = ClarificationState(
            stage="complete",
            missing_fields=[],
            collected=collected,
            turn=turn,
            next_question=None,
        )
    elif max_turns <= 0 or turn >= max_turns:
        next_state = ClarificationState(
            stage="fallback",
            missing_fields=missing_fields,
            collected=collected,
            turn=turn,
            next_question=None,
        )
    else:
        next_state = ClarificationState(
            stage="collecting",
            missing_fields=missing_fields,
            collected=collected,
            turn=turn,
            next_question=generate_next_question(missing_fields, collected, prompt_pack),
        )

    logger.info(
        "Clarification transition: old_stage=%s new_stage=%s missing_fields=%s collected=%s",
        state.stage,
        next_state.stage,
        next_state.missing_fields,
        sorted(next_state.collected),
    )
    return next_state


def idle_state() -> ClarificationState:
    return ClarificationState(stage="idle", missing_fields=[], collected={}, turn=0, next_question=None)


def generate_next_question(
    missing_fields: list[str],
    collected: dict[str, str],
    prompt_pack: PromptPack,
) -> str:
    labels = [FIELD_LABELS.get(field, field) for field in missing_fields]
    template = prompt_pack.get("clarification", "Уточните, пожалуйста: {missing_fields}")
    return format_prompt(
        template,
        {
            "missing_fields": ", ".join(labels),
            "collected_fields": collected,
        },
    ).strip()


def _extract_field_value(field: str, user_message: str) -> str | None:
    text = user_message.strip()
    if not text:
        return None

    patterns = {
        "topic": [r"(?:про|о|about)\s+(.+)$"],
        "subject": [r"(?:про|о|about)\s+(.+)$", r"(?:это|это про|я имею в виду)\s+(.+)$"],
    }
    for pattern in patterns.get(field, []):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _normalize_value(match.group(1))
    return _normalize_value(text)


def _normalize_value(value: str) -> str:
    return value.strip(" .,!?:;\"'")


def _to_contract(row: ClarificationStateRow) -> ClarificationState:
    return ClarificationState(
        stage=row.stage,
        missing_fields=list(row.missing_fields or []),
        collected=dict(row.collected or {}),
        turn=row.turn,
        next_question=row.next_question,
    )
