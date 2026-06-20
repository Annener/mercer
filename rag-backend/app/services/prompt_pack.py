from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptPack:
    domain_id: str
    description: str
    prompts: dict[str, str]

    def get(self, name: str, default: str = "") -> str:
        return self.prompts.get(name, default)


# ---------------------------------------------------------------------------
# Step variable resolution — новый DAG-based подход
# ---------------------------------------------------------------------------

# Regex для {STEP_ID.result} и {STEP_ID.key}
# Группы: (step_id, accessor)  где accessor = "result" | любой другой ключ
_VAR_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\.( result|[A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_step_vars(template: str, step_results: dict[str, Any]) -> str:
    """Подставить {STEP_ID.result} и {STEP_ID.key} из словаря step_results.

    Правила подстановки:
      {STEP_ID.result} + str   → строка как есть
      {STEP_ID.result} + dict  → json.dumps(dict, ensure_ascii=False)
      {STEP_ID.key}    + dict  → dict[key]; если ключ отсутствует — placeholder остаётся,
                                 в лог пишется WARNING
      {STEP_ID.*}              → если step_id не в step_results — placeholder остаётся,
                                 в лог пишется WARNING
    """

    def _replace(match: re.Match) -> str:
        step_id = match.group(1)
        accessor = match.group(2)
        placeholder = match.group(0)  # вернуть как есть при ошибке

        if step_id not in step_results:
            logger.warning(
                "resolve_step_vars: step_id '%s' not found in step_results; placeholder kept",
                step_id,
            )
            return placeholder

        value = step_results[step_id]

        if accessor == "result":
            if isinstance(value, dict):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        # accessor = конкретный ключ
        if isinstance(value, dict):
            if accessor in value:
                return str(value[accessor])
            logger.warning(
                "resolve_step_vars: key '%s' not found in step_results['%s']; placeholder kept",
                accessor,
                step_id,
            )
            return placeholder

        # value — строка, а запрошен ключ; нет смысла
        logger.warning(
            "resolve_step_vars: step_result for '%s' is not a dict, cannot access key '%s'; "
            "placeholder kept",
            step_id,
            accessor,
        )
        return placeholder

    return _VAR_PATTERN.sub(_replace, template)


# ---------------------------------------------------------------------------
# Generic format_prompt — сохранён для обратной совместимости
# ---------------------------------------------------------------------------

def format_prompt(template: str, variables: dict[str, Any]) -> str:
    """Форматирует шаблон через .format_map с безопасным fallback для отсутствующих ключей.

    DEPRECATED: не использовать в новых пайплайнах.
    Для DAG-шагов используй resolve_step_vars() с паттерном {STEP_ID.result}/{STEP_ID.key}.

    Единственный активный вызов:
        clarification_fsm.generate_next_question — шаблон с плейсхолдерами
        {missing_fields} и {collected_fields}.

    Условие удаления: мигрировать generate_next_question на resolve_step_vars
    (потребует переименования плейсхолдеров в шаблоне «clarification» в PromptPack).
    После этого удалить format_prompt и _stringify.
    """

    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    normalized = {key: _stringify(value) for key, value in variables.items()}
    return template.format_map(SafeDict(normalized))


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)
