from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validation_rules import get_all_rules
from cccc.ralph.validation_rules.contracts import _check_consume_provider_unresolved
from cccc.ralph.validation_rules.coverage import (
    _check_flow_id_cross_namespace,
    _check_flow_test_created_by_unknown,
    _check_verification_non_gating,
)
from cccc.ralph.validator import validate


TARGET_CODES = {
    "E_VERIFICATION_NON_GATING",
    "E_FLOW_TEST_CREATED_BY_UNKNOWN_TASK",
    "E_FLOW_ID_CROSS_NAMESPACE_COLLISION",
    "E_CONSUME_PROVIDER_UNRESOLVED",
}


def _issue_codes(report) -> set[str]:
    return {issue.code for issue in [*report.errors, *report.warnings, *report.hints]}


def _dirty_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/t1.py"],
                "goal_behavior": "verification should gate task completion",
                "acceptance_criteria": "required checks block completion on failure",
                "verification": {
                    "level": "unit",
                    "command": "",
                    "checks": [
                        {"name": "advisory-1", "command": "pytest tests/a.py -q", "required": False},
                        {"name": "advisory-2", "command": "pytest tests/b.py -q", "required": False},
                    ],
                    "covers": {"tasks": ["T1"]},
                },
            },
            {"id": "P1", "provides": [{"name": "artifact"}]},
            {"id": "P2", "provides": [{"name": "artifact"}]},
            {"id": "C", "consumes": [{"name": "artifact"}]},
        ],
        "critical_flows": [
            {"id": "shared-flow", "test_created_by": ["ghost"]},
        ],
        "forbidden_flows": [
            {"id": "shared-flow", "test_created_by": ["ghost"]},
        ],
    })


def _clean_plan() -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/t1.py"],
                "goal_behavior": "verification should gate task completion",
                "acceptance_criteria": "required checks block completion on failure",
                "verification": {
                    "level": "unit",
                    "command": "",
                    "checks": [
                        {"name": "behavior-check", "command": "pytest tests/t1.py -q"},
                    ],
                    "covers": {"tasks": ["T1"]},
                },
            },
            {"id": "P1", "provides": [{"name": "artifact"}]},
            {"id": "C", "depends_on": ["P1"], "consumes": [{"name": "artifact"}]},
        ],
        "critical_flows": [
            {"id": "critical-flow", "test_created_by": ["T1"]},
        ],
        "forbidden_flows": [
            {"id": "forbidden-flow", "test_created_by": ["C"]},
        ],
    })


def test_validate_reports_all_v49_codes_on_dirty_plan() -> None:
    report = validate(_dirty_plan())

    assert TARGET_CODES <= _issue_codes(report)


def test_validate_omits_all_v49_codes_on_clean_plan() -> None:
    report = validate(_clean_plan())

    assert _issue_codes(report).isdisjoint(TARGET_CODES)


def test_get_all_rules_lists_v49_rule_functions() -> None:
    rules = get_all_rules()

    assert _check_verification_non_gating in rules
    assert _check_flow_test_created_by_unknown in rules
    assert _check_flow_id_cross_namespace in rules
    assert _check_consume_provider_unresolved in rules
