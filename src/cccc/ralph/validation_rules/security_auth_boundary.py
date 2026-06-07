"""Auth boundary malformed-input coverage checks."""

from __future__ import annotations

from typing import Callable

from ..models import Plan, ValidationIssue

_MALFORMED_TOKENS = (
    "malformed",
    "invalid type",
    "non-integer",
    "boundary",
    "valueerror",
    "typeerror",
)
_REJECTION_TOKENS = (
    "assert",
    "4xx",
    "401",
    "403",
    "422",
    "denied",
    "error",
    "rejected",
    "forbidden",
)

FlowMatcher = Callable[[object], bool]
FlowCoverResolver = Callable[[Plan, object], list[object]]


def run_auth_boundary_type_safety(
    plan: Plan,
    tasks: list[object] | None,
    *,
    flow_requires_auth_verification: FlowMatcher,
    covering_tasks_for_flow: FlowCoverResolver,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not flow_requires_auth_verification(flow):
            continue
        covering_tasks = list(tasks) if tasks is not None else covering_tasks_for_flow(plan, flow)
        issue = _build_auth_boundary_issue(flow, covering_tasks)
        if issue is not None:
            issues.append(issue)
    return issues


def _build_auth_boundary_issue(
    flow: object,
    covering_tasks: list[object],
) -> ValidationIssue | None:
    if not covering_tasks:
        return None
    combined_text = " ".join(_task_auth_boundary_text(task) for task in covering_tasks)
    has_malformed = _text_has_any_token(combined_text, _MALFORMED_TOKENS)
    has_rejection = _text_has_any_token(combined_text, _REJECTION_TOKENS)
    if has_malformed and has_rejection:
        return None
    return ValidationIssue(
        code="W_AUTH_TYPE_CAST_UNGUARDED",
        severity="warning",
        message=(
            f"auth flow '{getattr(flow, 'id', '')}' lacks malformed-input rejection "
            "coverage for auth boundary type safety"
        ),
        task_ids=[str(getattr(task, "id", "")) for task in covering_tasks],
        evidence={
            "flow_id": getattr(flow, "id", ""),
            "surface_type": getattr(flow, "surface_type", None),
            "has_malformed_token": has_malformed,
            "has_rejection_token": has_rejection,
        },
    )


def _task_auth_boundary_text(task: object) -> str:
    parts = [str(getattr(task, "acceptance_criteria", "") or "")]
    verification = getattr(task, "verification", None)
    if verification is None:
        return " ".join(part for part in parts if part)
    for check in getattr(verification, "checks", []) or []:
        parts.append(f"{getattr(check, 'name', '')} {getattr(check, 'command', '')}")
    for mock_test in getattr(verification, "mock_tests", []) or []:
        parts.extend(_mock_test_parts(mock_test))
    return " ".join(part for part in parts if part)


def _mock_test_parts(mock_test: object) -> list[str]:
    return [
        str(getattr(mock_test, "name", "") or ""),
        str(getattr(mock_test, "description", "") or ""),
        str(getattr(mock_test, "setup_command", "") or ""),
        str(getattr(mock_test, "verify_command", "") or ""),
        str(getattr(mock_test, "input", "") or ""),
        str(getattr(mock_test, "expected_output", "") or ""),
    ]


def _text_has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in tokens)
