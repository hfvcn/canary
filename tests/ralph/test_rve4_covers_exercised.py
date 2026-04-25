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


def _plan(t2_check_command: str) -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "role": "leaf",
                "claimed_paths": ["src/cccc/ralph/validator.py"],
                "provides": [{"name": "validator_contract"}],
                "goal_behavior": "Implement validator changes.",
                "acceptance_criteria": "validator change is complete",
                "verification": {
                    "level": "unit",
                    "checks": _checks(["pytest tests/ralph/test_validator.py -q"]),
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "role": "verification",
                "depends_on": ["T1"],
                "claimed_paths": ["tests/ralph/test_validator_flow.py"],
                "goal_behavior": "Exercise the downstream verification flow.",
                "acceptance_criteria": "downstream verification passes",
                "verification": {
                    "level": "integration",
                    "checks": _checks([t2_check_command]),
                    "covers": {"tasks": ["T1"]},
                },
            },
        ],
    })


def test_covers_no_reference_flagged() -> None:
    plan = _plan("pytest tests/ralph/test_validator_flow.py -q")

    report = validate(plan)
    issues = _warnings_by_code(report, "W_COVERS_NOT_EXERCISED")

    assert len(issues) == 1
    assert issues[0].task_ids == ["T2", "T1"]


def test_covers_with_reference_ok() -> None:
    plan = _plan("pytest tests/ralph/test_validator_flow.py -q -k validator.py")

    report = validate(plan)

    assert _warnings_by_code(report, "W_COVERS_NOT_EXERCISED") == []
