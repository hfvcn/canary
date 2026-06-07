from __future__ import annotations

from cccc.ralph.models import Plan, TaskSpec
from cccc.ralph.validation_rules.coverage import (
    W_SECURITY_REVIEW_NOT_INDEPENDENT,
    _check_security_reviewer_assignment,
)
from cccc.ralph.validator import validate


def _task(
    task_id: str,
    *,
    title: str = "",
    goal_behavior: str = "",
    role: str = "leaf",
    claimed_paths: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=title,
        role=role,
        claimed_paths=claimed_paths or [],
        goal_behavior=goal_behavior,
    )


def test_security_review_title_with_different_role_does_not_warn() -> None:
    plan = Plan(tasks=[
        _task("impl", claimed_paths=["src/service.py"], role="leaf"),
        _task("review", title="security-review", role="verification"),
    ])

    assert _check_security_reviewer_assignment(plan, plan.tasks) == []


def test_security_review_title_with_same_role_warns() -> None:
    plan = Plan(tasks=[
        _task("impl", claimed_paths=["src/service.py"], role="leaf"),
        _task("review", title="security review", role="leaf"),
    ])

    assert _check_security_reviewer_assignment(plan, plan.tasks) == [W_SECURITY_REVIEW_NOT_INDEPENDENT]


def test_no_security_review_task_returns_empty_list() -> None:
    plan = Plan(tasks=[
        _task("impl", claimed_paths=["src/service.py"], role="leaf"),
        _task("tests", claimed_paths=["tests/test_service.py"], role="verification"),
    ])

    assert _check_security_reviewer_assignment(plan, plan.tasks) == []


def test_goal_behavior_independent_security_review_is_detected() -> None:
    plan = Plan(tasks=[
        _task("impl", claimed_paths=["src/service.py"], role="leaf"),
        _task("review", goal_behavior="Perform an independent security review for auth changes", role="leaf"),
    ])

    assert _check_security_reviewer_assignment(plan, plan.tasks) == [W_SECURITY_REVIEW_NOT_INDEPENDENT]


def test_validate_emits_security_review_not_independent_warning() -> None:
    plan = Plan(tasks=[
        _task("impl", claimed_paths=["src/service.py"], role="leaf"),
        _task("review", title="security review", role="leaf"),
    ])

    warning_codes = [issue.code for issue in validate(plan).warnings]

    assert W_SECURITY_REVIEW_NOT_INDEPENDENT in warning_codes
