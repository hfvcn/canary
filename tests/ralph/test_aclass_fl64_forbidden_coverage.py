from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import (
    CheckSpec,
    ForbiddenFlow,
    Plan,
    TaskSpec,
    ValidationIssue,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate
from cccc.ralph.validation_rules.coverage import (
    W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING,
    W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE,
    _check_forbidden_flow_field_coverage,
)


FLOW_ID = "forbid-admin"
FIELD_NAME = "is_admin"
TEST_PATH = "tests/test_auth.py"


def _plan(command: str, *, top_level_only: bool = False) -> Plan:
    checks = [] if top_level_only else [CheckSpec(name="behavior", command=command)]
    verification_command = command if top_level_only else ""
    task = TaskSpec(
        id="T1",
        claimed_paths=["src/auth.py"],
        acceptance_criteria="forbidden flow field must have negative coverage",
        verification=Verification(
            level="unit",
            command=verification_command,
            checks=checks,
            covers=VerificationCovers(tasks=["T1"], flows=[FLOW_ID]),
        ),
    )
    flow = ForbiddenFlow(
        id=FLOW_ID,
        description="Request payload MUST NOT accept `is_admin`",
        required_verification_level="unit",
    )
    return Plan(tasks=[task], forbidden_flows=[flow])


def _write(project_root: Path, rel_path: str, content: str) -> None:
    target = project_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def test_reports_assertion_missing_when_field_is_mentioned_without_negative_assertion(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        TEST_PATH,
        (
            "def test_is_admin_payload_shape() -> None:\n"
            "    payload = {'is_admin': True}\n"
            "    assert payload['is_admin'] is True\n"
        ),
    )

    issues = _check_forbidden_flow_field_coverage(
        _plan(f"python -m pytest {TEST_PATH} -k is_admin -q"),
        project_root=tmp_path,
    )

    warning = _issues_by_code(issues, W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING)
    assert len(warning) == 1
    assert warning[0].evidence == {
        "flow_id": FLOW_ID,
        "declared_fields": [FIELD_NAME],
        "covering_task_ids": ["T1"],
        "scanned_test_files": [TEST_PATH],
        "assertion_missing_fields": [FIELD_NAME],
    }
    assert _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNTESTED") == []


def test_real_negative_assertion_is_not_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        TEST_PATH,
        (
            "def test_is_admin_rejected() -> None:\n"
            "    payload = {'is_admin': True}\n"
            "    response = client.post('/users', json=payload)\n"
            "    assert response.status_code == 403\n"
        ),
    )

    issues = _check_forbidden_flow_field_coverage(
        _plan(f"python -m pytest {TEST_PATH} -k is_admin -q"),
        project_root=tmp_path,
    )

    assert _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNTESTED") == []
    assert _issues_by_code(issues, W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING) == []


def test_reports_untested_when_test_file_does_not_mention_field(tmp_path: Path) -> None:
    _write(
        tmp_path,
        TEST_PATH,
        "def test_role_boundary() -> None:\n    assert True\n",
    )

    issues = _check_forbidden_flow_field_coverage(
        _plan(f"python -m pytest {TEST_PATH} -k is_admin -q"),
        project_root=tmp_path,
    )

    warning = _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNTESTED")
    assert len(warning) == 1
    assert warning[0].evidence == {
        "flow_id": FLOW_ID,
        "declared_fields": [FIELD_NAME],
        "covering_task_ids": ["T1"],
        "scanned_test_files": [TEST_PATH],
        "untested_fields": [FIELD_NAME],
    }
    assert _issues_by_code(issues, W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING) == []


def test_validate_reports_missing_project_root_as_real_issue() -> None:
    report = validate(_plan(f"python -m pytest {TEST_PATH} -k is_admin -q"))

    warning = _issues_by_code(report.warnings, W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE)
    assert len(warning) == 1
    assert warning[0].evidence == {
        "flow_id": FLOW_ID,
        "declared_fields": [FIELD_NAME],
        "covering_task_ids": ["T1"],
        "candidate_test_files": [TEST_PATH],
        "unverifiable_fields": [FIELD_NAME],
        "reason": "project_root_missing",
    }
    assert _issues_by_code(report.warnings, "W_FORBIDDEN_FLOW_FIELD_UNTESTED") == []
    assert _issues_by_code(report.warnings, W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING) == []


def test_top_level_verification_command_only_is_still_scanned(tmp_path: Path) -> None:
    _write(
        tmp_path,
        TEST_PATH,
        "def test_role_boundary() -> None:\n    assert True\n",
    )

    issues = _check_forbidden_flow_field_coverage(
        _plan(
            f"python -m pytest {TEST_PATH} -k is_admin -q",
            top_level_only=True,
        ),
        project_root=tmp_path,
    )

    warning = _issues_by_code(issues, "W_FORBIDDEN_FLOW_FIELD_UNTESTED")
    assert len(warning) == 1
    assert warning[0].evidence == {
        "flow_id": FLOW_ID,
        "declared_fields": [FIELD_NAME],
        "covering_task_ids": ["T1"],
        "scanned_test_files": [TEST_PATH],
        "untested_fields": [FIELD_NAME],
    }
