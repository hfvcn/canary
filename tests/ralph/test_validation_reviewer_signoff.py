from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.security import _check_reviewer_signoff


def _task(
    task_id: str,
    *,
    flow_id: str,
    claimed_paths: list[str],
    verification_mode: str = "ralph",
) -> dict:
    return {
        "id": task_id,
        "claimed_paths": claimed_paths,
        "verification_mode": verification_mode,
        "verification": {
            "level": "unit",
            "command": "python -m pytest tests/auth/test_rbac_403_role.py -q",
            "checks": [{"name": "authz", "command": "python -m pytest tests/auth/test_rbac_403_role.py -q"}],
            "covers": {"flows": [flow_id]},
        },
    }


def _flow(flow_id: str) -> dict:
    return {
        "id": flow_id,
        "surface_type": "rbac_write",
        "entrypoints": ["src/admin.py"],
        "required_verification_level": "unit",
    }


def _issues_by_code(issues, code: str) -> list:
    return [issue for issue in issues if issue.code == code]


def test_security_flow_with_review_semantics_but_no_signoff_warns() -> None:
    plan = Plan.model_validate({
        "tasks": [_task("review", flow_id="admin_flow", claimed_paths=["src/admin.py"], verification_mode="agent")],
        "critical_flows": [_flow("admin_flow")],
    })

    warning = _issues_by_code(_check_reviewer_signoff(plan), "W_REVIEWER_SIGNOFF_MISSING")
    assert len(warning) == 1
    assert warning[0].evidence["reason"] == "no-auditable-signoff"


def test_review_artifact_path_satisfies_signoff_requirement() -> None:
    plan = Plan.model_validate({
        "tasks": [_task(
            "review",
            flow_id="admin_flow",
            claimed_paths=["src/admin.py", "docs/security-review.md"],
            verification_mode="agent",
        )],
        "critical_flows": [_flow("admin_flow")],
    })

    assert _issues_by_code(_check_reviewer_signoff(plan), "W_REVIEWER_SIGNOFF_MISSING") == []


def test_missing_review_semantics_is_left_to_independent_review_rule() -> None:
    plan = Plan.model_validate({
        "tasks": [_task("executor", flow_id="admin_flow", claimed_paths=["src/admin.py"])],
        "critical_flows": [_flow("admin_flow")],
    })

    assert _issues_by_code(_check_reviewer_signoff(plan), "W_REVIEWER_SIGNOFF_MISSING") == []


def test_non_security_plan_does_not_emit_signoff_issue() -> None:
    plan = Plan.model_validate({
        "tasks": [_task("review", flow_id="checkout_flow", claimed_paths=["src/checkout.py"], verification_mode="agent")],
        "critical_flows": [{
            "id": "checkout_flow",
            "entrypoints": ["src/checkout.py"],
            "required_verification_level": "unit",
        }],
    })

    assert _issues_by_code(_check_reviewer_signoff(plan), "W_REVIEWER_SIGNOFF_MISSING") == []
