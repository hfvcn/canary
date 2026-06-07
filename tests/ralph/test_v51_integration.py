from __future__ import annotations

from typing import Any

from cccc.ralph.models import Plan, ValidationReport
from cccc.ralph.validation_rules import (
    _check_contract_kind_mismatch,
    _check_security_critical_flow_suppressed,
    _check_signoff_structure,
    _check_task_paths_outside_plan_scope,
    get_all_rules,
)
from cccc.ralph.validator import validate


TASK_PATH_OUTSIDE_SCOPE = "E_TASK_PATH_OUTSIDE_PLAN_SCOPE"
SECURITY_FLOW_SUPPRESSED = "E_SECURITY_CRITICAL_FLOW_SUPPRESSED"
CONTRACT_KIND_MISMATCH = "E_CONTRACT_KIND_MISMATCH"
SIGNOFF_STRUCTURE_WEAK = "W_SIGNOFF_STRUCTURE_WEAK"
WORKER_ONLY_VERIFICATION = "W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION"
ENTRYPOINT_UNOWNED = "E_CRITICAL_ENTRYPOINT_UNOWNED"
FLOW_ENTRYPOINT_UNOWNED = "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED"
NEW_V51_CODES = {
    TASK_PATH_OUTSIDE_SCOPE,
    SECURITY_FLOW_SUPPRESSED,
    CONTRACT_KIND_MISMATCH,
    SIGNOFF_STRUCTURE_WEAK,
}
AUTH_FLOW_ID = "auth_admin_flow"


def _issue_codes(report: ValidationReport) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _bucket_codes(report: ValidationReport, bucket: str) -> list[str]:
    return [issue.code for issue in getattr(report, bucket)]


def _verification(
    *,
    command: str,
    level: str = "unit",
    flows: list[str] | None = None,
    tasks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "level": level,
        "command": command,
        "checks": [{"name": "behavior", "command": command}],
        "covers": {"flows": flows or [], "tasks": tasks or []},
    }


def _task(
    task_id: str,
    *,
    claimed_paths: list[str] | None = None,
    role: str = "leaf",
    verification_mode: str = "ralph",
    verification: dict[str, Any] | None = None,
    provides: list[dict[str, str]] | None = None,
    consumes: list[dict[str, str]] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "role": role,
        "claimed_paths": claimed_paths or [f"src/{task_id.lower()}.py"],
        "goal_behavior": f"{task_id} behavior",
        "acceptance_criteria": f"{task_id} acceptance",
        "verification_mode": verification_mode,
        "depends_on": depends_on or [],
        "provides": provides or [],
        "consumes": consumes or [],
        "verification": verification,
    }


def _auth_flow() -> dict[str, Any]:
    return {
        "id": AUTH_FLOW_ID,
        "description": "RBAC auth admin write path",
        "surface_type": "rbac_write",
        "entrypoints": ["src/auth/admin.py"],
        "required_verification_level": "unit",
    }


def test_validate_reports_multiple_new_v51_codes_on_dirty_plan() -> None:
    report = validate(Plan.model_validate({
        "plan_scope": ["src/auth", "tests/auth"],
        "suppress_flows": [AUTH_FLOW_ID],
        "tasks": [
            _task(
                "SCOPE",
                claimed_paths=["src/auth/login.py", "src/outside.py"],
                verification=_verification(
                    command="python -m pytest tests/auth/test_login.py -q",
                    tasks=["SCOPE"],
                ),
            ),
            _task(
                "PROVIDER",
                claimed_paths=["src/auth/provider.py"],
                provides=[{"name": "session", "kind": "api_endpoint"}],
            ),
            _task(
                "CONSUMER",
                claimed_paths=["src/auth/consumer.py"],
                depends_on=["PROVIDER"],
                consumes=[{"name": "session", "kind": "artifact", "from": "PROVIDER"}],
            ),
        ],
        "critical_flows": [_auth_flow()],
    }))

    assert {
        TASK_PATH_OUTSIDE_SCOPE,
        SECURITY_FLOW_SUPPRESSED,
        CONTRACT_KIND_MISMATCH,
    } <= _issue_codes(report)


def test_security_suppression_remains_ineffective_and_signoff_is_checked() -> None:
    weak_signoff = _verification(
        command="grep -qiE 'approved' docs/SECURITY_REVIEW.md",
        flows=[AUTH_FLOW_ID],
        tasks=["SECURITY_SIGNOFF"],
    )
    weak_signoff["checks"] = [{
        "name": "signoff",
        "command": "grep -qiE 'approved' docs/SECURITY_REVIEW.md",
    }]
    report = validate(Plan.model_validate({
        "suppress_codes": [WORKER_ONLY_VERIFICATION],
        "tasks": [
            _task(
                "SECURITY_SIGNOFF",
                role="verification",
                claimed_paths=["src/auth/admin.py", "docs/SECURITY_REVIEW.md"],
                verification=weak_signoff,
            ),
        ],
        "critical_flows": [_auth_flow()],
    }))

    assert WORKER_ONLY_VERIFICATION in _bucket_codes(report, "warnings")
    assert WORKER_ONLY_VERIFICATION not in _bucket_codes(report, "hints")
    assert SIGNOFF_STRUCTURE_WEAK in _bucket_codes(report, "warnings")


def test_file_function_entrypoint_is_owned_through_validate() -> None:
    report = validate(Plan.model_validate({
        "tasks": [
            _task(
                "APP",
                claimed_paths=["src/app.py"],
                verification=_verification(
                    command="python -m pytest tests/test_app.py -q",
                    level="integration",
                    flows=["app_start"],
                    tasks=["APP"],
                ),
            ),
        ],
        "critical_entrypoints": ["src/app.py::create_app"],
        "critical_flows": [{
            "id": "app_start",
            "entrypoints": ["src/app.py::create_app"],
            "required_verification_level": "integration",
        }],
    }))

    assert ENTRYPOINT_UNOWNED not in _issue_codes(report)
    assert FLOW_ENTRYPOINT_UNOWNED not in _issue_codes(report)


def test_validate_omits_new_v51_codes_on_clean_plan() -> None:
    strong_signoff = _verification(
        command="python tools/verify_signoff.py --require reviewer --require commit",
        flows=[AUTH_FLOW_ID],
        tasks=["SECURITY_SIGNOFF"],
    )
    strong_signoff["checks"] = [{
        "name": "signoff",
        "command": "python tools/verify_signoff.py --require reviewer --require commit",
    }]
    report = validate(Plan.model_validate({
        "plan_scope": ["src/auth", "tests/auth", "docs", "src/contracts"],
        "tasks": [
            _task(
                "AUTH",
                claimed_paths=["src/auth/admin.py"],
                verification_mode="agent",
                verification=_verification(
                    command="python -m pytest tests/auth/test_admin_403_role.py -q",
                    flows=[AUTH_FLOW_ID],
                    tasks=["AUTH"],
                ),
            ),
            _task(
                "PROVIDER",
                claimed_paths=["src/contracts/provider.py"],
                provides=[{"name": "session", "kind": "artifact"}],
            ),
            _task(
                "CONSUMER",
                claimed_paths=["src/contracts/consumer.py"],
                depends_on=["PROVIDER"],
                consumes=[{"name": "session", "kind": "artifact", "from": "PROVIDER"}],
            ),
            _task(
                "SECURITY_SIGNOFF",
                role="verification",
                claimed_paths=["docs/SECURITY_REVIEW.md"],
                verification_mode="agent",
                verification=strong_signoff,
            ),
        ],
        "critical_flows": [_auth_flow()],
    }))

    assert _issue_codes(report).isdisjoint(NEW_V51_CODES)


def test_get_all_rules_lists_v51_rule_functions() -> None:
    rules = get_all_rules()

    assert _check_task_paths_outside_plan_scope in rules
    assert _check_security_critical_flow_suppressed in rules
    assert _check_contract_kind_mismatch in rules
    assert _check_signoff_structure in rules
