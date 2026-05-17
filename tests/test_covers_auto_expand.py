from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


def _issues(report, code: str) -> list:
    return [
        issue
        for issue in [*report.errors, *report.warnings, *report.hints]
        if issue.code == code
    ]


def _plan(*, covers_paths: list[str] | None = None) -> Plan:
    covers = {"tasks": ["T1"]}
    if covers_paths is not None:
        covers["paths"] = covers_paths
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/service.py"],
                "acceptance_criteria": "service is updated",
                "verification": {
                    "level": "unit",
                    "command": "python -m pytest tests/test_service.py",
                    "covers": {"tasks": ["T1"]},
                },
            },
            {
                "id": "T2",
                "role": "verification",
                "depends_on": ["T1"],
                "claimed_paths": ["tests/test_flow.py"],
                "acceptance_criteria": "flow is verified",
                "verification": {
                    "level": "integration",
                    "command": "python -m pytest tests/test_flow.py",
                    "covers": covers,
                },
            },
        ],
    })


def test_covers_tasks_auto_expands_claimed_paths_as_hint() -> None:
    report = validate(_plan())

    issues = _issues(report, "W_COVERS_NOT_EXERCISED")
    assert len(issues) == 1
    assert issues[0].severity == "hint"
    assert issues[0].evidence["covered_paths"] == ["src/service.py"]
    assert issues[0].evidence["auto_expanded_from_covers_tasks"] is True


def test_explicit_covers_paths_keeps_warning_level() -> None:
    report = validate(_plan(covers_paths=["src/service.py"]))

    issues = _issues(report, "W_COVERS_NOT_EXERCISED")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].evidence["auto_expanded_from_covers_tasks"] is False
