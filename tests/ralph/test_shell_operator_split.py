from __future__ import annotations

from pathlib import Path

from cccc.ralph.filesystem_validator import _split_shell_command, validate_filesystem
from cccc.ralph.models import Plan
from cccc.ralph.workspace_index import WorkspaceIndex


def _plan(command: str, claimed_paths: list[str] | None = None) -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": claimed_paths or ["src/demo.py"],
            "verification": {
                "level": "unit",
                "command": command,
                "covers": {"tasks": ["T1"]},
            },
        }],
    })


def _validate(tmp_path: Path, command: str, claimed_paths: list[str] | None = None):
    plan = _plan(command, claimed_paths)
    workspace = WorkspaceIndex(tmp_path)
    return validate_filesystem(plan, project_root=tmp_path, workspace=workspace)


def test_split_shell_command_splits_top_level_and_operator():
    assert _split_shell_command("pytest a.py && pytest b.py") == [
        "pytest a.py",
        "pytest b.py",
    ]


def test_and_command_splits_and_checks_both_pytest_targets(tmp_path):
    test_a = tmp_path / "tests" / "test_a.py"
    test_b = tmp_path / "tests" / "test_b.py"
    test_a.parent.mkdir(parents=True)
    test_a.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    test_b.write_text("def test_b():\n    assert True\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "pytest tests/test_a.py && pytest tests/test_b.py",
        claimed_paths=["tests/test_a.py", "tests/test_b.py"],
    )

    assert issues == []


def test_semicolon_command_splits_and_checks_subcommands(tmp_path):
    test_a = tmp_path / "tests" / "test_a.py"
    test_a.parent.mkdir(parents=True)
    test_a.write_text("def test_a():\n    assert True\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "pytest tests/test_a.py; grep foo bar",
        claimed_paths=["tests/test_a.py"],
    )

    assert [issue.code for issue in issues] == ["W_VERIFICATION_SHAPE_UNKNOWN"]


def test_pipe_command_still_skips_with_complex_shell_hint(tmp_path):
    issues = _validate(tmp_path, "pytest a.py | grep PASS")

    assert [issue.code for issue in issues] == ["W_VERIFICATION_COMPLEX_SHELL_SKIPPED"]


def test_or_command_still_skips_with_complex_shell_hint(tmp_path):
    issues = _validate(tmp_path, "pytest a.py || true")

    assert [issue.code for issue in issues] == ["W_VERIFICATION_COMPLEX_SHELL_SKIPPED"]


def test_pytest_node_id_with_and_text_does_not_trigger_shell_detection(tmp_path):
    test_path = tmp_path / "tests" / "test_foo.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_bar_and_stuff():\n    assert True\n", encoding="utf-8")

    issues = _validate(
        tmp_path,
        "pytest tests/test_foo.py::test_bar_and_stuff",
        claimed_paths=["tests/test_foo.py"],
    )

    assert issues == []


def test_python_c_semicolon_inside_quotes_is_not_split(tmp_path):
    command = 'python -c "import sys; print(1)"'

    issues = _validate(tmp_path, command)

    assert _split_shell_command(command) is None
    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTHON_IMPORT_OPAQUE"]


def test_python_c_and_inside_quotes_is_not_split(tmp_path):
    command = 'python -c "foo && bar"'

    issues = _validate(tmp_path, command)

    assert _split_shell_command(command) is None
    assert [issue.code for issue in issues] == ["W_VERIFICATION_PYTHON_SNIPPET_INVALID"]
