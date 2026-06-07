from __future__ import annotations

from cccc.ralph.models import CheckSpec, Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    checks: list[str],
) -> TaskSpec:
    check_specs = [
        CheckSpec(name=f"check-{index}", command=command)
        for index, command in enumerate(checks, start=1)
    ]
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths,
        acceptance_criteria="claimed tests are exercised",
        verification=Verification(
            level="unit",
            command=check_specs[0].command if check_specs else "",
            checks=check_specs,
            covers=VerificationCovers(tasks=[task_id]),
        ),
    )


def test_claimed_test_without_matching_check_warns() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["tests/foo_test.py"],
                checks=["python -m pytest tests/bar_test.py -q"],
            )
        ]
    )

    report = validate(plan)
    issues = _issues_by_code(report, "W_CLAIMED_TEST_NOT_EXERCISED")

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {"claimed_test_path": "tests/foo_test.py"}


def test_claimed_test_with_direct_basename_match_is_silent() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["tests/unit/test_login.py"],
                checks=["pytest test_login.py -q"],
            )
        ]
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_CLAIMED_TEST_NOT_EXERCISED") == []


def test_claimed_test_with_directory_prefix_is_silent() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["tests/ralph/test_login.py"],
                checks=["pytest tests/ralph -q"],
            )
        ]
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_CLAIMED_TEST_NOT_EXERCISED") == []


def test_bare_pytest_suite_covers_test_tree_claims() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["tests/smoke/auth_case.py"],
                checks=["python -m pytest -q"],
            )
        ]
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_CLAIMED_TEST_NOT_EXERCISED") == []


def test_non_test_claims_do_not_warn() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                claimed_paths=["src/service.py"],
                checks=["python -m pytest tests/service_test.py -q"],
            )
        ]
    )

    report = validate(plan)

    assert _issues_by_code(report, "W_CLAIMED_TEST_NOT_EXERCISED") == []
