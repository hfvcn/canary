from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan
from cccc.ralph.validator import validate_with_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _issues_by_code(report, code: str) -> list:
    return [issue for issue in [*report.errors, *report.warnings, *report.hints] if issue.code == code]


def _plan(command: str, *, covers_paths: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/feature.py"],
            "acceptance_criteria": "feature verified",
            "verification": {
                "level": "unit",
                "command": command,
                "covers": {
                    "tasks": ["T1"],
                    "paths": covers_paths or [],
                },
            },
        }],
    })


def _cross_task_plan(command: str) -> Plan:
    return Plan.model_validate({
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/service.py"],
                "acceptance_criteria": "service is updated",
            },
            {
                "id": "T2",
                "depends_on": ["T1"],
                "claimed_paths": ["tests/test_flow.py"],
                "acceptance_criteria": "flow is verified",
                "verification": {
                    "level": "unit",
                    "command": command,
                    "covers": {"tasks": ["T1"]},
                },
            },
        ],
    })


def test_pytest_explicit_file_not_in_covers_paths_warns(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "feature.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_feature.py", "def test_feature():\n    assert True\n")

    report = validate_with_project(
        _plan("pytest tests/test_feature.py -q"),
        project_root=tmp_path,
    )

    issues = _issues_by_code(report, "W_COVERS_PATHS_UNVERIFIED")
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].evidence["path"] == "tests/test_feature.py"


def test_make_test_is_skipped_for_v1_literal_rule(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "feature.py", "VALUE = 1\n")

    report = validate_with_project(_plan("make test"), project_root=tmp_path)

    assert _issues_by_code(report, "W_COVERS_PATHS_UNVERIFIED") == []


def test_covers_tasks_auto_expanded_paths_are_allowed(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "service.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_flow.py", "def test_flow():\n    assert True\n")

    report = validate_with_project(
        _cross_task_plan("python -m pytest src/service.py"),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, "W_COVERS_PATHS_UNVERIFIED") == []


def test_explicit_file_in_covers_paths_is_ok(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "feature.py", "VALUE = 1\n")
    _write(tmp_path / "tests" / "test_feature.py", "def test_feature():\n    assert True\n")

    report = validate_with_project(
        _plan(
            "pytest tests/test_feature.py -q",
            covers_paths=["tests/test_feature.py"],
        ),
        project_root=tmp_path,
    )

    assert _issues_by_code(report, "W_COVERS_PATHS_UNVERIFIED") == []
