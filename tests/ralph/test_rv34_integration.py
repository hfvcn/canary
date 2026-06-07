from __future__ import annotations

from typing import Any

from cccc.ralph.models import Plan, ValidationIssue, ValidationReport
from cccc.ralph.validator import validate


CODE = "W_SIGNOFF_STRUCTURE_WEAK"
AUTH_FLOW_ID = "admin_rbac"
NON_AUTH_FLOW_ID = "checkout"
AUTH_ENTRYPOINT = "src/admin.py"
NON_AUTH_ENTRYPOINT = "src/checkout.py"
SIGNOFF_PATH = "docs/security-review.md"

AUTHZ_CHECK = {
    "name": "authz-negative",
    "command": "python -m pytest tests/auth/test_admin_403_role.py -q",
}
WEAK_SIGNOFF_CHECK = {
    "name": "signoff-approved",
    "command": "grep -qiE approved docs/security-review.md",
}
STRUCTURED_SIGNOFF_CHECK = {
    "name": "signoff-schema",
    "command": "python verify.py --field reviewer --field commit docs/security-review.md",
}


def _auth_flow() -> dict[str, Any]:
    return {
        "id": AUTH_FLOW_ID,
        "surface_type": "rbac_write",
        "entrypoints": [AUTH_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _non_auth_flow() -> dict[str, Any]:
    return {
        "id": NON_AUTH_FLOW_ID,
        "entrypoints": [NON_AUTH_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _review_task(
    *,
    flow_id: str,
    entrypoint: str,
    checks: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "id": "security-review",
        "claimed_paths": [entrypoint, SIGNOFF_PATH],
        "verification_mode": "agent",
        "verification": {
            "level": "unit",
            "checks": checks,
            "covers": {"flows": [flow_id]},
        },
    }


def _plan(
    *,
    flow: dict[str, Any],
    task: dict[str, Any],
    suppress_codes: list[str] | None = None,
) -> Plan:
    return Plan.model_validate({
        "tasks": [task],
        "critical_flows": [flow],
        "suppress_codes": suppress_codes or [],
    })


def _auth_plan(
    *,
    checks: list[dict[str, str]],
    suppress_codes: list[str] | None = None,
) -> Plan:
    return _plan(
        flow=_auth_flow(),
        task=_review_task(
            flow_id=AUTH_FLOW_ID,
            entrypoint=AUTH_ENTRYPOINT,
            checks=checks,
        ),
        suppress_codes=suppress_codes,
    )


def _non_auth_plan(
    *,
    checks: list[dict[str, str]],
    suppress_codes: list[str] | None = None,
) -> Plan:
    return _plan(
        flow=_non_auth_flow(),
        task=_review_task(
            flow_id=NON_AUTH_FLOW_ID,
            entrypoint=NON_AUTH_ENTRYPOINT,
            checks=checks,
        ),
        suppress_codes=suppress_codes,
    )


def _issues_by_code(
    report: ValidationReport,
    bucket: str,
    code: str = CODE,
) -> list[ValidationIssue]:
    return [issue for issue in getattr(report, bucket) if issue.code == code]


def test_no_signoff_check_with_auth_flow_and_suppress_still_warns() -> None:
    report = validate(_auth_plan(checks=[AUTHZ_CHECK], suppress_codes=[CODE]))

    warnings = _issues_by_code(report, "warnings")

    assert len(warnings) == 1
    assert warnings[0].evidence["reason"] == "no-signoff-check"
    assert _issues_by_code(report, "hints") == []


def test_weak_grep_signoff_with_suppress_still_warns() -> None:
    report = validate(
        _auth_plan(
            checks=[AUTHZ_CHECK, WEAK_SIGNOFF_CHECK],
            suppress_codes=[CODE],
        ),
    )

    warnings = _issues_by_code(report, "warnings")

    assert len(warnings) == 1
    assert warnings[0].evidence["reason"] == "weak-check"
    assert _issues_by_code(report, "hints") == []


def test_structured_check_without_path_reference_warns() -> None:
    check = {
        "name": "signoff-schema",
        "command": "python verify.py --field reviewer --field commit",
    }
    report = validate(_auth_plan(checks=[AUTHZ_CHECK, check]))

    warnings = _issues_by_code(report, "warnings")

    assert len(warnings) == 1
    assert warnings[0].evidence["reason"] == "signoff-check-no-path-reference"


def test_structured_check_with_path_reference_has_no_warning() -> None:
    report = validate(_auth_plan(checks=[AUTHZ_CHECK, STRUCTURED_SIGNOFF_CHECK]))

    assert _issues_by_code(report, "warnings") == []
    assert _issues_by_code(report, "hints") == []


def test_non_security_flow_has_no_warning() -> None:
    report = validate(_non_auth_plan(checks=[WEAK_SIGNOFF_CHECK]))

    assert _issues_by_code(report, "warnings") == []
    assert _issues_by_code(report, "hints") == []


def test_non_security_flow_with_suppress_has_no_warning() -> None:
    report = validate(
        _non_auth_plan(
            checks=[WEAK_SIGNOFF_CHECK],
            suppress_codes=[CODE],
        ),
    )

    assert _issues_by_code(report, "warnings") == []
    assert _issues_by_code(report, "hints") == []
