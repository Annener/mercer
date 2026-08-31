"""effective_context.py — фасад (re-export) для обратной совместимости.

Логика сборки контекста перенесена в `app.services.context_engine` (Фаза 1).
Здесь остаются:
  - re-export старых имён (`compose_full_system_prompt`,
    `compose_full_system_prompt_with_state`, `compose_state_block_only`,
    `compose_scene_block`, `_resolve_system_prompt_text`,
    `_resolve_campaign_state_block_safe`) — для существующих импортов;
  - `append_tool_use_rules` + `_TOOL_USE_RULES` — пост-обработка для
    agent-loop пути, к сборке контекста не относится;
  - `_RAG_DECIDES_HINT` — хинт для plain-RAG режима;
  - `build_effective_context` — debug-endpoint helper, использует
    `_resolve_system_prompt_text` / `_resolve_campaign_state_block_safe`
    через re-export.

Используется из `app.api.chat`, `app.api.pipeline_resume`,
`app.services.pipeline_executor`, `app.api.settings.campaigns`,
плюс тесты в `tests/integration/test_iter6_smoke.py`,
`tests/integration/test_iter7_e2e.py`,
`tests/unit/rag_backend/test_tool_use_rules.py`,
`tests/unit/rag_backend/test_effective_context_api.py`.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.campaign_state_compiler import (
    default_token_counter,
    get_campaign_state_token_budget,
)
from app.services.context_engine import (
    build_chat_context,
    build_chat_context_with_state,
    build_state_block_only,
)
from app.services.context_engine.assembly import (
    _resolve_campaign_state_block_safe,
    _resolve_system_prompt_text,
)
from shared_contracts.models import (
    EffectiveContextBlock,
    EffectiveContextRead,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-export фасад: старые имена → новые реализации из context_engine
# ---------------------------------------------------------------------------


async def compose_full_system_prompt(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> str:
    """Deprecated alias для `app.services.context_engine.build_chat_context`."""
    return await build_chat_context(campaign_id, domain_id, db, scene_state)


async def compose_full_system_prompt_with_state(
    campaign_id: str | None,
    domain_id: str | None,
    db: AsyncSession,
    scene_state: dict[str, Any] | None = None,
) -> tuple[str, Any]:
    """Deprecated alias для `app.services.context_engine.build_chat_context_with_state`."""
    return await build_chat_context_with_state(
        campaign_id, domain_id, db, scene_state
    )


async def compose_state_block_only(
    campaign_id: str | None,
    db: AsyncSession,
) -> str:
    """Deprecated alias для `app.services.context_engine.build_state_block_only`."""
    return await build_state_block_only(campaign_id, db)


# ---------------------------------------------------------------------------
# Tool use rules (остаются здесь — пост-обработка agent-loop, не сборка контекста)
# ---------------------------------------------------------------------------

# Stage 8.6: правила использования `search_knowledge` tool. Согласно §12.1
# спецификации, модель обязана вызвать tool при запросах о конкретных фактах
# и не должна выдумывать лор/правила. Блок приклеивается к system prompt
# только когда agent loop реально использует tool — для legacy single-shot
# пути он избыточен.
_TOOL_USE_RULES = """\

# Правила использования `search_knowledge`

Ты имеешь доступ к инструменту `search_knowledge(queries, reason)`, который ищет доказательства в локальной базе знаний активного домена и кампании.

## Общее правило

Вызывай `search_knowledge` при обращении к **конкретике**, по которой у тебя нет однозначных знаний, подтверждённых:

- в явном виде в текущей истории чата, или
- в полном объёме в system_prompt (Campaign State + доменный промпт + scene_state).

Если ответ требует конкретного факта из базы знаний — сначала поиск, потом синтез. Не отвечай «из головы» по проектным/доменным артефактам.

## Явные сигналы пользователя к поиску

Когда пользователь пишет «уточни», «посмотри в базе», «сверься», «что в документах», «что у нас там по этому поводу», «найди», «поищи», «в базе знаний», «в RAG» — это прямой сигнал к вызову `search_knowledge`. В таких случаях сначала поиск.

## Когда вызывать (проектные домены: work и аналогичные)

Почти наверняка нужен `search_knowledge`, если вопрос про:

- конкретный компонент, подсистему, модуль, сервис;
- статус, фазу, MVP, готовность, релиз;
- требования, ограничения, риски, принятые решения;
- персоны, роли, доступы, ответственность;
- версии, метрики, даты, числа из проекта;
- любые термины, которые звучат как проектные артефакты, а не общеизвестные понятия.

Примеры:
- "Что у нас с управлением доступами?" → ищи.
- "Какие сложности с компонентом X?" → ищи.
- "Расскажи про NPC Аркагор" → ищи описание сущности.
- "Что было в документе про X?" → ищи документ.
- "Что мы решили по Y на прошлой неделе?" → ищи в логах/документах.

## Когда НЕ вызывать

- "Привет" / "Как дела?" / "Спасибо" — светская беседа.
- Вопрос, на который system_prompt и история чата уже дают полный ответ.
- Инструкция вида "запомни что мы в фазе X" / "обнови контекст — MVP завершён" — это не вопрос о фактах, используй `propose_context_update` или `update_scene_state`.

## Правила цитирования

- Если `search_knowledge` вернул evidence, опирайся только на него для проектных/доменных фактов. Не подменяй его своими общими знаниями.
- Если `search_knowledge` вернул пустой результат или `note='no evidence found'` / `scope='no_vault'` — НЕ выдумывай. Явно скажи пользователю, что в локальной базе знаний этих сведений нет или что база знаний пуста/не настроена.
- Не повторяй тот же запрос дважды за один turn: host отклонит дубликат.
- Не выдумывай ссылки на источники: модель не имеет доступа к URL — только к тексту чанков, которые вернул `search_knowledge`.

## Дополнительные инструменты (Sprint 3)

### Главное правило: контекст кампании

Твоя основная задача как ассистента кампании — **актуализировать Campaign State и связанные `.md` файлы** при появлении любых новых долгосрочных фактов.

При появлении в сообщении пользователя новых фактов о статусе, результатах, сущностях, интеграциях, компонентах, MVP-завершении, новых ролях/инструментах, принятых решениях — ВСЕГДА вызывай `propose_context_update`. Пользователь увидит карточку ревью и примет/отклонит правки.

Не подменяй это `update_scene_state` — scene_state НЕ виден в Campaign State и не сохраняется между чатами. Запись долгосрочного факта в scene-state — это потеря данных: пользователь не увидит изменения в debug-контексте кампании и не сможет их применить.

### `update_scene_state(patch, reason)`
Краткоживущая память текущего разговора: `current_location`, `active_npcs`, `current_act` — только то, что важно между turn-ами одного чата, но НЕ должно персистироваться в Campaign State.

ЗАПРЕЩЕНО использовать `update_scene_state` для:
- статусов проекта / фаз / MVP-завершения;
- результатов работы / релизов / готовых компонентов;
- технических фактов (интеграции, доступы, наблюдаемость);
- любых данных, которые должны быть видны в Campaign State.

Для всего перечисленного выше используй `propose_context_update`.

### `propose_context_update(field_changes?, state_patch?, file_changes?, confidence, reason, source_message_ids?, review_summary?)`
Создаёт **предложение** изменения контекста кампании. ПРЕДЛОЖЕНИЕ, а не прямая запись — пользователь увидит карточку ревью и должен явно принять или отклонить. **Не** применяй предложения, если:
- факт уже есть в текущем state или в system_prompt (нет смысла дублировать);
- ты не уверен в интерпретации (низкая `confidence`);
- это разовая реплика в диалоге, а не долгосрочный факт.

Предлагать **минимальный** патч, не переписывать документы целиком.
Параметр `confidence` ∈ [0, 1]: < 0.5 = не предлагать, 0.5–0.7 = сомнительно, > 0.7 = уверенно. Помни: создание поля — серьёзное архитектурное решение; не предлагай `create_field` для каждого нового слова пользователя.

Если уже есть активная review-сессия, модель автоматически перезаписывает её — пользователь увидит свежую карточку. Не нужно сначала отменять.

Синтаксис `field_changes[]` (только если хочешь изменить *схему* Campaign State):
- `operation`: `"create_field"` | `"update_field"`. Для `update_field` атрибут `mode` иммутабелен — если нужно сменить режим, откажись от proposal.
- `key`: `^[a-z][a-z0-9_]*$`, ≤ 64 символов. Иммутабелен после создания.
- `mode`: `"single"` (свободный текст) | `"list"` (упорядоченный чек-лист с `item_key`).
- `label`, `description`, `enabled`, `display_order` — необязательные, но рекомендуются.

Синтаксис `state_patch[]` (только если хочешь записать *значения* в существующие поля):
- `type`: `"replace_single"` | `"clear_single"` | `"add_list_item"` | `"update_list_item"` | `"resolve_list_item"` | `"remove_list_item"`.
- `field_key`: должен существовать в snapshot кампании, либо быть создан в этом же proposal через `field_changes`.
- `text`: обязателен (не пустой) для `replace_single` / `update_list_item` / `add_list_item`.

Синтаксис `file_changes[]` (только если хочешь править `.md` файлы в vault):
- `action`: `"update"` | `"create"`.
- `operation`: `"append_after_section"` | `"append_to_file"` | `"replace_unique_text"` | `"create_file"`.
- Для `update` нужен `document_id` из контекста; для `create` — опциональный `parent_document_id` и `suggested_filename`.

Невалидные значения (например `mode="manual"` или `type="unknown"`) хост отклоняет целиком без применения. Проверяй допустимые значения, прежде чем отправлять.

## Контекст сцены

`chat.scene_state` (если заполнен) уже виден тебе в system_prompt как блок «Текущая сцена». Это твоя краткосрочная память между turn-ами — читай её в начале каждого turn-а, чтобы не задавать одни и те же вопросы дважды.
"""


# Hint, инжектируемый ТОЛЬКО когда per-chat rag_prefill_enabled=False
# (режим «модель сама решает»). Усиливает инструкции о вызове search_knowledge,
# чтобы компенсировать отсутствие автоматического prefill в system_prompt.
_RAG_DECIDES_HINT = """\

# Режим диалога: ты решаешь, нужен ли поиск

Сейчас автоматическая префилл-выборка из базы знаний **выключена**. Ты получаешь вопрос пользователя как есть — без подготовленного контекста из RAG.

Поэтому: при обращении к какой-либо конкретике, по которой у тебя нет однозначных знаний, подтверждённых **в явном виде в этой истории чата** или **в полном объёме в этом system_prompt**, — ДЕЛАЙ запрос в RAG через `search_knowledge` прежде чем отвечать.

Прямые сигналы к немедленному поиску:

- пользователь явно просит свериться с базой / RAG / контекстом / документами
  («уточни», «посмотри», «сверься», «что в базе», «найди в документах»,
  «что у нас там»);
- вопрос про компонент / подсистему / модуль / интеграцию / персону / статус
  / фазу / MVP / риск / требование;
- любое название, которое звучит как проектный артефакт, а не общеизвестное понятие.

Если есть сомнения — лучше поискать, чем выдумывать.
"""



def append_tool_use_rules(system_prompt: str) -> str:
    """Приклеивает правила §12.1 к system prompt.

    Используется только в agent-loop пути `plain_stream` —
    legacy single-shot retrieval не нуждается в этих правилах.
    """
    if not system_prompt:
        return _TOOL_USE_RULES.lstrip()
    return system_prompt + _TOOL_USE_RULES


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
