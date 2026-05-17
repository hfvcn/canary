from __future__ import annotations

import datetime as dt

from cccc.ralph.models import (
    Plan,
    SuppressInstance,
    TaskRole,
    TaskSpec,
    Verification,
    VerificationCovers,
    VerificationLevel,
)
from cccc.ralph.validator import validate


LEASE_DAYS = 30


def _future_date() -> str:
    return (dt.date.today() + dt.timedelta(days=LEASE_DAYS)).isoformat()


def _task(
    task_id: str,
    *,
    role: TaskRole = "leaf",
    claimed_paths: list[str] | None = None,
    depends_on: list[str] | None = None,
    verification_level: VerificationLevel = "unit",
    covers: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=f"Task {task_id}",
        role=role,
        depends_on=depends_on or [],
        claimed_paths=claimed_paths or [f"src/{task_id.lower()}.py"],
        acceptance_criteria="done",
        verification=Verification(
            level=verification_level,
            command="true",
            covers=VerificationCovers(tasks=covers or [task_id]),
        ),
    )


def _issues(report, code: str):
    return [
        issue
        for issue in [*report.errors, *report.warnings, *report.hints]
        if issue.code == code
    ]


def test_two_leaf_tasks_claim_same_file_emit_write_conflict_error() -> None:
    plan = Plan(tasks=[
        _task("T1", claimed_paths=["src/shared.py"]),
        _task("T2", claimed_paths=["src/shared.py"]),
    ])

    report = validate(plan)

    conflicts = _issues(report, "E_WRITE_CONFLICT")
    assert len(conflicts) == 1
    assert conflicts[0].severity == "error"
    assert conflicts[0].task_ids == ["T1", "T2"]
    assert conflicts[0].evidence["shared_paths"] == ["src/shared.py"]
    assert _issues(report, "W_SHARED_PATH_NO_DEPENDENCY") == []


def test_leaf_directory_overlap_stays_shared_path_warning() -> None:
    plan = Plan(tasks=[
        _task("T1", claimed_paths=["src/app/"]),
        _task("T2", claimed_paths=["src/app/routes.py"]),
    ])

    report = validate(plan)

    warnings = _issues(report, "W_SHARED_PATH_NO_DEPENDENCY")
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert _issues(report, "E_WRITE_CONFLICT") == []


def test_integration_task_overlap_emits_no_write_conflict_error() -> None:
    plan = Plan(tasks=[
        _task("T1", claimed_paths=["src/shared.py"]),
        _task(
            "T2",
            role="integration",
            claimed_paths=["src/shared.py", "src/other.py"],
            verification_level="integration",
        ),
    ])

    report = validate(plan)

    assert _issues(report, "E_WRITE_CONFLICT") == []
    assert _issues(report, "W_SHARED_PATH_NO_DEPENDENCY") == []


def test_suppress_instance_for_write_conflict_downgrades_error() -> None:
    plan = Plan(
        tasks=[
            _task("T1", claimed_paths=["src/shared.py"]),
            _task("T2", claimed_paths=["src/shared.py"]),
            _task(
                "T3",
                role="integration",
                claimed_paths=["tests/test_flow.py"],
                depends_on=["T1", "T2"],
                verification_level="integration",
                covers=["T1", "T2"],
            ),
        ],
        suppress_instances=[
            SuppressInstance(
                code="E_WRITE_CONFLICT",
                owner="owner@example.com",
                expiry=_future_date(),
                review_after=_future_date(),
            ),
        ],
    )

    report = validate(plan)

    conflicts = _issues(report, "E_WRITE_CONFLICT")
    assert report.valid
    assert len(conflicts) == 1
    assert conflicts[0].severity == "hint"
    assert conflicts[0].message.startswith("[suppressed]")
