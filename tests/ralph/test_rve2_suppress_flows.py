from __future__ import annotations

from cccc.ralph.models import CriticalFlow, Plan
from cccc.ralph.validator import validate


def _make_plan(*, suppress_flows: list[str] | None = None) -> Plan:
    data = {
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "verification": {
                    "level": "unit",
                    "command": "true",
                    "covers": {"tasks": ["T1"]},
                },
            }
        ],
        "critical_flows": [
            CriticalFlow(id="daemon_startup"),
            CriticalFlow(id="cli_workflow"),
        ],
    }
    if suppress_flows is not None:
        data["suppress_flows"] = suppress_flows
    return Plan.model_validate(data)


def test_suppress_specific_flow() -> None:
    plan = _make_plan(suppress_flows=["daemon_startup"])

    report = validate(plan)

    suppressed_errors = [
        issue for issue in report.errors
        if issue.code == "E_CRITICAL_FLOW_UNCOVERED" and issue.evidence.get("flow_id") == "daemon_startup"
    ]
    suppressed_hints = [
        issue for issue in report.hints
        if issue.code == "E_CRITICAL_FLOW_UNCOVERED" and issue.evidence.get("flow_id") == "daemon_startup"
    ]

    assert suppressed_errors == []
    assert len(suppressed_hints) == 1
    assert suppressed_hints[0].message.startswith("[suppress_flows] ")


def test_unsuppressed_flow_still_reported() -> None:
    plan = _make_plan(suppress_flows=["daemon_startup"])

    report = validate(plan)

    unsuppressed_errors = [
        issue for issue in report.errors
        if issue.code == "E_CRITICAL_FLOW_UNCOVERED" and issue.evidence.get("flow_id") == "cli_workflow"
    ]

    assert len(unsuppressed_errors) == 1


def test_unknown_flow_warning() -> None:
    plan = _make_plan(suppress_flows=["unknown_flow"])

    report = validate(plan)

    warnings = [
        issue for issue in report.warnings
        if issue.code == "W_SUPPRESS_FLOWS_UNKNOWN" and issue.evidence.get("flow_id") == "unknown_flow"
    ]

    assert len(warnings) == 1
    assert warnings[0].message == "suppress_flows references unknown flow 'unknown_flow'"
