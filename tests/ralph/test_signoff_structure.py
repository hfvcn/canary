from __future__ import annotations

from cccc.ralph.models import Plan, ValidationIssue, ValidationReport
from cccc.ralph.validation_rules import get_all_rules
from cccc.ralph.validation_rules.security import _check_signoff_structure
from cccc.ralph.validator import validate


CODE = "W_SIGNOFF_STRUCTURE_WEAK"
SECURITY_FLOW_ID = "admin_rbac_write"
CHECKOUT_FLOW_ID = "checkout_flow"
SECURITY_ENTRYPOINT = "src/admin.py"
CHECKOUT_ENTRYPOINT = "src/checkout.py"
SIGNOFF_PATH = "docs/security-review.md"
AUTHZ_CHECK = {
    "name": "authz-negative",
    "command": "python -m pytest tests/auth/test_admin_403_role.py -q",
}
WEAK_SIGNOFF_CHECK = {
    "name": "signoff-approved",
    "command": "grep -qiE 'approved' docs/security-review.md",
}
STRUCTURED_SIGNOFF_CHECK = {
    "name": "sign-off-schema",
    "command": (
        "python scripts/verify_signoff.py --field reviewer "
        "--field commit docs/security-review.md"
    ),
}


def _security_flow() -> dict:
    return {
        "id": SECURITY_FLOW_ID,
        "surface_type": "rbac_write",
        "entrypoints": [SECURITY_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _checkout_flow() -> dict:
    return {
        "id": CHECKOUT_FLOW_ID,
        "entrypoints": [CHECKOUT_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _review_task(
    *,
    flow_id: str = SECURITY_FLOW_ID,
    claimed_paths: list[str] | None = None,
    checks: list[dict[str, str]] | None = None,
    verification_command: str = "",
) -> dict:
    return {
        "id": "review",
        "claimed_paths": claimed_paths or [SECURITY_ENTRYPOINT, SIGNOFF_PATH],
        "verification_mode": "agent",
        "verification": {
            "level": "unit",
            "command": verification_command,
            "checks": checks or [AUTHZ_CHECK],
            "covers": {"flows": [flow_id]},
        },
    }


def _plan(*, flow: dict | None = None, task: dict | None = None) -> Plan:
    return Plan.model_validate({
        "tasks": [task or _review_task()],
        "critical_flows": [flow or _security_flow()],
    })


def _rule_issues(plan: Plan) -> list[ValidationIssue]:
    return [issue for issue in _check_signoff_structure(plan) if issue.code == CODE]


def _warning_issues(report: ValidationReport) -> list[ValidationIssue]:
    return [issue for issue in report.warnings if issue.code == CODE]


def test_simple_grep_signoff_check_warns_through_validate_entrypoint() -> None:
    report = validate(_plan(task=_review_task(checks=[WEAK_SIGNOFF_CHECK])))

    issues = _warning_issues(report)

    assert len(issues) == 1
    assert issues[0].evidence["reason"] == "weak-check"


def test_signoff_check_with_reviewer_and_commit_is_structured() -> None:
    task = _review_task(
        claimed_paths=[SECURITY_ENTRYPOINT, SIGNOFF_PATH],
        checks=[STRUCTURED_SIGNOFF_CHECK],
    )

    issues = _rule_issues(_plan(task=task))

    assert issues == []


def test_structured_check_without_path_reference_warns() -> None:
    check = {
        "name": "sign-off-schema",
        "command": (
            "python verify.py --field reviewer --field commit "
            "--input data.json"
        ),
    }

    issues = _rule_issues(_plan(task=_review_task(checks=[check])))

    assert len(issues) == 1
    assert issues[0].evidence["reason"] == "signoff-check-no-path-reference"
    assert issues[0].evidence["check_names"] == ["sign-off-schema"]


def test_structured_check_with_path_reference_passes() -> None:
    check = {
        "name": "sign-off-schema",
        "command": (
            "python scripts/verify_signoff.py docs/security-review.json "
            "--field reviewer --field commit"
        ),
    }
    task = _review_task(
        claimed_paths=[SECURITY_ENTRYPOINT, "docs/security-review.json"],
        checks=[check],
    )

    assert _rule_issues(_plan(task=task)) == []


def test_structured_check_with_basename_reference_passes() -> None:
    check = {
        "name": "sign-off-schema",
        "command": (
            "python scripts/verify_signoff.py security-review.json "
            "--field reviewer --field commit"
        ),
    }
    task = _review_task(
        claimed_paths=[SECURITY_ENTRYPOINT, "docs/security-review.json"],
        checks=[check],
    )

    assert _rule_issues(_plan(task=task)) == []


def test_grep_with_structured_tokens_still_weak() -> None:
    check = {
        "name": "sign-off-check",
        "command": "grep -E reviewer.*commit docs/security-review.md",
    }

    issues = _rule_issues(_plan(task=_review_task(checks=[check])))

    assert len(issues) == 1
    assert issues[0].evidence["reason"] == "weak-check"


def test_verification_command_path_extraction() -> None:
    check = {
        "name": "sign-off-schema",
        "command": (
            "python scripts/verify_signoff.py docs/security-review.md "
            "--field reviewer --field commit"
        ),
    }
    task = _review_task(
        claimed_paths=[SECURITY_ENTRYPOINT],
        checks=[check],
        verification_command="python scripts/read_review.py docs/security-review.md",
    )

    assert _rule_issues(_plan(task=task)) == []


def test_signoff_reference_without_signoff_check_warns() -> None:
    issues = _rule_issues(_plan(task=_review_task(checks=[AUTHZ_CHECK])))

    assert len(issues) == 1
    assert issues[0].evidence["reason"] == "no-signoff-check"


def test_task_without_signoff_reference_is_left_to_missing_signoff_rule() -> None:
    task = _review_task(claimed_paths=[SECURITY_ENTRYPOINT], checks=[AUTHZ_CHECK])

    assert _rule_issues(_plan(task=task)) == []


def test_non_security_critical_flow_does_not_report_signoff_structure() -> None:
    task = _review_task(
        flow_id=CHECKOUT_FLOW_ID,
        claimed_paths=[CHECKOUT_ENTRYPOINT, SIGNOFF_PATH],
        checks=[WEAK_SIGNOFF_CHECK],
    )

    assert _rule_issues(_plan(flow=_checkout_flow(), task=task)) == []


def test_signoff_structure_rule_is_discoverable() -> None:
    assert _check_signoff_structure in get_all_rules()
