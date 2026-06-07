from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.security import W_STATE_MACHINE_CONCURRENCY_UNVERIFIED
from cccc.ralph.validator import validate

TARGET_CODE = W_STATE_MACHINE_CONCURRENCY_UNVERIFIED


def _issues_by_code(report, code: str = TARGET_CODE) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _task(
    task_id: str,
    *,
    goal_behavior: str,
    acceptance_criteria: str = "state transition remains correct",
    checks: list[dict[str, str]] | None = None,
    mock_tests: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    check_specs = checks or [{"name": "unit-check", "command": "python -m pytest tests/unit/test_status.py -q"}]
    return {
        "id": task_id,
        "claimed_paths": ["src/workflow.py"],
        "goal_behavior": goal_behavior,
        "acceptance_criteria": acceptance_criteria,
        "verification": {
            "level": "unit",
            "command": check_specs[0]["command"],
            "checks": check_specs,
            "mock_tests": mock_tests or [],
        },
    }


def _plan(task: dict[str, object]) -> Plan:
    return Plan.model_validate({"tasks": [task]})


def test_state_machine_task_with_race_check_is_silent() -> None:
    plan = _plan(_task(
        "T1",
        goal_behavior="claim state transition for workflow completion",
        checks=[{"name": "race-check", "command": "python -m pytest tests/unit/test_status.py -q"}],
    ))

    assert _issues_by_code(validate(plan)) == []


def test_state_machine_task_with_atomic_acceptance_is_silent() -> None:
    plan = _plan(_task(
        "T1",
        goal_behavior="status update must preserve state transition ordering",
        acceptance_criteria="atomic update prevents duplicate completion",
    ))

    assert _issues_by_code(validate(plan)) == []


def test_state_machine_task_without_concurrency_evidence_warns() -> None:
    plan = _plan(_task(
        "T1",
        goal_behavior="claim state transition after workflow approval",
        acceptance_criteria="state transition completes successfully",
        checks=[{"name": "unit-check", "command": "python -m pytest tests/unit/test_status.py -q"}],
    ))

    issues = _issues_by_code(validate(plan))

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]


def test_non_state_machine_task_is_skipped() -> None:
    plan = _plan(_task(
        "T1",
        goal_behavior="render dashboard summary for completed workflows",
    ))

    assert _issues_by_code(validate(plan)) == []
