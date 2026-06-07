from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import get_all_rules
from cccc.ralph.validation_rules.coverage import (
    _check_claimed_test_not_exercised,
    _check_critical_flow_independent_review,
)
from cccc.ralph.validation_rules.security import _check_rbac_flow_auth_coverage
from cccc.ralph.validator import validate


TARGET_CODES = {
    "W_RBAC_FLOW_AUTH_UNVERIFIED",
    "W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW",
    "W_CLAIMED_TEST_NOT_EXERCISED",
}


def _issue_codes(report) -> set[str]:
    issues = [*report.errors, *report.warnings, *report.hints]
    return {issue.code for issue in issues}


def _dirty_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/auth.py", "tests/foo_test.py"],
                "acceptance_criteria": "critical auth flow is covered",
                "verification_mode": "ralph",
                "verification": {
                    "level": "unit",
                    "command": "python -m pytest tests/bar_test.py -q",
                    "checks": [
                        {
                            "name": "behavior-check",
                            "command": "python -m pytest tests/bar_test.py -q",
                        }
                    ],
                    "covers": {"tasks": ["T1"], "flows": ["rbac_login_flow"]},
                },
            }
        ],
        "critical_flows": [
            {
                "id": "rbac_login_flow",
                "entrypoints": ["src/auth.py"],
                "required_verification_level": "unit",
            }
        ],
    })


def _clean_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/auth.py", "tests/auth/test_login_401.py"],
                "acceptance_criteria": "critical auth flow is covered",
                "verification_mode": "agent",
                "verification": {
                    "level": "unit",
                    "command": "python -m pytest tests/auth/test_login_401.py -q",
                    "checks": [
                        {
                            "name": "auth-check",
                            "command": "python -m pytest tests/auth/test_login_401.py -q",
                        }
                    ],
                    "covers": {"tasks": ["T1"], "flows": ["rbac_login_flow"]},
                },
            }
        ],
        "critical_flows": [
            {
                "id": "rbac_login_flow",
                "entrypoints": ["src/auth.py"],
                "required_verification_level": "unit",
            }
        ],
    })


def test_validate_reports_all_v47_codes_on_dirty_plan() -> None:
    report = validate(_dirty_plan())

    assert TARGET_CODES <= _issue_codes(report)


def test_validate_omits_all_v47_codes_on_clean_plan() -> None:
    report = validate(_clean_plan())

    assert _issue_codes(report).isdisjoint(TARGET_CODES)


def test_get_all_rules_lists_v47_rule_functions() -> None:
    rules = get_all_rules()

    assert _check_rbac_flow_auth_coverage in rules
    assert _check_critical_flow_independent_review in rules
    assert _check_claimed_test_not_exercised in rules
