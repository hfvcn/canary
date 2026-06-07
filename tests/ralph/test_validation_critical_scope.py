from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.coverage import _check_critical_declaration_outside_scope


def _plan(*, plan_scope: list[str], critical_flows: list[dict], critical_entrypoints: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "plan_scope": plan_scope,
        "critical_entrypoints": critical_entrypoints or [],
        "critical_flows": critical_flows,
    })


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_flow_declared_entirely_outside_scope_warns() -> None:
    issues = _check_critical_declaration_outside_scope(_plan(
        plan_scope=["src/in_scope"],
        critical_flows=[{"id": "login", "entrypoints": ["src/outside/login.py"]}],
    ))

    warning = _issues_by_code(issues, "W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE")
    assert len(warning) == 1
    assert warning[0].evidence["flow_id"] == "login"


def test_flow_with_at_least_one_in_scope_entrypoint_is_silent() -> None:
    issues = _check_critical_declaration_outside_scope(_plan(
        plan_scope=["src/in_scope"],
        critical_flows=[{
            "id": "login",
            "entrypoints": ["src/outside/login.py", "src/in_scope/login.py"],
        }],
    ))

    assert _issues_by_code(issues, "W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE") == []


def test_top_level_critical_entrypoints_outside_scope_warn() -> None:
    issues = _check_critical_declaration_outside_scope(_plan(
        plan_scope=["src/in_scope"],
        critical_flows=[],
        critical_entrypoints=["src/outside/auth.py"],
    ))

    warning = _issues_by_code(issues, "W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE")
    assert len(warning) == 1
    assert warning[0].evidence["scope"] == "critical_entrypoints"


def test_empty_plan_scope_disables_rule() -> None:
    issues = _check_critical_declaration_outside_scope(_plan(
        plan_scope=[],
        critical_flows=[{"id": "login", "entrypoints": ["src/outside/login.py"]}],
        critical_entrypoints=["src/outside/auth.py"],
    ))

    assert _issues_by_code(issues, "W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE") == []


def test_flow_without_entrypoints_is_ignored() -> None:
    issues = _check_critical_declaration_outside_scope(_plan(
        plan_scope=["src/in_scope"],
        critical_flows=[{"id": "login", "entrypoints": []}],
    ))

    assert _issues_by_code(issues, "W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE") == []
