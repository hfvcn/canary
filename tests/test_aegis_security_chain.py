from __future__ import annotations

from cccc.ralph.models import (
    CheckSpec,
    CriticalFlow,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
)
from cccc.ralph.validator import validate

SECURITY_CODE = "E_AEGIS_SECURITY_CHAIN_MISSING"
ENTRYPOINT = "src/auth.py"


def test_feature_with_security_flow_and_empty_checks_reports_error() -> None:
    report = validate(_plan(intent="feature", checks=[]))

    issue = _only_security_error(report)
    assert issue.task_ids == ["T1"]
    assert issue.evidence["intent"] == "feature"
    assert issue.evidence["critical_flows"] == ["ssrf_protection"]
    assert issue.evidence["check_names"] == []


def test_feature_with_security_flow_and_security_checks_passes() -> None:
    report = validate(_plan(intent="feature", checks=[_security_check()]))

    assert SECURITY_CODE not in _error_codes(report)


def test_feature_without_security_flow_passes() -> None:
    report = validate(_plan(intent="feature", flow_id="data_pipeline", checks=[]))

    assert SECURITY_CODE not in _error_codes(report)


def test_fix_with_security_flow_and_empty_checks_passes() -> None:
    report = validate(_plan(intent="fix", checks=[]))

    assert SECURITY_CODE not in _error_codes(report)


def _plan(*, intent: str, checks: list[CheckSpec], flow_id: str = "ssrf_protection") -> Plan:
    return Plan(
        tasks=[_task(intent=intent, flow_id=flow_id, checks=checks)],
        critical_flows=[
            CriticalFlow(
                id=flow_id,
                entrypoints=[ENTRYPOINT],
                required_verification_level="unit",
            )
        ],
        semantic_mode="off",
    )


def _task(*, intent: str, flow_id: str, checks: list[CheckSpec]) -> TaskSpec:
    return TaskSpec(
        id="T1",
        title="Implement authentication path",
        claimed_paths=[ENTRYPOINT],
        verification_mode="challenge",
        verification=Verification(
            level="unit",
            checks=checks,
            covers=VerificationCovers(tasks=["T1"], flows=[flow_id]),
        ),
        aegis={"intent": intent},
    )


def _security_check() -> CheckSpec:
    return CheckSpec(
        name="ssrf behavior test",
        command="python -m pytest tests/test_aegis_security_chain.py -q",
    )


def _only_security_error(report):
    matches = [issue for issue in report.errors if issue.code == SECURITY_CODE]
    assert len(matches) == 1
    return matches[0]


def _error_codes(report) -> list[str]:
    return [issue.code for issue in report.errors]
