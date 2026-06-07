from __future__ import annotations

from cccc.ralph.models import Plan, ValidationReport
from cccc.ralph.validator import validate


WORKER_ONLY = "W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION"
NO_INDEPENDENT_REVIEW = "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW"
AUTH_FLOW_ID = "rbac_write_flow"
CHECKOUT_FLOW_ID = "checkout_flow"
AUTH_ENTRYPOINT = "src/auth/admin.py"
CHECKOUT_ENTRYPOINT = "src/checkout.py"
AUTHZ_CHECK = "python -m pytest tests/auth/test_admin_403_role.py -q"
CHECKOUT_CHECK = "python -m pytest tests/checkout/test_flow.py -q"


def _warning_codes(report: ValidationReport) -> list[str]:
    return [issue.code for issue in report.warnings]


def _hint_codes(report: ValidationReport) -> list[str]:
    return [issue.code for issue in report.hints]


def _plan(
    *,
    security_flow: bool,
    suppress_codes: list[str] | None = None,
    suppress_instances: list[dict[str, str]] | None = None,
) -> Plan:
    flow_id = AUTH_FLOW_ID if security_flow else CHECKOUT_FLOW_ID
    entrypoint = AUTH_ENTRYPOINT if security_flow else CHECKOUT_ENTRYPOINT
    check_command = AUTHZ_CHECK if security_flow else CHECKOUT_CHECK
    return Plan.model_validate({
        "suppress_codes": suppress_codes or [],
        "suppress_instances": suppress_instances or [],
        "tasks": [{
            "id": "T1",
            "claimed_paths": [entrypoint],
            "acceptance_criteria": "critical flow behavior is verified",
            "verification_mode": "ralph",
            "verification": {
                "level": "unit",
                "checks": [{"name": "authz-negative", "command": check_command}],
                "covers": {"flows": [flow_id]},
            },
        }],
        "critical_flows": [{
            "id": flow_id,
            "entrypoints": [entrypoint],
            "required_verification_level": "unit",
        }],
    })


def test_security_critical_flow_keeps_worker_only_warning_from_suppress_codes() -> None:
    report = validate(_plan(security_flow=True, suppress_codes=[WORKER_ONLY]))

    assert WORKER_ONLY in _warning_codes(report)
    assert WORKER_ONLY not in _hint_codes(report)


def test_security_critical_flow_keeps_independent_review_warning_from_suppress_instances() -> None:
    report = validate(_plan(
        security_flow=True,
        suppress_instances=[{"code": NO_INDEPENDENT_REVIEW}],
    ))

    assert NO_INDEPENDENT_REVIEW in _warning_codes(report)
    assert NO_INDEPENDENT_REVIEW not in _hint_codes(report)


def test_non_security_critical_flow_allows_independent_verification_suppression() -> None:
    report = validate(_plan(
        security_flow=False,
        suppress_codes=[WORKER_ONLY],
        suppress_instances=[{"code": NO_INDEPENDENT_REVIEW}],
    ))

    assert WORKER_ONLY not in _warning_codes(report)
    assert NO_INDEPENDENT_REVIEW not in _warning_codes(report)
    assert WORKER_ONLY in _hint_codes(report)
    assert NO_INDEPENDENT_REVIEW in _hint_codes(report)
