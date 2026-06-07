from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules.security import _non_suppressible_codes
from cccc.ralph.validator import validate


CODE = "W_SIGNOFF_STRUCTURE_WEAK"
AUTH_FLOW_ID = "admin_rbac_write"
CHECKOUT_FLOW_ID = "checkout_flow"
AUTH_ENTRYPOINT = "src/admin.py"
CHECKOUT_ENTRYPOINT = "src/checkout.py"
SIGNOFF_PATH = "docs/security-review.md"
ALWAYS_CODES = {
    "W_VERIFICATION_BEHAVIOR_MISMATCH",
    "W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE",
    "W_INTEGRATION_TASK_SHALLOW_VERIFICATION",
}


def _auth_flow() -> dict[str, object]:
    return {
        "id": AUTH_FLOW_ID,
        "surface_type": "rbac_write",
        "entrypoints": [AUTH_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _checkout_flow() -> dict[str, object]:
    return {
        "id": CHECKOUT_FLOW_ID,
        "entrypoints": [CHECKOUT_ENTRYPOINT],
        "required_verification_level": "unit",
    }


def _review_task() -> dict[str, object]:
    return {
        "id": "security-review",
        "claimed_paths": [AUTH_ENTRYPOINT, SIGNOFF_PATH],
        "verification_mode": "agent",
        "verification": {
            "level": "unit",
            "checks": [
                {
                    "name": "authz-negative",
                    "command": "python -m pytest tests/auth/test_admin_403_role.py -q",
                },
                {
                    "name": "signoff-approved",
                    "command": "grep -qiE 'approved' docs/security-review.md",
                },
            ],
            "covers": {"flows": [AUTH_FLOW_ID]},
        },
    }


def _plan(
    *,
    critical_flows: list[dict[str, object]],
    suppress_codes: list[str] | None = None,
    tasks: list[dict[str, object]] | None = None,
) -> Plan:
    return Plan.model_validate({
        "suppress_codes": suppress_codes or [],
        "tasks": tasks or [],
        "critical_flows": critical_flows,
    })


def _warning_codes(plan: Plan) -> list[str]:
    return [issue.code for issue in validate(plan).warnings]


def test_signoff_structure_weak_non_suppressible_with_security_flow() -> None:
    plan = _plan(
        critical_flows=[_auth_flow()],
        suppress_codes=[CODE],
        tasks=[_review_task()],
    )

    assert CODE in _warning_codes(plan)


def test_non_suppressible_codes_includes_signoff_weak() -> None:
    codes = _non_suppressible_codes(_plan(critical_flows=[_auth_flow()]))

    assert CODE in codes


def test_non_suppressible_codes_empty_for_non_security_plan() -> None:
    codes = _non_suppressible_codes(_plan(critical_flows=[_checkout_flow()]))

    assert codes == ALWAYS_CODES
