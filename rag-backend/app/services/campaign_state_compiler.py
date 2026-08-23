"""campaign_state_compiler.py — Stage 6: Prompt Assembly.

Детерминированная компиляция активной версии Campaign State в текстовый блок
для system prompt чата / пайплайна.

Контракт (см. campaign-state-implementation-spec.md §11):
  - порядок полей — `display_order ASC, key ASC`;
  - budget ~800 токенов; поля исключаются целиком, не обрезаются посередине;
  - soft-stop: при превышении бюджета следующее поле целиком попадает в
    `truncated_fields`;
  - для list-полей элементы идут в порядке серверной сериализации
    (`created_at ASC, item_key`); resolved=True рендерится с префиксом `[✓]`;
  - детерминированный: ни одного LLM-вызова, никаких DAG-плейсхолдеров;
  - токен-эвристика — `math.ceil(len(text) / 4)`, согласована с
    `update_mode_executor.py`, `pipeline_executor.py`, `full_document_service.py`;
  - если active state отсутствует или все поля пустые/исключены — `text=""`,
    `used_tokens=0`.

Чистая функция: не зависит от БД, Redis, FastAPI. Принимает уже сериализованный
`CampaignStateVersionRead` + список `CampaignStateFieldConfigRead` enabled-полей.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from shared_contracts.models import (
    CampaignStateCompiledBlock,
    CampaignStateCompiledFieldRead,
    CampaignStateFieldConfigRead,
    CampaignStateFieldMode,
    CampaignStateFieldValuesRead,
    CampaignStateListItemRead,
    CampaignStateSingleValueRead,
    CampaignStateVersionRead,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_TOKEN_BUDGET: int = 800
_BUDGET_SETTING_KEY: str = "chat.campaign_state_token_budget"
"""Ориентировочный общий budget для compiled state по §11."""


def default_token_counter(text: str) -> int:
    """Эвристика токенов, согласованная с остальным кодом Mercer."""
    return math.ceil(len(text) / 4)


async def get_campaign_state_token_budget(db: AsyncSession | None = None) -> int:
    """Прочитать token budget из settings_service с fallback на default.

    Если ключ не задан в `platform_settings` и кэш settings_service пуст —
    используется `DEFAULT_TOKEN_BUDGET`. Не падает, если `db is None`.
    """
    try:
        from app.services.settings_service import settings_service
        if db is None:
            return DEFAULT_TOKEN_BUDGET
        try:
            value = await settings_service.get(_BUDGET_SETTING_KEY, db)
        except KeyError:
            return DEFAULT_TOKEN_BUDGET
        if not isinstance(value, int) or value <= 0:
            return DEFAULT_TOKEN_BUDGET
        return value
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "campaign_state_compiler.get_campaign_state_token_budget fallback: %s",
            exc,
        )
        return DEFAULT_TOKEN_BUDGET


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_campaign_state(
    version: CampaignStateVersionRead | None,
    fields: Iterable[CampaignStateFieldConfigRead],
    *,
    budget_tokens: int = DEFAULT_TOKEN_BUDGET,
    token_counter: Callable[[str], int] | None = None,
) -> CampaignStateCompiledBlock:
    """Скомпилировать активный Campaign State в текстовый блок.

    Аргументы:
      version: последняя версия state (CampaignStateVersionRead) или None;
      fields: список enabled-полей конфигурации (display_order ASC, key ASC);
      budget_tokens: мягкий лимит; превышение → поле исключается целиком;
      token_counter: функция подсчёта токенов (default — `ceil(len/4)`).

    Возвращает:
      CampaignStateCompiledBlock с text, used_tokens, truncated_fields и
      per-field метаданными для debug/effective-context view.
    """
    counter = token_counter or default_token_counter
    enabled_fields = [f for f in fields if f.enabled]
    enabled_fields.sort(key=lambda f: (f.display_order, f.key))

    block = CampaignStateCompiledBlock(
        state_version=version.summary.state_version if version else None,
        config_version=version.summary.config_version if version else None,
        budget_tokens=budget_tokens,
        used_tokens=0,
        truncated_fields=[],
        empty_fields=[],
        fields=[],
        text="",
    )

    if not enabled_fields:
        return block

    values_by_field_key: dict[str, CampaignStateFieldValuesRead] = {}
    if version is not None:
        for fv in version.fields:
            values_by_field_key[fv.field_key] = fv

    rendered_chunks: list[str] = []
    used_tokens = 0

    for cfg in enabled_fields:
        fv = values_by_field_key.get(cfg.key)
        # Empty field — поле без значения (single=None или list пустой).
        if fv is None or _is_empty(fv):
            block.empty_fields.append(cfg.key)
            block.fields.append(
                CampaignStateCompiledFieldRead(
                    field_key=cfg.key,
                    field_id=cfg.id,
                    label=cfg.label,
                    mode=cfg.mode,
                    included=False,
                    truncated=False,
                    rendered_text="",
                    estimated_tokens=0,
                    items_included=0,
                    items_total=_items_total(fv),
                )
            )
            continue

        chunk = _render_field(cfg, fv)
        chunk_tokens = counter(chunk)

        if used_tokens + chunk_tokens > budget_tokens:
            # Поле исключается целиком (требование §11).
            block.truncated_fields.append(cfg.key)
            block.fields.append(
                CampaignStateCompiledFieldRead(
                    field_key=cfg.key,
                    field_id=cfg.id,
                    label=cfg.label,
                    mode=cfg.mode,
                    included=False,
                    truncated=True,
                    rendered_text="",
                    estimated_tokens=chunk_tokens,
                    items_included=0,
                    items_total=_items_total(fv),
                )
            )
            logger.info(
                "campaign_state.compile: field truncated. key=%s tokens=%d budget=%d",
                cfg.key, chunk_tokens, budget_tokens,
            )
            continue

        block.fields.append(
            CampaignStateCompiledFieldRead(
                field_key=cfg.key,
                field_id=cfg.id,
                label=cfg.label,
                mode=cfg.mode,
                included=True,
                truncated=False,
                rendered_text=chunk,
                estimated_tokens=chunk_tokens,
                items_included=_items_included(fv),
                items_total=_items_total(fv),
            )
        )
        rendered_chunks.append(chunk)
        used_tokens += chunk_tokens

    block.used_tokens = used_tokens
    block.text = "\n\n".join(rendered_chunks)
    return block


def compose_state_block_header(state_version: int | None) -> str:
    """Маркер секции для prompt: используется как заголовок при отладке.

    Возвращает короткую строку для prepending к `block.text` в effective-context
    view. Не используется в runtime, но помогает UI отличать блок от system_prompt.
    """
    if state_version is None:
        return "[Campaign State: not initialized]"
    return f"[Campaign State: version {state_version}]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_empty(fv: CampaignStateFieldValuesRead) -> bool:
    """Поле считается пустым, если для single нет значения, для list — пусто."""
    if fv.mode == "single":
        return fv.single_value is None or not (fv.single_value.text or "").strip()
    return len(fv.items) == 0


def _items_total(fv: CampaignStateFieldValuesRead | None) -> int:
    if fv is None or fv.mode != "list":
        return 0
    return len(fv.items)


def _items_included(fv: CampaignStateFieldValuesRead) -> int:
    if fv.mode == "list":
        return len(fv.items)
    return 1 if fv.single_value is not None else 0


def _render_field(
    cfg: CampaignStateFieldConfigRead,
    fv: CampaignStateFieldValuesRead,
) -> str:
    """Текстовое представление одного поля."""
    label = (cfg.label or cfg.key).strip()
    if fv.mode == "single":
        return _render_single(label, fv.single_value)
    return _render_list(label, fv.items)


def _render_single(label: str, sv: CampaignStateSingleValueRead | None) -> str:
    text = (sv.text if sv is not None else "").strip()
    return f"{label}: {text}"


def _render_list(label: str, items: list[CampaignStateListItemRead]) -> str:
    if not items:
        return f"{label}:"
    lines: list[str] = [f"{label}:"]
    for it in items:
        prefix = "[x] " if it.resolved else "- "
        text = (it.text or "").strip()
        lines.append(f"{prefix}{text}")
    return "\n".join(lines)


def render_block_for_prompt(block: CampaignStateCompiledBlock) -> str:
    """Возвращает текст для подстановки в system prompt.

    Если `block.text == ""`, возвращает "" — caller склеивает через filter(None).
    """
    return block.text


__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "compile_campaign_state",
    "compose_state_block_header",
    "default_token_counter",
    "get_campaign_state_token_budget",
    "render_block_for_prompt",
]
