from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


def _hints_by_code(report, code: str) -> list:
    return [issue for issue in report.hints if issue.code == code]


def _checks() -> list[dict[str, object]]:
    return [
        {"name": "compile", "command": "python -m py_compile src/cccc/ralph/validator.py"},
        {"name": "unit", "command": "pytest tests/ralph/test_rve3_dead_command.py -q", "required": True},
    ]


def _plan(command: str) -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "role": "leaf",
            "claimed_paths": ["src/cccc/ralph/validator.py"],
            "goal_behavior": "Keep verification checks aligned with validator behavior.",
            "acceptance_criteria": "validator emits the expected hints",
            "verification": {
                "level": "unit",
                "command": command,
                "checks": _checks(),
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


def test_complex_command_with_checks_hints() -> None:
    plan = _plan("cd x && pytest y")

    report = validate(plan)

    assert _hints_by_code(report, "H_VERIFICATION_COMMAND_DEAD")


def test_simple_command_no_hint() -> None:
    plan = _plan("pytest tests/foo.py")

    report = validate(plan)

    assert _hints_by_code(report, "H_VERIFICATION_COMMAND_DEAD") == []
