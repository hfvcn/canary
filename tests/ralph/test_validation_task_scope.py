from __future__ import annotations

from typing import Any

from cccc.ralph.models import Plan, ValidationIssue, ValidationReport
from cccc.ralph.validation_rules import get_all_rules
from cccc.ralph.validation_rules.structural import _check_task_paths_outside_plan_scope
from cccc.ralph.validator import validate


TARGET_CODE = "E_TASK_PATH_OUTSIDE_PLAN_SCOPE"
_UNSET = object()


def _task(
    *,
    claimed_paths: list[str],
    awareness_paths: list[str] | object = _UNSET,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": "T1",
        "claimed_paths": claimed_paths,
        "goal_behavior": "validate scoped task paths",
        "acceptance_criteria": "task paths stay within plan scope",
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/ralph/test_validation_task_scope.py -q",
            "checks": [
                {
                    "name": "unit",
                    "command": "python -m pytest tests/ralph/test_validation_task_scope.py -q",
                }
            ],
            "covers": {"tasks": ["T1"], "paths": list(claimed_paths)},
        },
    }
    if awareness_paths is not _UNSET:
        task["awareness_paths"] = awareness_paths
    return task


def _plan(
    *,
    plan_scope: list[str],
    claimed_paths: list[str],
    awareness_paths: list[str] | object = _UNSET,
) -> Plan:
    return Plan.model_validate({
        "plan_scope": plan_scope,
        "tasks": [_task(
            claimed_paths=claimed_paths,
            awareness_paths=awareness_paths,
        )],
    })


def _errors_by_code(report: ValidationReport, code: str) -> list[ValidationIssue]:
    return [issue for issue in report.errors if issue.code == code]


def _all_codes(report: ValidationReport) -> set[str]:
    return {
        issue.code
        for issue in [*report.errors, *report.warnings, *report.hints]
    }


def test_claimed_paths_outside_plan_scope_emit_error() -> None:
    assert _check_task_paths_outside_plan_scope in get_all_rules()
    report = validate(_plan(
        plan_scope=["src/auth"],
        claimed_paths=["src/auth/service.py", "src/authz.py"],
    ))

    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {
        "task_id": "T1",
        "kind": "claimed_paths",
        "offending_paths": ["src/authz.py"],
        "plan_scope": ["src/auth"],
    }


def test_awareness_paths_outside_plan_scope_emit_error() -> None:
    report = validate(_plan(
        plan_scope=["src/auth"],
        claimed_paths=["src/auth/service.py"],
        awareness_paths=["src/auth/notes.md", "docs/auth.md"],
    ))

    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].evidence["kind"] == "awareness_paths"
    assert issues[0].evidence["offending_paths"] == ["docs/auth.md"]


def test_paths_inside_plan_scope_are_silent() -> None:
    report = validate(_plan(
        plan_scope=["src/auth"],
        claimed_paths=["src/auth", "src/auth/service.py"],
        awareness_paths=["src/auth/notes.md"],
    ))

    assert TARGET_CODE not in _all_codes(report)


def test_empty_plan_scope_disables_task_path_scope_rule() -> None:
    report = validate(_plan(
        plan_scope=[],
        claimed_paths=["src/outside.py"],
        awareness_paths=["docs/auth.md"],
    ))

    assert TARGET_CODE not in _all_codes(report)


def test_awareness_paths_none_is_silent_when_claimed_paths_are_in_scope() -> None:
    plan = _plan(
        plan_scope=["src/auth"],
        claimed_paths=["src/auth/service.py"],
    )
    plan.tasks[0].awareness_paths = None  # type: ignore[assignment]

    issues = _check_task_paths_outside_plan_scope(plan)

    assert [issue for issue in issues if issue.code == TARGET_CODE] == []
