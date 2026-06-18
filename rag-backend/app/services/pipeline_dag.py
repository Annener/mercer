"""
pipeline_dag.py — чистый DAG-движок для пайплайнов Mercer.

Нет зависимостей от БД, HTTP или FastAPI.
Входные данные: list[PipelineStep] из shared_contracts.

Публичный API:
    build_dag(steps)           -> dict[str, list[str]]
    topological_sort(steps)    -> list[list[str]]
    detect_cycles(steps)       -> list[str] | None
    validate_dag(steps)        -> list[str]   # список ошибок, [] = OK
    get_execution_levels(steps)-> list[list[PipelineStep]]
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared_contracts.models import PipelineStep


def build_dag(steps: list["PipelineStep"]) -> dict[str, list[str]]:
    """Строит граф смежности: {step_id: [child_step_ids]}.

    Ребро A→B означает: шаг B зависит от шага A (B.after_step_ids содержит A).
    """
    ids = {s.step_id for s in steps}
    children: dict[str, list[str]] = {s.step_id: [] for s in steps}
    for step in steps:
        for parent_id in step.after_step_ids:
            if parent_id in ids:
                children[parent_id].append(step.step_id)
    return children


def topological_sort(steps: list["PipelineStep"]) -> list[list[str]]:
    """Топологическая сортировка алгоритмом Кана.

    Возвращает список уровней (список списков step_id).
    Шаги одного уровня не зависят друг от друга и могут выполняться параллельно.
    Если в графе есть цикл — возвращает пустой список.
    """
    in_degree: dict[str, int] = {s.step_id: len(s.after_step_ids) for s in steps}
    children = build_dag(steps)

    # Учитываем только рёбра к существующим узлам
    existing = {s.step_id for s in steps}
    in_degree = {
        s.step_id: sum(1 for p in s.after_step_ids if p in existing)
        for s in steps
    }

    queue: deque[str] = deque(
        step_id for step_id, deg in in_degree.items() if deg == 0
    )
    levels: list[list[str]] = []

    while queue:
        level = list(queue)
        queue.clear()
        levels.append(level)
        for node in level:
            for child in children.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    total_sorted = sum(len(lvl) for lvl in levels)
    if total_sorted != len(steps):
        # Цикл — вернуть пустой список
        return []

    return levels


def detect_cycles(steps: list["PipelineStep"]) -> list[str] | None:
    """DFS-поиск цикла в графе.

    Возвращает список step_id, образующих цикл, или None если цикла нет.
    """
    children = build_dag(steps)
    existing = {s.step_id for s in steps}

    # Состояния узлов: 0=белый(необработан), 1=серый(в стеке), 2=чёрный(готов)
    color: dict[str, int] = {s.step_id: 0 for s in steps}
    stack: list[str] = []
    cycle_found: list[str] = []

    def dfs(node: str) -> bool:
        color[node] = 1
        stack.append(node)
        for child in children.get(node, []):
            if child not in existing:
                continue
            if color[child] == 1:
                # Нашли цикл — извлечь его из стека
                idx = stack.index(child)
                cycle_found.extend(stack[idx:])
                return True
            if color[child] == 0 and dfs(child):
                return True
        stack.pop()
        color[node] = 2
        return False

    for step in steps:
        if color[step.step_id] == 0:
            if dfs(step.step_id):
                return cycle_found

    return None


def validate_dag(steps: list["PipelineStep"]) -> list[str]:
    """Агрегирует все ошибки структуры DAG.

    Возвращает список строк с описаниями ошибок. Пустой список = граф корректен.
    """
    errors: list[str] = []
    existing = {s.step_id for s in steps}

    # 1. Нет ни одного стартового шага
    start_steps = [s for s in steps if not s.after_step_ids]
    if not start_steps:
        errors.append(
            "DAG не имеет стартового шага: хотя бы один шаг должен иметь after_step_ids=[]"
        )

    # 2. Ссылки на несуществующие step_id
    for step in steps:
        for parent_id in step.after_step_ids:
            if parent_id not in existing:
                errors.append(
                    f"Шаг '{step.step_id}' ссылается на несуществующий after_step_id='{parent_id}'"
                )

    # 3. Цикл в графе
    cycle = detect_cycles(steps)
    if cycle is not None:
        errors.append(
            f"Обнаружен цикл в DAG: {' -> '.join(cycle)} -> {cycle[0]}"
        )

    # 4. validation-шаг без потомков (предупреждение, не блокирующая ошибка)
    children = build_dag(steps)
    for step in steps:
        if step.type == "validation" and not children.get(step.step_id):
            errors.append(
                f"Шаг validation '{step.step_id}' не имеет потомков — "
                f"пайплайн завершится после паузы без FinalComposition"
            )

    return errors


def get_execution_levels(steps: list["PipelineStep"]) -> list[list["PipelineStep"]]:
    """Возвращает уровни параллельности с объектами шагов.

    Использует topological_sort для вычисления уровней,
    затем сопоставляет step_id → PipelineStep.

    Raises:
        ValueError: если в графе обнаружен цикл.
    """
    levels_ids = topological_sort(steps)
    if not levels_ids and steps:
        raise ValueError(
            "Невозможно вычислить уровни исполнения: в DAG обнаружен цикл. "
            f"Детали: {detect_cycles(steps)}"
        )

    step_map = {s.step_id: s for s in steps}
    return [[step_map[sid] for sid in level] for level in levels_ids]
