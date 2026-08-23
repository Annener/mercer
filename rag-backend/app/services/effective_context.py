"""effective_context.py — Stage 6: общий runtime helper для prompt assembly.

Содержит функции, которые используются и в chat runtime, и в debug-эндпойнте:
  - `_compose_full_system_prompt_text` — собрать system_prompt + Campaign State
    в единую строку (без RAG-context);
  - `build_effective_context` — собрать полный effective-context для UI.

Не зависит от FastAPI. Используется из `app.api.chat`, `app.api.pipeline_resume`,
`app.services.pipeline_executor`, `app.api.settings.campaigns`.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.campaign_state_compiler import (
    compile_campaign_state,
    default_token_counter,
    get_campaign_state_token_budget,
)
from app.services.campaign_state_value_service import campaign_state_value_service
from app.services.domain_service import domain_service
from shared_contracts.models import (
    CampaignStateCompiledBlock,
    EffectiveContextBlock,
    EffectiveContextRead,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_system_prompt_text(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
) -> str:
    if campaign_id:
        from app.db.models import Campaign
        try:
            campaign = await db.get(Campaign, uuid.UUID(campaign_id))
        except (ValueError, TypeError):
            campaign = None
        if campaign is not None and campaign.system_prompt:
            return campaign.system_prompt
    return await domain_service.get_prompt(domain_id or "default", "system", db)


async def _resolve_campaign_state_block_safe(
    campaign_id: str | None,
    db: AsyncSession,
) -> tuple[str, CampaignStateCompiledBlock | None]:
    """Скомпилировать active Campaign State.

    Возвращает `(text, block_or_none)`. Никогда не падает: ошибки логируются и
    возвращается пустой блок — runtime чата не должен зависеть от Campaign State.
    """
    if not campaign_id:
        return "", None
    try:
        version = await campaign_state_value_service.get_active_state(
            db, uuid.UUID(campaign_id)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "effective_context._resolve_campaign_state_block_safe: get_active_state failed: %s",
            exc,
        )
        version = None

    if version is None:
        return "", CampaignStateCompiledBlock(
            budget_tokens=await get_campaign_state_token_budget(db),
            used_tokens=0,
        )

    try:
        budget = await get_campaign_state_token_budget(db)
        fields = await campaign_state_value_service.list_enabled_fields_ordered(
            db, uuid.UUID(campaign_id)
        )
        block = compile_campaign_state(version, fields, budget_tokens=budget)
        return block.text, block
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "effective_context._resolve_campaign_state_block_safe: compile failed: %s",
            exc,
        )
        return "", None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compose_full_system_prompt(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> str:
    """Собрать `system_prompt + Campaign State block + Scene State block` через filter(None).

    `scene_state` (если задан) рендерится отдельным блоком между campaign_state
    и финальным system_prompt — модель видит активный контекст сцены
    (location, active_npcs, current_act и т.п.) и помнит его между turn-ами.

    Не подставляет RAG-context — это делает вызывающий код после retrieval.
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    state_text, _ = await _resolve_campaign_state_block_safe(campaign_id, db)
    scene_text = compose_scene_block(scene_state)
    parts = [p for p in (system_prompt, state_text, scene_text) if p]
    return "\n\n".join(parts)


# Максимальный размер scene_state JSON (символов). Защищает prompt от раздувания,
# если модель начнёт писать большие значения (например, длинные истории NPC).
_SCENE_STATE_MAX_CHARS = 4 * 1024


def compose_scene_block(scene_state: dict[str, Any] | None) -> str:
    """Рендерит блок «Текущая сцена» для system_prompt.

    - Пустой / None / не-dict → пустая строка (блок пропускается).
    - Слишком большой JSON (>_SCENE_STATE_MAX_CHARS) → обрезается с WARNING-меткой.
      Полный текст при этом всё равно доступен модели через `chat.metadata.scene_state`
      в read-only (host-controlled) режиме — мы просто не пихаем его целиком в prompt.

    Структура выходного текста (plain text, не JSON-строка, чтобы модель
    читала естественно):

        ## Текущая сцена
        - location: Забытые Королевства, подземелье
        - active_npcs:
          - Бехолдер
          - Культисты Теней
        - current_act: Глава 3 — Падение
    """
    if not scene_state:
        return ""
    if not isinstance(scene_state, dict):
        return ""
    try:
        rendered = json.dumps(scene_state, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        logger.warning(
            "compose_scene_block: scene_state is not JSON-serialisable, skipping"
        )
        return ""
    if len(rendered) > _SCENE_STATE_MAX_CHARS:
        rendered = rendered[:_SCENE_STATE_MAX_CHARS] + "\n…(truncated)"
        logger.warning(
            "compose_scene_block: scene_state exceeded %d chars, truncated for prompt",
            _SCENE_STATE_MAX_CHARS,
        )
    return f"## Текущая сцена\n{rendered}"


# Stage 8.6: правила использования `search_knowledge` tool. Согласно §12.1
# спецификации, модель обязана вызвать tool при запросах о конкретных фактах
# и не должна выдумывать лор/правила. Блок приклеивается к system prompt
# только когда agent loop реально использует tool — для legacy single-shot
# пути он избыточен.
_TOOL_USE_RULES = """\

# Правила использования `search_knowledge`

Ты имеешь доступ к инструменту `search_knowledge(queries, reason)`, который ищет доказательства в локальной базе знаний кампании.

## Когда ОБЯЗАН вызвать `search_knowledge`

Ты ОБЯЗАН вызвать `search_knowledge` ПЕРЕД ответом, если вопрос касается:
- конкретных фактов кампании, истории, сюжета, лора;
- именованных сущностей (персонажей, локаций, предметов, фракций);
- точного содержания документов кампании (правил, заклинаний, характеристик);
- деталей, которых нет в твоём system prompt и в недавней истории чата.

## Когда НЕ НУЖНО вызывать `search_knowledge`

- общий вопрос, не требующий кампанийского контекста;
- приветствие, благодарность, светская беседа;
- вопрос, на который system prompt и недавняя история чата уже дают полный ответ.

## Правила цитирования

- Если `search_knowledge` вернул evidence, опирайся только на него для кампанийских фактов. Не подменяй его своими общими знаниями.
- Если `search_knowledge` вернул пустой результат или `note='no evidence found'` — НЕ выдумывай кампанийский лор. Явно скажи пользователю, что в локальной базе знаний этих сведений нет.
- Не повторяй тот же запрос дважды за один turn: host отклонит дубликат.
- Не выдумывай ссылки на источники: модель не имеет доступа к URL — только к тексту чанков, которые вернул `search_knowledge`.

## Дополнительные инструменты (Sprint 3)

### `update_scene_state(patch, reason)`
Краткоживущая память активной сцены: локация, NPC рядом, текущая фаза.
Patch мерджится в `chat.scene_state`. НЕ для долгосрочных фактов — для этого
используй `propose_context_update`.

### `propose_context_update(field_changes?, state_patch?, file_changes?, confidence, reason, source_message_ids?, review_summary?)`
Создаёт **предложение** изменения контекста кампании. ПРЕДЛОЖЕНИЕ, а не
прямая запись — пользователь увидит карточку ревью и должен явно
принять или отклонить. **Не** применяй предложения, если:
- факт уже есть в текущем state или в system_prompt (нет смысла дублировать);
- ты не уверен в интерпретации (низкая `confidence`);
- это разовая реплика в диалоге, а не долгосрочный факт.

Предлагать **минимальный** патч, не переписывать документы целиком.
Параметр `confidence` ∈ [0, 1]: < 0.5 = не предлагать, 0.5–0.7 = сомнительно,
> 0.7 = уверенно. Помни: создание поля — серьёзное архитектурное решение;
не предлагай `create_field` для каждого нового слова пользователя.

## Контекст сцены

`chat.scene_state` (если заполнен) уже виден тебе в system_prompt как блок
«Текущая сцена». Это твоя краткосрочная память между turn-ами — читай её
в начале каждого turn-а, чтобы не задавать одни и те же вопросы дважды.
"""


def append_tool_use_rules(system_prompt: str) -> str:
    """Приклеивает правила §12.1 к system prompt.

    Используется только в agent-loop пути `plain_stream` —
    legacy single-shot retrieval не нуждается в этих правилах.
    """
    if not system_prompt:
        return _TOOL_USE_RULES.lstrip()
    return system_prompt + _TOOL_USE_RULES


async def compose_full_system_prompt_with_state(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> tuple[str, CampaignStateCompiledBlock | None]:
    """Вернуть (system_prompt_text, state_block).

    Возвращает уже склеенный `system_prompt + state + scene_state` и сам
    state_block для debug. `scene_state` рендерится после campaign_state.
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    state_text, block = await _resolve_campaign_state_block_safe(campaign_id, db)
    scene_text = compose_scene_block(scene_state)
    parts = [p for p in (system_prompt, state_text, scene_text) if p]
    return "\n\n".join(parts), block


async def compose_state_block_only(
    campaign_id: str | None,
    db: AsyncSession,
) -> str:
    """Вернуть только текст Campaign State block (без system_prompt и rag_context).

    Используется в `_run_final_composition` для добавления блока после
    pipeline-resolved prompt без вмешательства в шаблоны с {query}/{STEP_ID.*}.
    """
    state_text, _ = await _resolve_campaign_state_block_safe(campaign_id, db)
    return state_text


# ---------------------------------------------------------------------------
# Effective context (debug endpoint)
# ---------------------------------------------------------------------------


async def build_effective_context(
    campaign_id: str | None,
    chat_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    *,
    include_rag: bool = False,
    rag_hits: list[Any] | None = None,
    user_message: str = "",
) -> EffectiveContextRead:
    """Собрать effective-context для дебага prompt assembly.

    Не выполняет retrieval. Если `include_rag=True` — берёт уже посчитанные
    `rag_hits` (иначе пропускает блок).
    """
    system_prompt = await _resolve_system_prompt_text(campaign_id, domain_id, db)
    _, state_block = await _resolve_campaign_state_block_safe(campaign_id, db)
    budget = await get_campaign_state_token_budget(db)

    blocks: list[EffectiveContextBlock] = []
    total_tokens = 0

    if system_prompt:
        sp_tokens = default_token_counter(system_prompt)
        blocks.append(EffectiveContextBlock(
            name="system_prompt",
            text=system_prompt,
            estimated_tokens=sp_tokens,
        ))
        total_tokens += sp_tokens

    if state_block is not None and state_block.text:
        blocks.append(EffectiveContextBlock(
            name="campaign_state",
            text=state_block.text,
            estimated_tokens=state_block.used_tokens,
        ))
        total_tokens += state_block.used_tokens

    if include_rag and rag_hits:
        from app.services.retrieval import format_context
        rag_text = format_context(rag_hits)
        rag_tokens = default_token_counter(rag_text) if rag_text else 0
        if rag_text:
            blocks.append(EffectiveContextBlock(
                name="rag_context",
                text=rag_text,
                estimated_tokens=rag_tokens,
            ))
            total_tokens += rag_tokens

    if user_message:
        um_tokens = default_token_counter(user_message)
        blocks.append(EffectiveContextBlock(
            name="user_message",
            text=user_message,
            estimated_tokens=um_tokens,
        ))
        total_tokens += um_tokens

    return EffectiveContextRead(
        campaign_id=campaign_id,
        chat_id=chat_id,
        domain_id=domain_id,
        blocks=blocks,
        total_tokens=total_tokens,
        budget=budget,
        truncated_fields=list(state_block.truncated_fields) if state_block else [],
        state_version=state_block.state_version if state_block else None,
    )


__all__ = [
    "build_effective_context",
    "compose_full_system_prompt",
    "compose_full_system_prompt_with_state",
    "compose_state_block_only",
]
