from __future__ import annotations

from typing import Any

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


TARGET_CODE = "E_VERIFICATION_NON_GATING"


def _all_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _errors_by_code(report, code: str) -> list:
    return [issue for issue in report.errors if issue.code == code]


def _plan(verification: dict[str, Any] | None) -> Plan:
    task: dict[str, Any] = {
        "id": "T1",
        "claimed_paths": ["src/t1.py"],
        "goal_behavior": "verification should gate task completion",
        "acceptance_criteria": "task completion is blocked by verification failures",
    }
    if verification is not None:
        task["verification"] = verification
    return Plan.model_validate({"tasks": [task]})


def test_all_advisory_checks_emit_non_gating_issue() -> None:
    plan = _plan({
        "level": "unit",
        "command": "",
        "checks": [
            {"name": "behavior-1", "command": "pytest tests/a.py -q", "required": False},
            {"name": "behavior-2", "command": "pytest tests/b.py -q", "required": False},
        ],
        "covers": {"tasks": ["T1"]},
    })

    report = validate(plan)
    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {
        "checks_count": 2,
        "has_required": False,
        "top_command_empty": True,
    }


def test_required_check_with_empty_command_still_gates() -> None:
    plan = _plan({
        "level": "unit",
        "command": "",
        "checks": [
            {"name": "behavior-gate", "command": "", "required": True},
        ],
        "covers": {"tasks": ["T1"]},
    })

    report = validate(plan)

    assert TARGET_CODE not in _all_codes(report)


def test_required_defaults_true_when_omitted() -> None:
    plan = _plan({
        "level": "unit",
        "command": "",
        "checks": [
            {"name": "behavior-default-required", "command": "pytest tests/t1.py -q"},
        ],
        "covers": {"tasks": ["T1"]},
    })

    report = validate(plan)

    assert TARGET_CODE not in _all_codes(report)


def test_empty_top_level_command_without_checks_emits_issue() -> None:
    plan = _plan({
        "level": "unit",
        "command": "   ",
        "checks": [],
        "covers": {"tasks": ["T1"]},
    })

    report = validate(plan)
    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].evidence == {
        "checks_count": 0,
        "has_required": False,
        "top_command_empty": True,
    }


def test_non_empty_top_level_command_without_checks_is_silent() -> None:
    plan = _plan({
        "level": "unit",
        "command": "python -m pytest tests/t1.py -q",
        "checks": [],
        "covers": {"tasks": ["T1"]},
    })

    report = validate(plan)

    assert TARGET_CODE not in _all_codes(report)


def test_missing_verification_is_silent_for_this_rule() -> None:
    report = validate(_plan(None))

    assert TARGET_CODE not in _all_codes(report)
