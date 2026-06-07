from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan, TaskSpec, ValidationIssue, Verification
from cccc.ralph.validator import validate_with_project
from cccc.ralph.validation_rules.coverage import (
    _check_status_code_implementation_drift,
)


TARGET_CODE = "W_STATUS_CODE_IMPLEMENTATION_DRIFT"


def _write_source(project_root: Path, relative_path: str, content: str) -> str:
    source_path = project_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(content, encoding="utf-8")
    return relative_path


def _issues_by_code(issues: list[ValidationIssue], code: str) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.code == code]


def _task(*, goal_behavior: str, claimed_paths: list[str]) -> TaskSpec:
    compile_target = next(
        (path for path in claimed_paths if path.endswith(".py")),
        "src/task.py",
    )
    return TaskSpec(
        id="T1",
        claimed_paths=claimed_paths,
        goal_behavior=goal_behavior,
        acceptance_criteria="implementation matches declared status codes",
        verification=Verification.model_validate({
            "level": "unit",
            "command": "",
            "checks": [{
                "name": "compile",
                "command": f"python -m py_compile {compile_target}",
            }],
            "covers": {"tasks": ["T1"]},
        }),
    )


def _plan(*, goal_behavior: str, claimed_paths: list[str]) -> Plan:
    return Plan(tasks=[_task(goal_behavior=goal_behavior, claimed_paths=claimed_paths)])


def test_validate_with_project_warns_when_goal_code_missing_from_source(tmp_path: Path) -> None:
    claimed_path = _write_source(
        tmp_path,
        "src/service.py",
        "def remove_resource():\n    return 404\n",
    )
    report = validate_with_project(
        _plan(
            goal_behavior="删除不存在资源时返回 410",
            claimed_paths=[claimed_path],
        ),
        project_root=tmp_path,
    )

    issues = _issues_by_code([*report.errors, *report.warnings, *report.hints], TARGET_CODE)

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence == {
        "goal_codes": ["410"],
        "implementation_codes": ["404"],
        "drifted": ["410"],
        "scanned_paths": ["src/service.py"],
    }


def test_matching_goal_and_source_status_codes_emit_no_warning(tmp_path: Path) -> None:
    claimed_path = _write_source(
        tmp_path,
        "src/service.py",
        "def remove_resource():\n    return 410\n",
    )
    issues = _check_status_code_implementation_drift(
        _plan(
            goal_behavior="删除不存在资源时返回 410",
            claimed_paths=[claimed_path],
        ),
        project_root=tmp_path,
    )

    assert _issues_by_code(issues, TARGET_CODE) == []


def test_goal_without_status_code_declaration_is_skipped(tmp_path: Path) -> None:
    claimed_path = _write_source(
        tmp_path,
        "src/service.py",
        "def remove_resource():\n    return 410\n",
    )
    issues = _check_status_code_implementation_drift(
        _plan(
            goal_behavior="删除不存在资源时返回明确的错误",
            claimed_paths=[claimed_path],
        ),
        project_root=tmp_path,
    )

    assert issues == []


def test_missing_claimed_python_file_is_skipped(tmp_path: Path) -> None:
    issues = _check_status_code_implementation_drift(
        _plan(
            goal_behavior="删除不存在资源时返回 410",
            claimed_paths=["src/missing.py"],
        ),
        project_root=tmp_path,
    )

    assert issues == []
