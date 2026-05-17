from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


def _issues(report, code: str) -> list:
    return [
        issue
        for issue in [*report.errors, *report.warnings, *report.hints]
        if issue.code == code
    ]


def _task(
    *,
    goal_behavior: str,
    claimed_paths: list[str] | None = None,
    awareness_paths: list[str] | None = None,
) -> dict:
    return {
        "id": "T1",
        "goal_behavior": goal_behavior,
        "claimed_paths": claimed_paths or ["src/known.py"],
        "awareness_paths": awareness_paths or [],
        "acceptance_criteria": "done",
        "verification": {
            "level": "unit",
            "command": "true",
            "covers": {"tasks": ["T1"]},
        },
    }


def test_goal_file_reference_missing_from_claims_warns() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(goal_behavior="Modify src/missing.py and update src/known.py."),
        ],
    })

    report = validate(plan)

    issues = _issues(report, "W_CLAIMED_PATH_INCOMPLETE")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].evidence["referenced_path"] == "src/missing.py"


def test_awareness_path_satisfies_goal_file_reference() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task(
                goal_behavior="Write to config/app.yaml.",
                awareness_paths=["config/app.yaml"],
            ),
        ],
    })

    report = validate(plan)

    assert _issues(report, "W_CLAIMED_PATH_INCOMPLETE") == []
