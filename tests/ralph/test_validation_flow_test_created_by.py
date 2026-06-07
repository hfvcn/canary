from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


TARGET_CODE = "E_FLOW_TEST_CREATED_BY_UNKNOWN_TASK"


def _all_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _errors_by_code(report, code: str) -> list:
    return [issue for issue in report.errors if issue.code == code]


def _plan(*, critical_flows: list[dict] | None = None, forbidden_flows: list[dict] | None = None) -> Plan:
    return Plan.model_validate({
        "tasks": [{"id": "T1"}],
        "critical_flows": critical_flows or [],
        "forbidden_flows": forbidden_flows or [],
    })


def test_critical_flow_with_unknown_test_created_by_emits_issue() -> None:
    report = validate(_plan(critical_flows=[{"id": "critical-flow", "test_created_by": ["ghost"]}]))
    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].task_ids == ["ghost"]
    assert issues[0].evidence == {
        "flow_id": "critical-flow",
        "namespace": "critical",
        "unknown_id": "ghost",
    }


def test_forbidden_flow_with_unknown_test_created_by_emits_issue() -> None:
    report = validate(_plan(forbidden_flows=[{"id": "forbidden-flow", "test_created_by": ["ghost"]}]))
    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].task_ids == ["ghost"]
    assert issues[0].evidence == {
        "flow_id": "forbidden-flow",
        "namespace": "forbidden",
        "unknown_id": "ghost",
    }


def test_known_test_created_by_is_silent() -> None:
    report = validate(_plan(critical_flows=[{"id": "critical-flow", "test_created_by": ["T1"]}]))

    assert TARGET_CODE not in _all_codes(report)


def test_missing_test_created_by_field_is_silent() -> None:
    report = validate(_plan(critical_flows=[{"id": "critical-flow"}]))

    assert TARGET_CODE not in _all_codes(report)


def test_no_flows_is_silent() -> None:
    report = validate(_plan())

    assert TARGET_CODE not in _all_codes(report)
