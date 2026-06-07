from __future__ import annotations

from cccc.ralph.models import (
    ForbiddenFlow,
    Plan,
    TaskSpec,
    ValidationIssue,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate
from cccc.ralph.validation_rules.coverage import _check_forbidden_flow_field_coverage


def _task(task_id: str, *, flow_id: str, command: str) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=["src/auth.py"],
        acceptance_criteria="forbidden flow field is covered by verification",
        verification=Verification(
            level="unit",
            command=command,
            covers=VerificationCovers(tasks=[task_id], flows=[flow_id]),
        ),
    )


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_forbidden_flow_field_covered_by_verification_text_emits_no_warning() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                flow_id="forbid-admin",
                command="pytest tests/test_auth.py -q -k is_admin",
            )
        ],
        forbidden_flows=[
            ForbiddenFlow(
                id="forbid-admin",
                description="Request payload MUST NOT accept `is_admin`",
            )
        ],
    )

    issues = _check_forbidden_flow_field_coverage(plan)

    assert _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNCOVERED") == []


def test_forbidden_flow_field_missing_from_covering_task_emits_warning() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                flow_id="forbid-admin",
                command="pytest tests/test_auth.py -q -k role_boundary",
            )
        ],
        forbidden_flows=[
            ForbiddenFlow(
                id="forbid-admin",
                description="Request payload MUST NOT accept `is_admin`",
            )
        ],
    )

    issues = _check_forbidden_flow_field_coverage(plan)

    warning = _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNCOVERED")
    assert len(warning) == 1
    assert warning[0].task_ids == ["T1"]
    assert warning[0].evidence == {
        "flow_id": "forbid-admin",
        "declared_fields": ["is_admin"],
        "covering_task_ids": ["T1"],
        "uncovered_fields": ["is_admin"],
    }


def test_forbidden_flow_without_declared_fields_emits_no_issue() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                flow_id="forbid-admin",
                command="pytest tests/test_auth.py -q -k role_boundary",
            )
        ],
        forbidden_flows=[
            ForbiddenFlow(
                id="forbid-admin",
                description="Must not bypass authorization middleware.",
            )
        ],
    )

    issues = _check_forbidden_flow_field_coverage(plan)

    assert issues == []


def test_uncovered_forbidden_flow_does_not_emit_field_warning() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                flow_id="other-flow",
                command="pytest tests/test_auth.py -q -k is_admin",
            )
        ],
        forbidden_flows=[
            ForbiddenFlow(
                id="forbid-admin",
                description="Request payload MUST NOT accept `is_admin`",
            )
        ],
    )

    issues = _check_forbidden_flow_field_coverage(plan)

    assert issues == []


def test_validate_surfaces_forbidden_flow_field_warning() -> None:
    plan = Plan(
        tasks=[
            _task(
                "T1",
                flow_id="forbid-admin",
                command="pytest tests/test_auth.py -q -k role_boundary",
            )
        ],
        forbidden_flows=[
            ForbiddenFlow(
                id="forbid-admin",
                description="Request payload MUST NOT accept `is_admin`",
            )
        ],
    )

    warning = _issues_by_code(
        validate(plan).warnings,
        "W_FORBIDDEN_FLOW_FIELD_UNCOVERED",
    )

    assert len(warning) == 1
    assert warning[0].task_ids == ["T1"]
