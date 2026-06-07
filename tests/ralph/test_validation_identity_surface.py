from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.security import _check_identity_surface_privilege


def _task(task_id: str, *, claimed_paths: list[str], checks: list[str], covers_flows: list[str]) -> dict:
    return {
        "id": task_id,
        "claimed_paths": claimed_paths,
        "verification": {
            "level": "unit",
            "command": checks[0],
            "checks": [
                {"name": f"check-{index}", "command": command}
                for index, command in enumerate(checks, start=1)
            ],
            "covers": {"flows": covers_flows},
        },
    }


def _flow(flow_id: str, *, surface_type: str | None = None, description: str = "", entrypoints: list[str] | None = None) -> dict:
    return {
        "id": flow_id,
        "description": description,
        "surface_type": surface_type,
        "entrypoints": entrypoints or ["src/auth.py"],
        "required_verification_level": "unit",
    }


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_identity_surface_without_privileged_role_negative_warns() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/register.py"],
                checks=["python -m pytest tests/auth/test_register_auth.py -q"],
                covers_flows=["register_flow"],
            ),
        ],
        "critical_flows": [
            _flow("rbac_admin_write", surface_type="rbac_write", entrypoints=["src/admin.py"]),
            _flow("register_flow", surface_type="identity_register", entrypoints=["src/register.py"]),
        ],
    })

    warning = _issues_by_code(_check_identity_surface_privilege(plan), "W_AUTH_PRIVILEGED_ROLE_FIELD")
    assert len(warning) == 1
    assert warning[0].evidence["reason"] == "privileged-role-field-boundary-untested"


def test_identity_surface_with_role_boundary_check_is_silent() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/register.py"],
                checks=["python -m pytest tests/auth/test_register_role_privilege.py -q"],
                covers_flows=["register_flow"],
            ),
        ],
        "critical_flows": [
            _flow("rbac_admin_write", surface_type="rbac_write", entrypoints=["src/admin.py"]),
            _flow("register_flow", surface_type="identity_register", entrypoints=["src/register.py"]),
        ],
    })

    assert _issues_by_code(_check_identity_surface_privilege(plan), "W_AUTH_PRIVILEGED_ROLE_FIELD") == []


def test_security_flow_without_identity_surface_declaration_is_silent() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/admin.py"],
                checks=["python -m pytest tests/auth/test_admin_auth.py -q"],
                covers_flows=["rbac_admin_write"],
            ),
        ],
        "critical_flows": [_flow("rbac_admin_write", surface_type="rbac_write", entrypoints=["src/admin.py"])],
    })

    assert _issues_by_code(_check_identity_surface_privilege(plan), "W_AUTH_PRIVILEGED_ROLE_FIELD") == []


def test_uncovered_identity_surface_is_ignored_by_this_rule() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/admin.py"],
                checks=["python -m pytest tests/auth/test_admin_auth.py -q"],
                covers_flows=["rbac_admin_write"],
            ),
        ],
        "critical_flows": [
            _flow("rbac_admin_write", surface_type="rbac_write", entrypoints=["src/admin.py"]),
            _flow("register_flow", surface_type="identity_register", entrypoints=["src/register.py"]),
        ],
    })

    assert _issues_by_code(_check_identity_surface_privilege(plan), "W_AUTH_PRIVILEGED_ROLE_FIELD") == []


def test_plan_without_security_critical_flow_is_silent() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/checkout.py"],
                checks=["python -m pytest tests/test_checkout.py -q"],
                covers_flows=["checkout_flow"],
            ),
        ],
        "critical_flows": [_flow("checkout_flow", description="checkout", entrypoints=["src/checkout.py"])],
    })

    assert _issues_by_code(_check_identity_surface_privilege(plan), "W_AUTH_PRIVILEGED_ROLE_FIELD") == []
