from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


TARGET_CODE = "E_FLOW_ID_CROSS_NAMESPACE_COLLISION"


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


def test_cross_namespace_flow_id_collision_emits_issue() -> None:
    report = validate(_plan(
        critical_flows=[{"id": "shared-flow"}],
        forbidden_flows=[{"id": "shared-flow"}],
    ))
    issues = _errors_by_code(report, TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].evidence == {"flow_id": "shared-flow"}


def test_disjoint_flow_ids_are_silent() -> None:
    report = validate(_plan(
        critical_flows=[{"id": "critical-flow"}],
        forbidden_flows=[{"id": "forbidden-flow"}],
    ))

    assert TARGET_CODE not in _all_codes(report)


def test_internal_duplicate_only_is_silent_for_this_rule() -> None:
    report = validate(_plan(
        critical_flows=[{"id": "dup-flow"}, {"id": "dup-flow"}],
        forbidden_flows=[{"id": "other-flow"}],
    ))

    assert TARGET_CODE not in _all_codes(report)


def test_missing_forbidden_flows_is_silent() -> None:
    report = validate(_plan(critical_flows=[{"id": "critical-flow"}]))

    assert TARGET_CODE not in _all_codes(report)
