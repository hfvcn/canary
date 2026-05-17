"""Tests for AD-3 Aegis discipline validation rules."""

from __future__ import annotations

from typing import Any

import pytest

from cccc.ralph.cli import main
from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validator import validate

AEGIS_CODES = frozenset({
    "E_AEGIS_PLACEHOLDER_CONTENT",
    "E_AEGIS_RETIREMENT_TRACK_MISSING",
    "W_AEGIS_FIX_NO_REPAIR_TRACK",
    "W_AEGIS_TDD_NO_TEST_PATH",
    "W_AEGIS_COMPLEX_MISSING_BASELINE",
})


def _base_task(task_id: str = "T1", **overrides: Any) -> dict[str, Any]:
    task = {
        "id": task_id,
        "title": "Chore metadata update",
        "goal_behavior": "Refresh metadata wording.",
        "acceptance_criteria": "Metadata wording is concrete.",
        "claimed_paths": [f"docs/{task_id}.md"],
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/ralph/test_aegis_rules.py -v",
            "covers": {"tasks": [task_id]},
        },
    }
    task.update(overrides)
    return task


def _make_plan(*tasks: dict[str, Any]) -> Plan:
    return Plan.model_validate({"tasks": list(tasks), "semantic_mode": "off"})


def _all_issues(report) -> list[ValidationIssue]:
    return [*report.errors, *report.warnings, *report.hints]


def _issue(report, code: str) -> ValidationIssue:
    matches = [issue for issue in _all_issues(report) if issue.code == code]
    assert len(matches) == 1
    return matches[0]


def _aegis_codes(report) -> list[str]:
    return [issue.code for issue in _all_issues(report) if issue.code in AEGIS_CODES]


def test_placeholder_content_reports_error() -> None:
    plan = _make_plan(_base_task(title="TBD fill in validation behavior"))

    report = validate(plan)

    issue = _issue(report, "E_AEGIS_PLACEHOLDER_CONTENT")
    assert issue.severity == "error"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {"field": "title"}


def test_aegis_placeholder_skips_path_like_tokens() -> None:
    plan = _make_plan(
        _base_task(task_id="T1", goal_behavior="Update TODO.md with the final summary."),
        _base_task(task_id="T2", goal_behavior="Refresh the todo-list identifier mapping."),
        _base_task(task_id="T3", goal_behavior="Reference todo/问题清单-v5-ralph.md."),
        _base_task(task_id="T4", goal_behavior="Review standalone todo before editing."),
    )

    report = validate(plan)

    issue = _issue(report, "E_AEGIS_PLACEHOLDER_CONTENT")
    assert issue.task_ids == ["T4"]
    assert issue.evidence == {"field": "goal_behavior"}


def test_refactor_patch_shape_requires_retirement_track() -> None:
    plan = _make_plan(_base_task(
        title="Refactor legacy fallback adapter",
        goal_behavior="Replace the compat guard path.",
        aegis={"intent": "refactor"},
    ))

    report = validate(plan)

    issue = _issue(report, "E_AEGIS_RETIREMENT_TRACK_MISSING")
    assert issue.severity == "error"
    assert issue.task_ids == ["T1"]


def test_fix_without_repair_track_reports_warning() -> None:
    plan = _make_plan(_base_task(
        title="Fix validator branch",
        claimed_paths=["src/cccc/ralph/validator.py", "tests/ralph/test_aegis_rules.py"],
        aegis={"intent": "fix"},
    ))

    report = validate(plan)

    issue = _issue(report, "W_AEGIS_FIX_NO_REPAIR_TRACK")
    assert issue.severity == "warning"
    assert issue.task_ids == ["T1"]


@pytest.mark.parametrize(
    ("intent", "title"),
    [
        ("fix", "Fix validation rule"),
        ("feature", "Implement validation rule"),
    ],
)
def test_fix_or_feature_without_claimed_test_path_reports_warning(
    intent: str,
    title: str,
) -> None:
    plan = _make_plan(_base_task(
        title=title,
        claimed_paths=["src/cccc/ralph/validation_rules/discipline.py"],
        aegis={"intent": intent},
    ))

    report = validate(plan)

    issue = _issue(report, "W_AEGIS_TDD_NO_TEST_PATH")
    assert issue.severity == "warning"
    assert issue.evidence == {
        "claimed_paths": ["src/cccc/ralph/validation_rules/discipline.py"]
    }


def test_complex_task_without_baseline_refs_reports_warning() -> None:
    plan = _make_plan(
        _base_task("D1"),
        _base_task("D2"),
        _base_task("D3"),
        _base_task(
            "T4",
            title="Coordinate integration task",
            depends_on=["D1", "D2", "D3"],
            aegis={"intent": "chore"},
        ),
    )

    report = validate(plan)

    issue = _issue(report, "W_AEGIS_COMPLEX_MISSING_BASELINE")
    assert issue.severity == "warning"
    assert issue.task_ids == ["T4"]
    assert issue.evidence == {"reason": "depends_on>=3"}


def test_plain_non_fix_non_refactor_task_has_no_aegis_rules() -> None:
    report = validate(_make_plan(_base_task()))

    assert _aegis_codes(report) == []


def test_explain_outputs_placeholder_rule_doc(capsys) -> None:
    exit_code = main(["explain", "--code", "E_AEGIS_PLACEHOLDER_CONTENT"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "E_AEGIS_PLACEHOLDER_CONTENT" in captured.out
    assert "placeholder" in captured.out.casefold()
