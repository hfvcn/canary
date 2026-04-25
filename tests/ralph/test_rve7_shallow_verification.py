from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


def _warnings_by_code(report, code: str) -> list:
    return [issue for issue in report.warnings if issue.code == code]


def _checks(commands: list[str]) -> list[dict[str, str]]:
    return [
        {"name": f"check-{index}", "command": command}
        for index, command in enumerate(commands, start=1)
    ]


def _integration_plan(commands: list[str]) -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "role": "leaf",
                "claimed_paths": ["src/app.py"],
                "acceptance_criteria": "leaf task complete",
                "verification": {
                    "level": "unit",
                    "checks": _checks(["pytest tests/test_unit_app.py -q"]),
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "role": "integration",
                "depends_on": ["T1"],
                "claimed_paths": ["tests/test_integration_flow.py"],
                "acceptance_criteria": "integration flow complete",
                "verification": {
                    "level": "integration",
                    "checks": _checks(commands),
                    "covers": {"tasks": ["T1", "T2"]},
                },
            },
        ],
    })


def test_integration_grep_only_flagged() -> None:
    plan = _integration_plan([
        "grep -q READY logs/app.log",
        "python -m py_compile src/app.py",
    ])

    report = validate(plan)
    issues = _warnings_by_code(report, "W_INTEGRATION_TASK_SHALLOW_VERIFICATION")

    assert len(issues) == 1
    assert issues[0].task_ids == ["T2"]


def test_integration_with_behavioral_not_flagged() -> None:
    plan = _integration_plan([
        "grep -q READY logs/app.log",
        "pytest tests/test_integration_flow.py -q",
    ])

    report = validate(plan)

    assert _warnings_by_code(report, "W_INTEGRATION_TASK_SHALLOW_VERIFICATION") == []


def test_leaf_shallow_not_flagged() -> None:
    plan = Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "role": "leaf",
                "claimed_paths": ["src/app.py"],
                "acceptance_criteria": "leaf task complete",
                "verification": {
                    "level": "unit",
                    "checks": _checks(["grep -q READY logs/app.log"]),
                    "covers": {"tasks": ["T1"]},
                },
            }
        ]
    })

    report = validate(plan)

    assert _warnings_by_code(report, "W_INTEGRATION_TASK_SHALLOW_VERIFICATION") == []
