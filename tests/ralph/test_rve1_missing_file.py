from __future__ import annotations

from pathlib import Path

from cccc.ralph.filesystem_validator import validate_filesystem
from cccc.ralph.models import Plan
from cccc.ralph.workspace_index import WorkspaceIndex


def _plan(command: str, checks: list[dict[str, object]] | None = None) -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": ["src/demo.py"],
            "verification": {
                "level": "unit",
                "command": command,
                "checks": checks or [],
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


def _validate(
    tmp_path: Path,
    command: str,
    checks: list[dict[str, object]] | None = None,
):
    plan = _plan(command, checks=checks)
    workspace = WorkspaceIndex(tmp_path)
    return validate_filesystem(plan, project_root=tmp_path, workspace=workspace)


def test_missing_file_error(tmp_path):
    issues = _validate(tmp_path, "pytest tests/cli/test_nonexistent.py -q")

    missing_file_issues = [
        issue for issue in issues
        if issue.code == "E_VERIFICATION_TARGET_MISSING_FILE"
    ]
    assert len(missing_file_issues) >= 1
    assert missing_file_issues[0].evidence["missing_path"] == "tests/cli/test_nonexistent.py"


def test_existing_file_no_error(tmp_path):
    test_path = tmp_path / "tests" / "ralph" / "test_ralph_standalone.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    issues = _validate(tmp_path, "pytest tests/ralph/test_ralph_standalone.py -q")

    assert all(issue.code != "E_VERIFICATION_TARGET_MISSING_FILE" for issue in issues)


def test_glob_pattern_skipped(tmp_path):
    issues = _validate(tmp_path, "pytest tests/*.py")

    assert all(issue.code != "E_VERIFICATION_TARGET_MISSING_FILE" for issue in issues)


def test_checks_command_missing_file_error(tmp_path):
    test_path = tmp_path / "tests" / "ralph" / "test_ralph_standalone.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "pytest tests/ralph/test_ralph_standalone.py -q",
        checks=[{
            "name": "missing-check-target",
            "command": "pytest tests/cli/test_nonexistent.py -q",
            "required": True,
        }],
    )

    missing_file_issues = [
        issue for issue in issues
        if issue.code == "E_VERIFICATION_TARGET_MISSING_FILE"
    ]
    assert len(missing_file_issues) >= 1
    assert missing_file_issues[0].evidence["missing_path"] == "tests/cli/test_nonexistent.py"


def test_pytest_k_expression_skipped(tmp_path):
    test_path = tmp_path / "tests" / "ralph" / "test_ralph_standalone.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        'pytest tests/ralph/test_ralph_standalone.py -k "tests/cli/test_nonexistent.py"',
    )

    assert all(issue.code != "E_VERIFICATION_TARGET_MISSING_FILE" for issue in issues)
