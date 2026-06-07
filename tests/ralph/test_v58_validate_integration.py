from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.ralph.models import Plan, ValidationReport
from cccc.ralph.validation_rules import (
    _check_af_verification_gate_bypass,
    _check_agentflow_invariants,
    _check_auth_boundary_type_safety,
    _check_security_reviewer_assignment,
    _check_security_reviewer_assignment_issues,
    _check_state_machine_concurrency_safety,
    _check_state_machine_concurrency_safety_issues,
    get_all_rules,
)
from cccc.ralph.validation_rules.coverage import (
    W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING,
    W_INTEGRATION_IMPORT_ONLY_NO_CALL,
)
from cccc.ralph.validator import validate, validate_with_project


AF_ENGINE_PATH = "src/cccc/agentflow/af_engine.py"
TRACE_PARSER_PATH = "src/cccc/agentflow/trace_parser.py"
GATE_PATH = "src/cccc/daemon/foreman/verification_gate.py"
AUTH_FLOW_ID = "login_flow"
FORBIDDEN_FLOW_ID = "forbid-admin"

PLAN_LEVEL_CODES = {
    "W_SECURITY_REVIEW_NOT_INDEPENDENT",
    "W_AF_VERIFICATION_GATE_BYPASS",
    "W_AF_TRACE_PARSER_SILENT_FAILURE",
    "W_AUTH_TYPE_CAST_UNGUARDED",
    "W_STATE_MACHINE_CONCURRENCY_UNVERIFIED",
}
PROJECT_LEVEL_CODES = {
    W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING,
    W_INTEGRATION_IMPORT_ONLY_NO_CALL,
}


def _issue_codes(report: ValidationReport) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _verification(
    command: str,
    *,
    level: str = "unit",
    flows: list[str] | None = None,
    tasks: list[str] | None = None,
    mock_tests: list[dict[str, object]] | None = None,
    name: str = "behavior",
) -> dict[str, Any]:
    return {
        "level": level,
        "command": command,
        "checks": [{"name": name, "command": command}],
        "covers": {"flows": flows or [], "tasks": tasks or []},
        "mock_tests": mock_tests or [],
    }


def _task(
    task_id: str,
    *,
    claimed_paths: list[str] | None = None,
    title: str = "",
    goal_behavior: str = "",
    acceptance_criteria: str = "",
    role: str = "leaf",
    verification_mode: str = "ralph",
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "title": title,
        "role": role,
        "verification_mode": verification_mode,
        "claimed_paths": claimed_paths or [],
        "goal_behavior": goal_behavior,
        "acceptance_criteria": acceptance_criteria,
        "verification": verification,
    }


def _auth_flow() -> dict[str, Any]:
    return {
        "id": AUTH_FLOW_ID,
        "surface_type": "auth_token",
        "entrypoints": ["src/auth.py"],
        "required_verification_level": "unit",
    }


def _forbidden_flow() -> dict[str, Any]:
    return {
        "id": FORBIDDEN_FLOW_ID,
        "description": "Request payload MUST NOT accept `is_admin`",
        "entrypoints": [],
        "required_verification_level": "unit",
    }


def _dirty_plan_level_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            _task(
                "IMPL",
                claimed_paths=["src/service.py"],
                goal_behavior="update service behavior",
                acceptance_criteria="service remains stable",
                verification=_verification(
                    "python -m pytest tests/unit/test_service.py -q",
                    tasks=["IMPL"],
                ),
            ),
            _task(
                "SEC_REVIEW",
                claimed_paths=["docs/security-review.md"],
                title="security review",
                goal_behavior="perform security review for auth changes",
                acceptance_criteria="review remains auditable",
                verification=_verification(
                    "python -m pytest tests/unit/test_review.py -q",
                    tasks=["SEC_REVIEW"],
                ),
            ),
            _task(
                "AF_TRACE",
                claimed_paths=[AF_ENGINE_PATH, TRACE_PARSER_PATH],
                goal_behavior="refine trace parser output",
                acceptance_criteria="AF trace handling remains observable",
                verification=_verification(
                    "python -m py_compile src/cccc/agentflow/trace_parser.py",
                    tasks=["AF_TRACE"],
                    name="compile",
                ),
            ),
            _task(
                "AUTH",
                claimed_paths=["src/auth.py"],
                acceptance_criteria="boundary malformed invalid type token is exercised",
                verification=_verification(
                    "python -m pytest tests/auth/test_login.py -q",
                    flows=[AUTH_FLOW_ID],
                    tasks=["AUTH"],
                ),
            ),
            _task(
                "STATE",
                claimed_paths=["src/workflow.py"],
                goal_behavior="claim state transition after workflow approval",
                acceptance_criteria="state transition completes successfully",
                verification=_verification(
                    "python -m pytest tests/unit/test_status.py -q",
                    tasks=["STATE"],
                    name="unit-check",
                ),
            ),
        ],
        "critical_flows": [_auth_flow()],
    })


def _clean_plan_level_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            _task(
                "IMPL",
                claimed_paths=["src/service.py"],
                goal_behavior="update service behavior",
                acceptance_criteria="service remains stable",
                verification=_verification(
                    "python -m pytest tests/unit/test_service.py -q",
                    tasks=["IMPL"],
                ),
            ),
            _task(
                "SEC_REVIEW",
                claimed_paths=["docs/security-review.md"],
                title="security review",
                goal_behavior="perform security review for auth changes",
                acceptance_criteria="review remains auditable",
                role="verification",
                verification=_verification(
                    "python -m pytest tests/unit/test_review.py -q",
                    tasks=["SEC_REVIEW"],
                ),
            ),
            _task(
                "AF_TRACE",
                claimed_paths=[AF_ENGINE_PATH, TRACE_PARSER_PATH, GATE_PATH],
                goal_behavior="emit error event on parser exception failure",
                acceptance_criteria="AF trace handling remains observable",
                verification=_verification(
                    "python -m py_compile src/cccc/agentflow/trace_parser.py",
                    tasks=["AF_TRACE"],
                    name="compile",
                ),
            ),
            _task(
                "AUTH",
                claimed_paths=["src/auth.py"],
                acceptance_criteria="auth verification stays covered",
                verification_mode="agent",
                verification=_verification(
                    "python -m pytest tests/auth/test_login_401_assert.py -q",
                    flows=[AUTH_FLOW_ID],
                    tasks=["AUTH"],
                    mock_tests=[{
                        "name": "malformed-token",
                        "description": "boundary malformed non-integer token raises TypeError",
                        "verify_command": "python -m pytest tests/auth/test_login_boundary.py -q",
                    }],
                ),
            ),
            _task(
                "STATE",
                claimed_paths=["src/workflow.py"],
                goal_behavior="claim state transition after workflow approval",
                acceptance_criteria="state transition completes successfully",
                verification=_verification(
                    "python -m pytest tests/unit/test_status.py -q",
                    tasks=["STATE"],
                    name="race-check",
                ),
            ),
        ],
        "critical_flows": [_auth_flow()],
    })


def _dirty_project_plan() -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src", "tests"],
        "tasks": [
            _task(
                "INTEGRATION",
                claimed_paths=["src/integration_mod.py"],
                role="integration",
                goal_behavior="wire integration module into production",
                acceptance_criteria="integration remains exercised",
                verification=_verification(
                    "python -m pytest tests/test_integration.py -q",
                    level="integration",
                    tasks=["INTEGRATION"],
                ),
            ),
            _task(
                "FORBID",
                claimed_paths=["src/auth.py"],
                goal_behavior="reject admin escalation",
                acceptance_criteria="request payload must not accept is_admin",
                verification=_verification(
                    "pytest tests/test_auth.py -k is_admin -q",
                    flows=[FORBIDDEN_FLOW_ID],
                    tasks=["FORBID"],
                ),
            ),
        ],
        "forbidden_flows": [_forbidden_flow()],
    })


def _clean_project_plan() -> Plan:
    return Plan.model_validate({
        "plan_scope": ["src", "tests"],
        "tasks": [
            _task(
                "INTEGRATION",
                claimed_paths=["src/integration_mod.py"],
                role="integration",
                goal_behavior="wire integration module into production",
                acceptance_criteria="integration remains exercised",
                verification=_verification(
                    "python -m pytest tests/test_integration.py -q",
                    level="integration",
                    tasks=["INTEGRATION"],
                ),
            ),
            _task(
                "FORBID",
                claimed_paths=["src/auth.py"],
                goal_behavior="reject admin escalation",
                acceptance_criteria="request payload must not accept is_admin",
                verification=_verification(
                    "pytest tests/test_auth.py -k is_admin -q",
                    flows=[FORBIDDEN_FLOW_ID],
                    tasks=["FORBID"],
                ),
            ),
        ],
        "forbidden_flows": [_forbidden_flow()],
    })


def _materialize_dirty_project(tmp_path: Path) -> Plan:
    _write(tmp_path / "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path / "src/main.py", "import integration_mod\n")
    _write(tmp_path / "src/auth.py", "def reject_admin(payload: dict[str, object]) -> bool:\n    return bool(payload)\n")
    _write(tmp_path / "tests/test_integration.py", "def test_integration() -> None:\n    assert True\n")
    _write(
        tmp_path / "tests/test_auth.py",
        (
            "def test_is_admin_payload_shape() -> None:\n"
            "    payload = {'is_admin': True}\n"
            "    assert payload['is_admin'] is True\n"
        ),
    )
    return _dirty_project_plan()


def _materialize_clean_project(tmp_path: Path) -> Plan:
    _write(tmp_path / "src/integration_mod.py", "def install() -> None:\n    pass\n")
    _write(tmp_path / "src/main.py", "from integration_mod import install\ninstall()\n")
    _write(tmp_path / "src/auth.py", "def reject_admin(payload: dict[str, object]) -> bool:\n    return bool(payload)\n")
    _write(tmp_path / "tests/test_integration.py", "def test_integration() -> None:\n    assert True\n")
    _write(
        tmp_path / "tests/test_auth.py",
        (
            "def test_is_admin_rejected() -> None:\n"
            "    payload = {'is_admin': True}\n"
            "    response = client.post('/users', json=payload)\n"
            "    assert response.status_code == 403\n"
        ),
    )
    return _clean_project_plan()


def test_validate_triggers_plan_level_v58_rules() -> None:
    report = validate(_dirty_plan_level_plan())

    assert PLAN_LEVEL_CODES <= _issue_codes(report)


def test_validate_omits_plan_level_v58_rules_on_clean_plan() -> None:
    report = validate(_clean_plan_level_plan())

    assert _issue_codes(report).isdisjoint(PLAN_LEVEL_CODES)


def test_v58_rule_exports_and_registrations_are_wired() -> None:
    rules = set(get_all_rules())

    assert callable(_check_security_reviewer_assignment)
    assert callable(_check_state_machine_concurrency_safety)
    assert _check_security_reviewer_assignment_issues in rules
    assert _check_af_verification_gate_bypass in rules
    assert _check_agentflow_invariants in rules
    assert _check_auth_boundary_type_safety in rules
    assert _check_state_machine_concurrency_safety_issues in rules


def test_validate_with_project_triggers_project_level_v58_rules(tmp_path: Path) -> None:
    plan = _materialize_dirty_project(tmp_path)

    assert _issue_codes(validate(plan)).isdisjoint(PROJECT_LEVEL_CODES)
    assert PROJECT_LEVEL_CODES <= _issue_codes(
        validate_with_project(plan, project_root=tmp_path),
    )


def test_validate_with_project_omits_project_level_v58_rules_on_clean_plan(tmp_path: Path) -> None:
    report = validate_with_project(
        _materialize_clean_project(tmp_path),
        project_root=tmp_path,
    )

    assert _issue_codes(report).isdisjoint(PROJECT_LEVEL_CODES)
