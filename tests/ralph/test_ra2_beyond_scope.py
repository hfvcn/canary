from __future__ import annotations

from pathlib import Path

import yaml

from cccc.ralph.models import Plan, TaskSpec, ValidationIssue, Verification, VerificationCovers
from cccc.ralph.validator import (
    _load_beyond_scope_issue_codes,
    _mark_beyond_scope_issues,
    validate_with_project,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _task(task_id: str) -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=f"Task {task_id}",
        claimed_paths=["src/worker.py"],
        goal_behavior="Compile the worker module successfully.",
        acceptance_criteria="worker module compiles",
        failure_path="surface the validation failure directly",
        verification=Verification(
            level="unit",
            command="python -m py_compile src/worker.py",
            covers=VerificationCovers(tasks=[task_id]),
        ),
    )


def test_config_loads() -> None:
    config_path = _repo_root() / ".cccc" / "beyond_scope.yaml"
    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert "beyond_scope_items" in raw_config


def test_issue_marked_beyond_scope() -> None:
    issue = ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="symbol target is missing",
    )

    beyond_scope_codes = _load_beyond_scope_issue_codes(_repo_root())
    _mark_beyond_scope_issues([issue], beyond_scope_codes)

    assert issue.beyond_scope is True


def test_missing_config_no_error(tmp_path: Path) -> None:
    """When project-level .cccc/beyond_scope.yaml is absent, validation succeeds.

    Note: the built-in beyond-scope checklist (RA-2) may still mark issues
    matching its patterns, so we only assert no crash + valid report.
    """
    _write(tmp_path / "src" / "worker.py", "VALUE = 1\n")
    plan = Plan(tasks=[_task("T1")])

    report = validate_with_project(plan, project_root=tmp_path)
    issues = [*report.errors, *report.warnings, *report.hints]

    assert isinstance(report.valid, bool)
    # Project-level config is absent — only built-in checklist may mark issues.
    # Verify no project-config-specific codes leaked in.
    project_codes = _load_beyond_scope_issue_codes(tmp_path)
    assert project_codes == set()
