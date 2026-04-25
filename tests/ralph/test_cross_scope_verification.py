"""Tests for W_VERIFICATION_CROSS_SCOPE — RO-24.

Detects when a task's verification command references paths claimed by another task.
"""
from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


def _warnings_by_code(report, code: str) -> list:
    return [issue for issue in report.warnings if issue.code == code]


def _make_plan(tasks: list[dict]) -> Plan:
    return Plan.model_validate({"tasks": tasks})


def _base_checks(command: str = "pytest src/tests/") -> list[dict]:
    return [
        {"name": "compile", "command": "python -m py_compile src/main.py"},
        {"name": "behavior", "command": command},
    ]


def _two_task_plan(
    *,
    t1_checks_command: str,
    t1_claimed: list[str],
    t2_claimed: list[str],
) -> Plan:
    """Build a minimal 2-task plan with T2 depending on T1 and cross-task verification."""
    return _make_plan([
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": t1_claimed,
            "goal_behavior": "Implement feature A.",
            "acceptance_criteria": "Feature A works.",
            "verification": {
                "level": "unit",
                "command": "",
                "checks": [
                    {"name": "compile", "command": "python -m py_compile src/main.py"},
                    {"name": "behavior", "command": t1_checks_command},
                ],
                "covers": {"tasks": ["T1"]},
            },
        },
        {
            "id": "T2",
            "role": "integration",
            "depends_on": ["T1"],
            "claimed_paths": t2_claimed,
            "goal_behavior": "Integrate feature A with backend tests.",
            "acceptance_criteria": "Integration works.",
            "verification": {
                "level": "integration",
                "command": "",
                "checks": [
                    {"name": "compile", "command": "python -m py_compile backend/main.py"},
                    {"name": "integration", "command": "pytest backend/tests/"},
                ],
                "covers": {"tasks": ["T1", "T2"]},
            },
        },
    ])


def test_cross_scope_warning() -> None:
    """T1 runs 'pytest backend/tests/' but backend/tests/ is claimed by T2, not T1."""
    plan = _two_task_plan(
        t1_checks_command="pytest backend/tests/",
        t1_claimed=["src/feature_a/"],
        t2_claimed=["backend/tests/"],
    )

    report = validate(plan)

    issues = _warnings_by_code(report, "W_VERIFICATION_CROSS_SCOPE")
    assert len(issues) >= 1, f"Expected W_VERIFICATION_CROSS_SCOPE warning, got: {report.warnings}"
    issue = issues[0]
    assert issue.evidence["check_name"] == "behavior"
    assert issue.evidence["referenced_path"] == "backend/tests/"
    assert issue.evidence["owning_task"] == "T2"
    assert "T1" in issue.task_ids


def test_own_scope_no_warning() -> None:
    """T1 runs 'pytest src/tests/' and src/tests/ is in T1's own claimed_paths."""
    plan = _two_task_plan(
        t1_checks_command="pytest src/tests/",
        t1_claimed=["src/"],
        t2_claimed=["backend/tests/"],
    )

    report = validate(plan)

    issues = _warnings_by_code(report, "W_VERIFICATION_CROSS_SCOPE")
    assert issues == [], f"Should not warn when path is in own scope, got: {issues}"


def test_no_checks_no_warning() -> None:
    """A task with no verification checks should not trigger cross-scope warnings."""
    plan = _make_plan([
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/"],
            "goal_behavior": "Implement feature.",
            "acceptance_criteria": "Feature works.",
            "verification": {
                "level": "unit",
                "command": "",
                "checks": [],
                "covers": {"tasks": ["T1"]},
            },
        },
        {
            "id": "T2",
            "role": "integration",
            "depends_on": ["T1"],
            "claimed_paths": ["backend/"],
            "goal_behavior": "Integrate.",
            "acceptance_criteria": "Integration works.",
            "verification": {
                "level": "integration",
                "command": "",
                "checks": [
                    {"name": "compile", "command": "python -m py_compile backend/main.py"},
                    {"name": "test", "command": "pytest backend/tests/"},
                ],
                "covers": {"tasks": ["T1", "T2"]},
            },
        },
    ])

    report = validate(plan)

    # T1 has no checks, so no cross-scope warning for T1
    t1_issues = [
        i for i in _warnings_by_code(report, "W_VERIFICATION_CROSS_SCOPE")
        if "T1" in i.task_ids
    ]
    assert t1_issues == [], f"T1 should not have cross-scope warnings: {t1_issues}"


def test_top_level_command_cross_scope() -> None:
    """The top-level verification.command is also checked for cross-scope references."""
    plan = _make_plan([
        {
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/feature/"],
            "goal_behavior": "Implement feature.",
            "acceptance_criteria": "Feature works.",
            "verification": {
                "level": "unit",
                "command": "pytest backend/integration/",
                "checks": [
                    {"name": "compile", "command": "python -m py_compile src/feature/main.py"},
                    {"name": "test", "command": "pytest src/feature/tests/"},
                ],
                "covers": {"tasks": ["T1"]},
            },
        },
        {
            "id": "T2",
            "role": "integration",
            "depends_on": ["T1"],
            "claimed_paths": ["backend/"],
            "goal_behavior": "Integrate.",
            "acceptance_criteria": "Integration works.",
            "verification": {
                "level": "integration",
                "command": "",
                "checks": [
                    {"name": "compile", "command": "python -m py_compile backend/main.py"},
                    {"name": "test", "command": "pytest backend/tests/"},
                ],
                "covers": {"tasks": ["T1", "T2"]},
            },
        },
    ])

    report = validate(plan)

    issues = _warnings_by_code(report, "W_VERIFICATION_CROSS_SCOPE")
    top_level = [i for i in issues if i.evidence.get("check_name") == "__top_level__"]
    assert len(top_level) >= 1, f"Expected top-level cross-scope warning, got: {issues}"
    assert top_level[0].evidence["referenced_path"] == "backend/integration/"
    assert top_level[0].evidence["owning_task"] == "T2"
