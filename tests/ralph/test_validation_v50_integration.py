from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import get_all_rules
from cccc.ralph.validation_rules.contracts import _check_consumer_from_provides
from cccc.ralph.validation_rules.coverage import (
    _check_critical_declaration_outside_scope,
    _check_full_regression_override_risk,
    _check_running_task_claims,
    _check_state_task_status_conflict,
)
from cccc.ralph.validation_rules.security import (
    _check_identity_surface_privilege,
    _check_rbac_write_endpoint_coverage,
    _check_reviewer_signoff,
)
from cccc.ralph.validation_rules.structural import _check_module_dep_cycle
from cccc.ralph.validator import validate


DIRTY_CODES = {
    "E_STATE_TASK_STATUS_CONFLICT",
    "E_STATE_RUNNING_TASK_INVALID_CLAIMS",
    "W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE",
    "E_CONSUMER_FROM_NOT_PROVIDER",
    "E_MODULE_DEP_CYCLE",
    "W_RBAC_WRITE_ENDPOINT_UNCOVERED",
    "W_AUTH_PRIVILEGED_ROLE_FIELD",
    "W_FULL_REGRESSION_OVERRIDE_RISK",
    "W_REVIEWER_SIGNOFF_MISSING",
}


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _task(
    task_id: str,
    *,
    claimed_paths: list[str] | None = None,
    command: str = "python -m pytest tests/unit/test_default.py -q",
    checks: list[str] | None = None,
    covers_flows: list[str] | None = None,
    verification_mode: str = "ralph",
    depends_on: list[str] | None = None,
    provides: list[dict] | None = None,
    consumes: list[dict] | None = None,
    modules: list[dict] | None = None,
) -> dict:
    check_commands = checks or [command]
    return {
        "id": task_id,
        "claimed_paths": claimed_paths or [f"src/{task_id.lower()}.py"],
        "depends_on": depends_on or [],
        "verification_mode": verification_mode,
        "provides": provides or [],
        "consumes": consumes or [],
        "modules": modules,
        "verification": {
            "level": "unit",
            "command": command,
            "checks": [
                {"name": f"check-{index}", "command": check}
                for index, check in enumerate(check_commands, start=1)
            ],
            "covers": {"flows": covers_flows or [], "tasks": [task_id]},
        },
    }


def _dirty_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            _task("STATE", claimed_paths=["src/state.py"]),
            _task("PROVIDER", provides=[{"name": "artifact-a"}]),
            _task(
                "CONSUMER",
                depends_on=["PROVIDER"],
                consumes=[{"name": "artifact-b", "from": "PROVIDER"}],
            ),
            _task(
                "MODULE",
                modules=[
                    {"id": "A", "internal_depends_on": ["B"]},
                    {"id": "B", "internal_depends_on": ["A"]},
                ],
            ),
            _task(
                "SECURITY",
                claimed_paths=["src/auth/admin.py", "src/auth/register.py"],
                command="python -m pytest tests/auth/test_register_auth.py -q",
                checks=["python -m pytest tests/auth/test_register_auth.py -q"],
                covers_flows=["rbac_write", "register_flow"],
                verification_mode="agent",
            ),
            _task("FULL", command="python -m pytest -q"),
            _task(
                "OVERRIDE",
                checks=["python -m pytest tests/unit/test_api.py -q --deselect tests/unit/test_skip.py"],
            ),
        ],
        "state": {
            "completed_task_ids": ["STATE"],
            "failed_task_ids": ["STATE"],
            "running_tasks": [{"task_id": "STATE", "claimed_paths": []}],
        },
        "plan_scope": ["src/auth"],
        "critical_entrypoints": ["src/outside/top.py"],
        "critical_flows": [
            {"id": "scope_outside", "entrypoints": ["src/outside/flow.py"]},
            {
                "id": "rbac_write",
                "surface_type": "rbac_write",
                "entrypoints": ["src/auth/admin.py"],
                "required_verification_level": "unit",
            },
            {
                "id": "register_flow",
                "surface_type": "identity_register",
                "entrypoints": ["src/auth/register.py"],
                "required_verification_level": "unit",
            },
        ],
    })


def _clean_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            _task("PROVIDER", provides=[{"name": "artifact-a"}]),
            _task(
                "CONSUMER",
                depends_on=["PROVIDER"],
                consumes=[{"name": "artifact-a", "from": "PROVIDER"}],
            ),
            _task(
                "MODULE",
                modules=[
                    {"id": "A", "internal_depends_on": ["B"]},
                    {"id": "B", "internal_depends_on": []},
                ],
            ),
            _task(
                "SECURITY",
                claimed_paths=["src/auth/admin.py", "src/auth/register.py", "docs/security-review.md"],
                command="python -m pytest tests/auth/test_rbac_403_role_privilege.py -q",
                checks=["python -m pytest tests/auth/test_rbac_403_role_privilege.py -q"],
                covers_flows=["rbac_write", "register_flow"],
                verification_mode="agent",
            ),
        ],
        "critical_flows": [
            {
                "id": "rbac_write",
                "surface_type": "rbac_write",
                "entrypoints": ["src/auth/admin.py"],
                "required_verification_level": "unit",
            },
            {
                "id": "register_flow",
                "surface_type": "identity_register",
                "entrypoints": ["src/auth/register.py"],
                "required_verification_level": "unit",
            },
        ],
    })


def test_validate_reports_all_new_v50_codes_on_dirty_plan() -> None:
    report = validate(_dirty_plan())

    assert DIRTY_CODES <= _issue_codes(report)


def test_validate_reports_creator_failed_and_deferred_visibility() -> None:
    failed_report = validate(Plan.model_validate({
        "tasks": [{"id": "create-tests"}],
        "state": {"failed_task_ids": ["create-tests"]},
        "critical_flows": [{"id": "login_flow", "test_created_by": ["create-tests"]}],
    }))
    deferred_report = validate(Plan.model_validate({
        "tasks": [{"id": "create-tests"}],
        "critical_flows": [{"id": "login_flow", "test_created_by": ["create-tests"]}],
    }))

    assert "E_FLOW_TEST_CREATOR_FAILED" in _issue_codes(failed_report)
    assert "W_FLOW_COVERAGE_DEFERRED" in _issue_codes(deferred_report)


def test_validate_keeps_security_warning_out_of_suppressed_hints() -> None:
    report = validate(Plan.model_validate({
        "suppress_codes": ["W_REVIEWER_SIGNOFF_MISSING"],
        "tasks": [_task(
            "SECURITY",
            claimed_paths=["src/auth/admin.py"],
            command="python -m pytest tests/auth/test_rbac_403_role.py -q",
            checks=["python -m pytest tests/auth/test_rbac_403_role.py -q"],
            covers_flows=["rbac_write"],
            verification_mode="agent",
        )],
        "critical_flows": [{
            "id": "rbac_write",
            "surface_type": "rbac_write",
            "entrypoints": ["src/auth/admin.py"],
            "required_verification_level": "unit",
        }],
    }))

    assert "W_REVIEWER_SIGNOFF_MISSING" in [issue.code for issue in report.warnings]
    assert "W_REVIEWER_SIGNOFF_MISSING" not in [issue.code for issue in report.hints]


def test_validate_omits_all_new_v50_codes_on_clean_plan() -> None:
    report = validate(_clean_plan())

    assert _issue_codes(report).isdisjoint(DIRTY_CODES | {"E_FLOW_TEST_CREATOR_FAILED", "W_FLOW_COVERAGE_DEFERRED"})


def test_get_all_rules_lists_v50_rule_functions() -> None:
    rules = get_all_rules()

    assert _check_state_task_status_conflict in rules
    assert _check_running_task_claims in rules
    assert _check_critical_declaration_outside_scope in rules
    assert _check_consumer_from_provides in rules
    assert _check_module_dep_cycle in rules
    assert _check_rbac_write_endpoint_coverage in rules
    assert _check_identity_surface_privilege in rules
    assert _check_full_regression_override_risk in rules
    assert _check_reviewer_signoff in rules
