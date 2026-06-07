from __future__ import annotations

from cccc.ralph.models import Plan, ValidationReport
from cccc.ralph.validation_rules import (
    _check_security_critical_flow_suppressed,
    get_all_rules,
)
from cccc.ralph.validator import validate


SECURITY_SUPPRESSED = "E_SECURITY_CRITICAL_FLOW_SUPPRESSED"


def _issue_codes(report: ValidationReport, bucket: str) -> list[str]:
    return [issue.code for issue in getattr(report, bucket)]


def _plan(
    *,
    suppress_flows: list[str] | None = None,
    suppress_codes: list[str] | None = None,
    flow_id: str = "critical_route",
    description: str = "critical request path",
    entrypoints: list[str] | None = None,
) -> Plan:
    flow_entrypoints = entrypoints or ["src/rbac/routes.py"]
    return Plan.model_validate({
        "suppress_flows": suppress_flows or [],
        "suppress_codes": suppress_codes or [],
        "tasks": [{
            "id": "T1",
            "claimed_paths": flow_entrypoints,
            "acceptance_criteria": "critical flow is verified",
            "verification_mode": "ralph",
            "verification": {
                "level": "unit",
                "checks": [{
                    "name": "auth-boundary",
                    "command": "python -m pytest tests/auth/test_403.py -q",
                }],
                "covers": {"tasks": ["T1"], "flows": [flow_id]},
            },
        }],
        "critical_flows": [{
            "id": flow_id,
            "description": description,
            "entrypoints": flow_entrypoints,
            "required_verification_level": "unit",
        }],
    })


def test_suppress_flows_security_critical_flow_reports_error() -> None:
    report = validate(_plan(suppress_flows=["critical_route"]))

    assert SECURITY_SUPPRESSED in _issue_codes(report, "errors")


def test_suppress_flows_non_security_critical_flow_is_allowed() -> None:
    report = validate(_plan(
        suppress_flows=["checkout_flow"],
        flow_id="checkout_flow",
        description="checkout submit path",
        entrypoints=["src/checkout/submit.py"],
    ))

    assert SECURITY_SUPPRESSED not in _issue_codes(report, "errors")


def test_suppress_flows_unknown_flow_is_left_to_unknown_flow_warning() -> None:
    report = validate(_plan(suppress_flows=["missing_flow"]))

    assert SECURITY_SUPPRESSED not in _issue_codes(report, "errors")
    assert "W_SUPPRESS_FLOWS_UNKNOWN" in _issue_codes(report, "warnings")


def test_empty_suppress_flows_does_not_report_security_suppression() -> None:
    report = validate(_plan())

    assert SECURITY_SUPPRESSED not in _issue_codes(report, "errors")


def test_security_suppression_rule_cannot_be_suppressed_itself() -> None:
    report = validate(_plan(
        suppress_flows=["critical_route"],
        suppress_codes=[SECURITY_SUPPRESSED],
    ))

    assert SECURITY_SUPPRESSED in _issue_codes(report, "errors")
    assert SECURITY_SUPPRESSED not in _issue_codes(report, "hints")


def test_security_suppression_rule_is_registered() -> None:
    assert _check_security_critical_flow_suppressed in get_all_rules()
