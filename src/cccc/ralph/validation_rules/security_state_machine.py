"""State-machine concurrency safety validation."""

from __future__ import annotations

from typing import Any

from ..models import Plan, ValidationIssue

W_STATE_MACHINE_CONCURRENCY_UNVERIFIED = "W_STATE_MACHINE_CONCURRENCY_UNVERIFIED"
_STATE_MACHINE_TASK_KEYWORDS = (
    "claim",
    "state transition",
    "status update",
    "状态机",
    "竞争",
    "并发",
    "atomic",
    "lock",
)
_CONCURRENCY_KEYWORDS = (
    "concurrent",
    "race",
    "atomic",
    "lock",
    "idempotent",
    "条件更新",
    "版本号",
    "乐观锁",
    "compare-and-swap",
    "cas",
    "version",
)


def check_state_machine_concurrency_safety(
    plan: Plan,
    tasks: list[object] | None = None,
    **kwargs: object,
) -> list[str]:
    del kwargs
    candidate_tasks = list(tasks or getattr(plan, "tasks", []) or [])
    return [W_STATE_MACHINE_CONCURRENCY_UNVERIFIED for _task, _evidence in _state_machine_gaps(candidate_tasks)]


def build_state_machine_concurrency_issues(plan: Plan) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for task, evidence in _state_machine_gaps(list(plan.tasks)):
        issues.append(ValidationIssue(
            code=W_STATE_MACHINE_CONCURRENCY_UNVERIFIED,
            severity="warning",
            message=(
                f"state-machine task '{getattr(task, 'id', '')}' lacks explicit concurrency-safety "
                "evidence in acceptance_criteria, verification.checks, or mock_tests"
            ),
            task_ids=[str(getattr(task, "id", ""))],
            evidence={
                "acceptance_criteria_has_concurrency_keyword": evidence["acceptance_criteria"],
                "verification_checks_have_concurrency_keyword": evidence["verification_checks"],
                "mock_tests_have_concurrency_keyword": evidence["mock_tests"],
            },
        ))
    return issues


def _state_machine_gaps(tasks: list[object]) -> list[tuple[object, dict[str, bool]]]:
    gaps: list[tuple[object, dict[str, bool]]] = []
    for task in tasks:
        if not _is_state_machine_task(task):
            continue
        evidence = _task_concurrency_evidence(task)
        if any(evidence.values()):
            continue
        gaps.append((task, evidence))
    return gaps


def _is_state_machine_task(task: object) -> bool:
    goal_behavior = str(getattr(task, "goal_behavior", "") or "")
    return _text_has_any_token(goal_behavior, _STATE_MACHINE_TASK_KEYWORDS)


def _task_concurrency_evidence(task: object) -> dict[str, bool]:
    verification = getattr(task, "verification", None)
    check_text = " ".join(
        f"{getattr(check, 'name', '')} {getattr(check, 'command', '')}"
        for check in getattr(verification, "checks", []) or []
    )
    mock_text = " ".join(_mock_test_text(mock_test) for mock_test in getattr(verification, "mock_tests", []) or [])
    return {
        "acceptance_criteria": _text_has_any_token(
            str(getattr(task, "acceptance_criteria", "") or ""),
            _CONCURRENCY_KEYWORDS,
        ),
        "verification_checks": bool(check_text) and _text_has_any_token(check_text, _CONCURRENCY_KEYWORDS),
        "mock_tests": bool(mock_text) and _text_has_any_token(mock_text, _CONCURRENCY_KEYWORDS),
    }


def _mock_test_text(mock_test: object) -> str:
    return " ".join([
        str(getattr(mock_test, "name", "") or ""),
        str(getattr(mock_test, "description", "") or ""),
        str(getattr(mock_test, "setup_command", "") or ""),
        str(getattr(mock_test, "verify_command", "") or ""),
        str(getattr(mock_test, "input", "") or ""),
        str(getattr(mock_test, "expected_output", "") or ""),
    ])


def _text_has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in tokens)
