from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(
    task_id: str,
    *,
    claimed_paths: list[str],
    awareness_paths: list[str],
    goal_behavior: str,
) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=claimed_paths,
        awareness_paths=awareness_paths,
        goal_behavior=goal_behavior,
        acceptance_criteria=f"{task_id} complete",
        verification=Verification(
            level="unit",
            command=f"python -m py_compile {claimed_paths[0]}",
            covers=VerificationCovers(tasks=[task_id]),
        ),
    )


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def test_hex_not_in_awareness_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "worker.py", "VALUE = 1\n")
    _write(tmp_path / "src" / "awareness.py", "KNOWN = 0xCD\n")

    plan = Plan(tasks=[
        _task(
            "T1",
            claimed_paths=["src/worker.py"],
            awareness_paths=["src/awareness.py"],
            goal_behavior="Write marker 0xAB into the frame header.",
        )
    ])

    report = validate_with_project(plan, project_root=tmp_path)

    issues = _issues_by_code(report, "W_GOAL_HARDCODED_WITHOUT_AWARENESS")
    assert len(issues) == 1
    assert issues[0].evidence["value"] == "0xAB"
    assert issues[0].task_ids == ["T1"]


def test_hex_in_awareness_ok(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "worker.py", "VALUE = 1\n")
    _write(tmp_path / "src" / "awareness.py", "KNOWN = 0xAB\n")

    plan = Plan(tasks=[
        _task(
            "T1",
            claimed_paths=["src/worker.py"],
            awareness_paths=["src/awareness.py"],
            goal_behavior="Write marker 0xAB into the frame header.",
        )
    ])

    report = validate_with_project(plan, project_root=tmp_path)

    assert _issues_by_code(report, "W_GOAL_HARDCODED_WITHOUT_AWARENESS") == []
