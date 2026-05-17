from __future__ import annotations

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate


def _issues(report, code: str) -> list:
    return [
        issue
        for issue in [*report.errors, *report.warnings, *report.hints]
        if issue.code == code
    ]


def _task(task_id: str, claimed_paths: list[str]) -> dict:
    return {
        "id": task_id,
        "claimed_paths": claimed_paths,
        "acceptance_criteria": "done",
        "verification": {
            "level": "unit",
            "command": "true",
            "covers": {"tasks": [task_id]},
        },
    }


def test_shared_path_message_names_task_pair_and_paths() -> None:
    plan = Plan.model_validate({
        "tasks": [
            _task("T1", ["app/"]),
            _task("T2", ["app/routes.py"]),
        ],
    })

    report = validate(plan)

    issues = _issues(report, "W_SHARED_PATH_NO_DEPENDENCY")
    assert len(issues) == 1
    assert "T1 claims app/ which contains T2's app/routes.py" in issues[0].message
