from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    CriticalFlow,
    Plan,
    TaskSpec,
    ValidationIssue,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate


CRITICAL_FLOW_ID = "critical_checkout_flow"
CLAIMED_PATH = "src/checkout.py"


def _make_plan(*, covers_flows: list[str], checks: list[CheckSpec]) -> Plan:
    return Plan(
        tasks=[
            TaskSpec(
                id="T1",
                claimed_paths=[CLAIMED_PATH],
                acceptance_criteria="checkout path works",
                verification=Verification(
                    level="unit",
                    command=checks[0].command,
                    checks=checks,
                    covers=VerificationCovers(tasks=["T1"], flows=covers_flows),
                ),
            )
        ],
        critical_flows=[
            CriticalFlow(
                id=CRITICAL_FLOW_ID,
                entrypoints=[CLAIMED_PATH],
                required_verification_level="unit",
            )
        ],
    )


def _issue_codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def test_shallow_checks_critical_flow_is_error() -> None:
    plan = _make_plan(
        covers_flows=[CRITICAL_FLOW_ID],
        checks=[
            CheckSpec(
                name="compile_check",
                command=f"python -m py_compile {CLAIMED_PATH}",
            )
        ],
    )

    report = validate(plan)

    assert "E_VERIFICATION_SHALLOW_CRITICAL" in _issue_codes(report.errors)
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in _issue_codes(report.warnings)


def test_shallow_checks_non_critical_stays_warning() -> None:
    plan = _make_plan(
        covers_flows=[],
        checks=[
            CheckSpec(
                name="compile_check",
                command=f"python -m py_compile {CLAIMED_PATH}",
            )
        ],
    )

    report = validate(plan)

    assert "W_VERIFICATION_SHALLOW_CHECKS" in _issue_codes(report.warnings)
    assert "E_VERIFICATION_SHALLOW_CRITICAL" not in _issue_codes(report.errors)


def test_behavioral_check_bypasses() -> None:
    plan = _make_plan(
        covers_flows=[CRITICAL_FLOW_ID],
        checks=[
            CheckSpec(
                name="behavior_test",
                command="python -m pytest tests/test_checkout.py -q",
            )
        ],
    )

    report = validate(plan)

    all_codes = _issue_codes(report.errors) + _issue_codes(report.warnings)
    assert "E_VERIFICATION_SHALLOW_CRITICAL" not in all_codes
    assert "W_VERIFICATION_SHALLOW_CHECKS" not in all_codes
