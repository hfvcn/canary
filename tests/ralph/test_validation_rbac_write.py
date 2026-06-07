from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.security import _check_rbac_write_endpoint_coverage


def _task(task_id: str, *, claimed_paths: list[str], checks: list[str], covers_flows: list[str] | None = None) -> dict:
    return {
        "id": task_id,
        "claimed_paths": claimed_paths,
        "verification": {
            "level": "unit",
            "command": checks[0] if checks else "",
            "checks": [
                {"name": f"check-{index}", "command": command}
                for index, command in enumerate(checks, start=1)
            ],
            "covers": {"flows": covers_flows or []},
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


def test_write_flow_with_auth_but_without_authz_negative_warns() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/auth/test_login_auth.py -q"],
                covers_flows=["rbac_write_flow"],
            ),
        ],
        "critical_flows": [_flow("rbac_write_flow", surface_type="rbac_write")],
    })

    warning = _issues_by_code(_check_rbac_write_endpoint_coverage(plan), "W_RBAC_WRITE_ENDPOINT_UNCOVERED")
    assert len(warning) == 1
    assert warning[0].evidence["reason"] == "auth-present-but-no-authz-negative-test"


def test_write_flow_with_authz_negative_check_is_silent() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/auth/test_login_403_role.py -q"],
                covers_flows=["rbac_write_flow"],
            ),
        ],
        "critical_flows": [_flow("rbac_write_flow", surface_type="rbac_write")],
    })

    assert _issues_by_code(_check_rbac_write_endpoint_coverage(plan), "W_RBAC_WRITE_ENDPOINT_UNCOVERED") == []


def test_write_flow_without_auth_check_is_left_to_auth_rule() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/unit/test_profile.py -q"],
                covers_flows=["rbac_write_flow"],
            ),
        ],
        "critical_flows": [_flow("rbac_write_flow", surface_type="rbac_write")],
    })

    assert _issues_by_code(_check_rbac_write_endpoint_coverage(plan), "W_RBAC_WRITE_ENDPOINT_UNCOVERED") == []


def test_non_write_auth_flow_does_not_warn() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/auth.py"],
                checks=["python -m pytest tests/auth/test_login_auth.py -q"],
                covers_flows=["rbac_read_flow"],
            ),
        ],
        "critical_flows": [_flow("rbac_read_flow", surface_type="rbac_read")],
    })

    assert _issues_by_code(_check_rbac_write_endpoint_coverage(plan), "W_RBAC_WRITE_ENDPOINT_UNCOVERED") == []


def test_non_security_flow_does_not_warn() -> None:
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

    assert _issues_by_code(_check_rbac_write_endpoint_coverage(plan), "W_RBAC_WRITE_ENDPOINT_UNCOVERED") == []


def test_uncovered_write_flow_is_ignored_by_this_rule() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                "T1",
                claimed_paths=["src/other.py"],
                checks=["python -m pytest tests/auth/test_login_auth.py -q"],
            ),
        ],
        "critical_flows": [_flow("rbac_write_flow", surface_type="rbac_write", entrypoints=["src/auth.py"])],
    })

    assert _issues_by_code(_check_rbac_write_endpoint_coverage(plan), "W_RBAC_WRITE_ENDPOINT_UNCOVERED") == []
