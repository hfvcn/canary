"""Discipline checks for agent prompt modification flows."""

from __future__ import annotations

from typing import Iterable

from ..models import Plan, TaskSpec, ValidationIssue

AGENT_PATH_DIRECTORY = ".cccc/agents/"
AGENT_PATH_MARKERS = ("prompt_projection", "tuned_agent", "agent_registry")
PROMOTION_KEYWORDS = ("promotion", "tuning")
AGENT_PROMPT_UPDATE_KIND = "agent_prompt_update"
DIRECT_MODIFICATION_CODE = "E_AGENT_PROMPT_DIRECT_MODIFICATION"


def build_agent_prompt_direct_modification_issues(
    plan: Plan,
) -> list[ValidationIssue]:
    tasks_by_id = {task.id: task for task in plan.tasks}
    issues: list[ValidationIssue] = []
    for task in plan.tasks:
        matched_paths = _matched_agent_paths(task.claimed_paths)
        if not matched_paths:
            continue
        if _has_promotion_dependency(task, tasks_by_id):
            continue
        if _has_promotion_verification_cover(task):
            continue
        if _has_agent_prompt_update_contract(task):
            continue
        issues.append(ValidationIssue(
            code=DIRECT_MODIFICATION_CODE,
            severity="error",
            message=(
                f"task '{task.id}' modifies agent prompt artifacts without "
                "structured promotion evidence"
            ),
            task_ids=[task.id],
            evidence={"claimed_paths": matched_paths},
        ))
    return issues


def _matched_agent_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if _is_agent_prompt_path(path)]


def _is_agent_prompt_path(path: str) -> bool:
    normalized_path = path.replace("\\", "/").casefold()
    if AGENT_PATH_DIRECTORY in normalized_path:
        return normalized_path.endswith(".yaml")
    return any(marker in normalized_path for marker in AGENT_PATH_MARKERS)


def _has_promotion_dependency(
    task: TaskSpec,
    tasks_by_id: dict[str, TaskSpec],
) -> bool:
    return any(
        _has_promotion_text(_task_summary(tasks_by_id[dependency_id]))
        for dependency_id in task.depends_on
        if dependency_id in tasks_by_id
    )


def _has_promotion_verification_cover(task: TaskSpec) -> bool:
    verification = task.verification
    if verification is None:
        return False
    return any(
        _has_promotion_text(reference)
        for reference in _verification_cover_references(task)
    )


def _verification_cover_references(task: TaskSpec) -> Iterable[str]:
    verification = task.verification
    if verification is None:
        return ()
    covers = verification.covers
    return (*covers.tasks, *covers.paths, *covers.flows)


def _has_agent_prompt_update_contract(task: TaskSpec) -> bool:
    return any(
        contract.kind.casefold() == AGENT_PROMPT_UPDATE_KIND
        for contract in task.provides
    )


def _task_summary(task: TaskSpec) -> str:
    return "\n".join((task.title, task.goal_behavior))


def _has_promotion_text(value: str) -> bool:
    normalized_value = value.casefold()
    return any(keyword in normalized_value for keyword in PROMOTION_KEYWORDS)
