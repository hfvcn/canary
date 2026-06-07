"""Focused tests for AD-3 Aegis discipline rules."""

from __future__ import annotations

from typing import Any

import pytest

from cccc.ralph.models import Plan, ValidationIssue
from cccc.ralph.validation_rules import discipline_security
from cccc.ralph.validation_rules.discipline import (
    _DISCIPLINE_RULES,
    check_rule_registration_completeness,
    collect_discipline_issues,
)

PLACEHOLDER_CODE = "E_AEGIS_PLACEHOLDER_CONTENT"
RETIREMENT_CODE = "E_AEGIS_RETIREMENT_TRACK_MISSING"
REPAIR_CODE = "W_AEGIS_FIX_NO_REPAIR_TRACK"
TDD_CODE = "W_AEGIS_TDD_NO_TEST_PATH"
BASELINE_CODE = "W_AEGIS_COMPLEX_MISSING_BASELINE"
UNREGISTERED_RULE_CODE = "W_DISCIPLINE_RULE_UNREGISTERED"
TEST_FILE = "tests/test_aegis_discipline_rules.py"
ENTRYPOINT = "src/app/startup.py"


def test_ad3_rules_are_registered() -> None:
    registered = {rule.__name__ for rule in _DISCIPLINE_RULES}

    assert {
        "_check_placeholder_content",
        "_check_retirement_track",
        "_check_fix_repair_track",
        "_check_tdd_test_path",
        "_check_complex_baseline",
    } <= registered


def test_rule_registration_all_registered() -> None:
    assert check_rule_registration_completeness() == []


def test_rule_registration_detects_unregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _check_mock_rule(plan: Plan) -> list[ValidationIssue]:
        return []

    monkeypatch.setattr(
        discipline_security,
        "_check_mock_rule",
        _check_mock_rule,
        raising=False,
    )

    issues = check_rule_registration_completeness()

    assert [issue.code for issue in issues] == [UNREGISTERED_RULE_CODE]
    assert issues[0].evidence == {
        "module": "discipline_security",
        "rule": "_check_mock_rule",
    }


def test_rule_registration_runs_via_validator_not_collect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.ralph.validator import validate

    def _check_mock_rule(plan: Plan) -> list[ValidationIssue]:
        return []

    monkeypatch.setattr(
        discipline_security,
        "_check_mock_rule",
        _check_mock_rule,
        raising=False,
    )

    plan = _plan(_task())

    assert UNREGISTERED_RULE_CODE not in _codes(collect_discipline_issues(plan))
    assert [
        issue.code for issue in validate(plan).warnings
        if issue.code == UNREGISTERED_RULE_CODE
    ] == [UNREGISTERED_RULE_CODE]


def test_unfilled_content_reports_error() -> None:
    issues = _issues(_plan(_task(title="TBD validator branch")))

    issue = _only_issue(issues, PLACEHOLDER_CODE)
    assert issue.severity == "error"
    assert issue.task_ids == ["T1"]
    assert issue.evidence == {"field": "title"}


def test_placeholder_content_ignores_markers_inside_code_fences() -> None:
    issues = _issues(_plan(_task(
        goal_behavior=(
            "Replace parser behavior with concrete output.\n"
            "```python\n"
            "# TODO placeholder implementation note\n"
            "```\n"
            "The runtime branch returns parsed records."
        ),
    )))

    assert PLACEHOLDER_CODE not in _codes(issues)


def test_placeholder_content_ignores_markers_inside_inline_code() -> None:
    issues = _issues(_plan(_task(
        goal_behavior="Use `TODO placeholder` as a literal marker in the parser.",
    )))

    assert PLACEHOLDER_CODE not in _codes(issues)


def test_retirement_track_missing_for_refactor_provider_pattern() -> None:
    issues = _issues(_plan(_task(
        title="Refactor provider boundary",
        goal_behavior="Replace adapter route with concrete dispatch.",
        aegis={"intent": "refactor"},
    )))

    issue = _only_issue(issues, RETIREMENT_CODE)
    assert issue.severity == "error"
    assert issue.evidence == {"intent": "refactor"}


def test_retirement_track_missing_for_migration_provider_pattern() -> None:
    issues = _issues(_plan(_task(
        title="Migrate provider boundary",
        goal_behavior="Replace adapter route with concrete dispatch.",
        aegis={"intent": "migration"},
    )))

    issue = _only_issue(issues, RETIREMENT_CODE)
    assert issue.severity == "error"
    assert issue.evidence == {"intent": "migration"}


def test_retirement_track_ignores_refactor_without_target_shape() -> None:
    issues = _issues(_plan(_task(
        title="Refactor guard branch",
        goal_behavior="Move condition into a clearer function.",
        aegis={"intent": "refactor"},
    )))

    assert RETIREMENT_CODE not in _codes(issues)


def test_fix_repair_track_requires_root_cause() -> None:
    issues = _issues(_plan(_task(
        title="Fix validator branch",
        claimed_paths=["src/validator.py", TEST_FILE],
        aegis={"intent": "fix", "repair_track": {"root_cause": ""}},
    )))

    issue = _only_issue(issues, REPAIR_CODE)
    assert issue.severity == "warning"
    assert issue.task_ids == ["T1"]


def test_fix_repair_track_accepts_root_cause() -> None:
    issues = _issues(_plan(_task(
        title="Fix validator branch",
        claimed_paths=["src/validator.py", TEST_FILE],
        aegis={
            "intent": "fix",
            "repair_track": {"root_cause": "missing validation branch"},
        },
    )))

    assert REPAIR_CODE not in _codes(issues)


def test_tdd_test_path_reports_when_no_test_file_is_claimed() -> None:
    issues = _issues(_plan(_task(
        title="Implement parser feature",
        claimed_paths=["src/parser.py"],
        aegis={"intent": "feature"},
    )))

    issue = _only_issue(issues, TDD_CODE)
    assert issue.severity == "warning"
    assert issue.evidence == {"claimed_paths": ["src/parser.py"]}


def test_tdd_test_path_reports_when_claimed_paths_are_empty() -> None:
    issues = _issues(_plan(_task(
        title="Fix parser feature",
        claimed_paths=[],
        aegis={"intent": "fix"},
    )))

    issue = _only_issue(issues, TDD_CODE)
    assert issue.evidence == {"claimed_paths": []}


@pytest.mark.parametrize(
    ("task_overrides", "plan_overrides", "expected_reason"),
    [
        ({"depends_on": ["D1", "D2", "D3"]}, {}, "depends_on>=3"),
        ({"provides": [{"name": "runtime-api"}]}, {}, "contracts"),
        (
            {
                "claimed_paths": [ENTRYPOINT],
                "verification": {"level": "unit", "covers": {"flows": ["startup"]}},
            },
            {"critical_flows": [{"id": "startup", "entrypoints": [ENTRYPOINT]}]},
            "critical_flows",
        ),
    ],
)
def test_complex_task_without_baseline_refs_reports_warning(
    task_overrides: dict[str, Any],
    plan_overrides: dict[str, Any],
    expected_reason: str,
) -> None:
    tasks = [_task("D1"), _task("D2"), _task("D3"), _task("T4", **task_overrides)]
    issues = _issues(_plan(*tasks, **plan_overrides))

    issue = _only_issue(issues, BASELINE_CODE)
    assert issue.severity == "warning"
    assert issue.task_ids == ["T4"]
    assert issue.evidence == {"reason": expected_reason}


def test_complex_task_accepts_baseline_refs() -> None:
    issues = _issues(_plan(_task(
        depends_on=["D1", "D2", "D3"],
        aegis={"baseline_refs": ["plans/current.yaml#T1"]},
    )))

    assert BASELINE_CODE not in _codes(issues)


def _plan(*tasks: dict[str, Any], **overrides: Any) -> Plan:
    data = {"tasks": list(tasks), "semantic_mode": "off"}
    data.update(overrides)
    return Plan.model_validate(data)


def _task(task_id: str = "T1", **overrides: Any) -> dict[str, Any]:
    task = {
        "id": task_id,
        "title": "Refresh metadata",
        "goal_behavior": "Refresh concrete metadata wording.",
        "acceptance_criteria": "Concrete metadata wording is refreshed.",
        "claimed_paths": [f"docs/{task_id}.md"],
    }
    task.update(overrides)
    return task


def _issues(plan: Plan) -> list[ValidationIssue]:
    return collect_discipline_issues(plan)


def _codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def _only_issue(issues: list[ValidationIssue], code: str) -> ValidationIssue:
    matches = [issue for issue in issues if issue.code == code]
    assert len(matches) == 1
    return matches[0]
