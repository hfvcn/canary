from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationIssue,
)
from cccc.ralph.validator import validate


def _task(task_id: str, addresses: list[str]) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=[f"src/{task_id.lower()}.py"],
        acceptance_criteria=f"{task_id} complete",
        verification=Verification(
            level="unit",
            checks=[
                CheckSpec(
                    name=f"{task_id} behavior test",
                    command=f"pytest tests/{task_id.lower()}_test.py",
                )
            ],
            covers=VerificationCovers(tasks=[task_id]),
        ),
        addresses=addresses,
    )


def _issues_by_code(plan: Plan, code: str) -> list[ValidationIssue]:
    report = validate(plan)
    issues = [*report.errors, *report.warnings, *report.hints]
    return [issue for issue in issues if issue.code == code]


def test_same_prefix_addresses_do_not_warn() -> None:
    plan = Plan(tasks=[_task("T1", ["RO-74", "RO-75"])])

    assert _issues_by_code(plan, "W_TASK_ADDRESSES_DISJOINT") == []
    assert _issues_by_code(plan, "H_DUPLICATE_ISSUE_ADDRESS") == []


def test_mixed_prefix_addresses_emit_warning() -> None:
    plan = Plan(tasks=[_task("T1", ["RO-74", "RL-7"])])

    issues = _issues_by_code(plan, "W_TASK_ADDRESSES_DISJOINT")

    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {
        "task_id": "T1",
        "address_groups": {"RO": ["RO-74"], "RL": ["RL-7"]},
    }


def test_single_address_does_not_warn() -> None:
    plan = Plan(tasks=[_task("T1", ["RO-74"])])

    assert _issues_by_code(plan, "W_TASK_ADDRESSES_DISJOINT") == []


def test_empty_addresses_do_not_warn() -> None:
    plan = Plan(tasks=[_task("T1", [])])

    assert _issues_by_code(plan, "W_TASK_ADDRESSES_DISJOINT") == []
    assert _issues_by_code(plan, "H_DUPLICATE_ISSUE_ADDRESS") == []


def test_duplicate_issue_address_across_tasks_emits_hint() -> None:
    plan = Plan(tasks=[
        _task("T1", ["RO-74"]),
        _task("T2", ["RO-74"]),
    ])

    issues = _issues_by_code(plan, "H_DUPLICATE_ISSUE_ADDRESS")

    assert len(issues) == 1
    assert issues[0].severity == "hint"
    assert issues[0].task_ids == ["T1", "T2"]
    assert issues[0].evidence == {
        "issue_id": "RO-74",
        "addressing_tasks": ["T1", "T2"],
    }
    assert _issues_by_code(plan, "W_TASK_ADDRESSES_DISJOINT") == []
