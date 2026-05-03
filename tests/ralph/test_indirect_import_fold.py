from __future__ import annotations

from pathlib import Path

from cccc.ralph.filesystem_validator import validate_filesystem
from cccc.ralph.models import Plan
from cccc.ralph.workspace_index import WorkspaceIndex


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _validate(tmp_path: Path, source_count: int):
    _write(tmp_path / "tests" / "test_smoke.py", "def test_smoke():\n    assert True\n")
    claimed_paths: list[str] = []
    for index in range(source_count):
        source_name = f"foo_{index}"
        claimed_paths.append(f"src/{source_name}.py")
        _write(tmp_path / "src" / f"{source_name}.py", f"VALUE_{index} = {index}\n")
        _write(
            tmp_path / "tests" / f"test_group_{index}.py",
            f"from {source_name} import VALUE_{index}\n",
        )

    plan = Plan.model_validate({
        "tasks": [{
            "id": "T1",
            "claimed_paths": claimed_paths,
            "verification": {
                "level": "unit",
                "command": "pytest tests/test_smoke.py -q",
                "covers": {"tasks": ["T1"]},
            },
        }]
    })
    workspace = WorkspaceIndex(tmp_path)
    return validate_filesystem(plan, project_root=tmp_path, workspace=workspace)


def test_indirect_import_hints_are_folded_at_threshold(tmp_path: Path) -> None:
    issues = _validate(tmp_path, source_count=10)

    indirect = [issue for issue in issues if issue.code == "W_INDIRECT_TEST_IMPORT"]
    assert len(indirect) == 1
    assert indirect[0].severity == "hint"
    assert indirect[0].evidence["total_hints"] == 10
    assert indirect[0].evidence["samples"] == [
        {"source_path": f"src/foo_{index}.py", "uncovered_tests": [f"tests/test_group_{index}.py"]}
        for index in range(5)
    ]
    assert "10 indirect test import hint(s)" in indirect[0].message


def test_indirect_import_hints_remain_unfolded_below_threshold(tmp_path: Path) -> None:
    issues = _validate(tmp_path, source_count=9)

    indirect = [issue for issue in issues if issue.code == "W_INDIRECT_TEST_IMPORT"]
    assert len(indirect) == 9
    assert {issue.evidence["source_path"] for issue in indirect} == {
        f"src/foo_{index}.py" for index in range(9)
    }
