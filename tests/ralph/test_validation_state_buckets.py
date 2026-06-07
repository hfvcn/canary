from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.coverage import (
    _check_running_task_claims,
    _check_state_task_status_conflict,
)


def _plan(*, tasks: list[dict], state: dict) -> Plan:
    return Plan.model_validate({"tasks": tasks, "state": state})


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_completed_and_failed_share_same_task_id() -> None:
    issues = _check_state_task_status_conflict(_plan(
        tasks=[{"id": "T1"}],
        state={"completed_task_ids": ["T1"], "failed_task_ids": ["T1"]},
    ))

    assert len(_issues_by_code(issues, "E_STATE_TASK_STATUS_CONFLICT")) == 1


def test_completed_and_running_share_same_task_id() -> None:
    issues = _check_state_task_status_conflict(_plan(
        tasks=[{"id": "T1", "claimed_paths": ["src/task.py"]}],
        state={
            "completed_task_ids": ["T1"],
            "running_tasks": [{"task_id": "T1", "claimed_paths": ["src/task.py"]}],
        },
    ))

    assert len(_issues_by_code(issues, "E_STATE_TASK_STATUS_CONFLICT")) == 1


def test_duplicate_task_id_inside_failed_bucket_is_reported() -> None:
    issues = _check_state_task_status_conflict(_plan(
        tasks=[{"id": "T1"}],
        state={"failed_task_ids": ["T1", "T1"]},
    ))

    conflict = _issues_by_code(issues, "E_STATE_TASK_STATUS_CONFLICT")
    assert len(conflict) == 1
    assert conflict[0].evidence == {"bucket": "failed_task_ids", "task_id": "T1"}


def test_distinct_state_buckets_are_silent() -> None:
    issues = _check_state_task_status_conflict(_plan(
        tasks=[
            {"id": "T1", "claimed_paths": ["src/a.py"]},
            {"id": "T2", "claimed_paths": ["src/b.py"]},
            {"id": "T3", "claimed_paths": ["src/c.py"]},
        ],
        state={
            "completed_task_ids": ["T1"],
            "failed_task_ids": ["T2"],
            "running_tasks": [{"task_id": "T3", "claimed_paths": ["src/c.py"]}],
        },
    ))

    assert _issues_by_code(issues, "E_STATE_TASK_STATUS_CONFLICT") == []


def test_running_task_requires_non_empty_claimed_paths() -> None:
    issues = _check_running_task_claims(_plan(
        tasks=[{"id": "T1", "claimed_paths": ["src/task.py"]}],
        state={"running_tasks": [{"task_id": "T1", "claimed_paths": []}]},
    ))

    invalid = _issues_by_code(issues, "E_STATE_RUNNING_TASK_INVALID_CLAIMS")
    assert len(invalid) == 1
    assert invalid[0].evidence == {"task_id": "T1", "reason": "empty"}


def test_running_task_rejects_out_of_declared_paths() -> None:
    issues = _check_running_task_claims(_plan(
        tasks=[{"id": "T1", "claimed_paths": ["src/pkg"]}],
        state={
            "running_tasks": [{"task_id": "T1", "claimed_paths": ["src/other.py"]}],
        },
    ))

    invalid = _issues_by_code(issues, "E_STATE_RUNNING_TASK_INVALID_CLAIMS")
    assert len(invalid) == 1
    assert invalid[0].evidence["reason"] == "out_of_declared"
    assert invalid[0].evidence["offending_paths"] == ["src/other.py"]


def test_running_task_claim_subset_is_allowed() -> None:
    issues = _check_running_task_claims(_plan(
        tasks=[{"id": "T1", "claimed_paths": ["src/pkg"]}],
        state={
            "running_tasks": [{"task_id": "T1", "claimed_paths": ["src/pkg/file.py"]}],
        },
    ))

    assert _issues_by_code(issues, "E_STATE_RUNNING_TASK_INVALID_CLAIMS") == []


def test_unknown_running_task_is_ignored_by_claim_validation() -> None:
    issues = _check_running_task_claims(_plan(
        tasks=[{"id": "T1", "claimed_paths": ["src/task.py"]}],
        state={
            "running_tasks": [{"task_id": "ghost", "claimed_paths": ["src/task.py"]}],
        },
    ))

    assert _issues_by_code(issues, "E_STATE_RUNNING_TASK_INVALID_CLAIMS") == []
