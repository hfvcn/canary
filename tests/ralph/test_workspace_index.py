from __future__ import annotations

from pathlib import Path

from cccc.ralph.models import Plan, TaskSpec
from cccc.ralph.workspace_index import WorkspaceIndex


def test_path_exists_true(tmp_path):
    file_path = tmp_path / "src" / "demo.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("value = 1\n", encoding="utf-8")

    workspace = WorkspaceIndex(tmp_path)

    assert workspace.path_exists("src/demo.py") is True


def test_path_exists_false(tmp_path):
    workspace = WorkspaceIndex(tmp_path)

    assert workspace.path_exists("missing.py") is False


def test_path_exists_rejects_traversal(tmp_path):
    outside = tmp_path.parent / "escape.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    workspace = WorkspaceIndex(tmp_path)

    assert workspace.path_exists("../escape.py") is False


def test_path_exists_cached(tmp_path):
    file_path = tmp_path / "cached.py"
    file_path.write_text("value = 1\n", encoding="utf-8")
    workspace = WorkspaceIndex(tmp_path)

    assert workspace.path_exists("cached.py") is True
    file_path.unlink()

    assert workspace.path_exists("cached.py") is False


def test_resolve_module_local():
    project_root = Path(__file__).resolve().parents[2]
    workspace = WorkspaceIndex(project_root)

    resolved = workspace.resolve_module("cccc.ralph.validator")

    assert resolved == project_root / "src" / "cccc" / "ralph" / "validator.py"


def test_resolve_module_stdlib():
    project_root = Path(__file__).resolve().parents[2]
    workspace = WorkspaceIndex(project_root)

    assert workspace.resolve_module("os.path") is None
    assert workspace.is_stdlib_or_thirdparty("os.path") is True


def test_resolve_module_nonexistent(tmp_path):
    workspace = WorkspaceIndex(tmp_path)

    assert workspace.resolve_module("missing.package.module") is None
    assert workspace.is_stdlib_or_thirdparty("missing.package.module") is False


def test_ast_parse_valid(tmp_path):
    file_path = tmp_path / "module.py"
    file_path.write_text("answer = 42\n", encoding="utf-8")
    workspace = WorkspaceIndex(tmp_path)

    parsed = workspace.ast_parse("module.py")

    assert parsed is not None
    assert parsed.body[0].__class__.__name__ == "Assign"


def test_ast_parse_syntax_error(tmp_path):
    file_path = tmp_path / "broken.py"
    file_path.write_text("def broken(:\n", encoding="utf-8")
    workspace = WorkspaceIndex(tmp_path)

    assert workspace.ast_parse("broken.py") is None


def test_ast_parse_rejects_traversal(tmp_path):
    outside = tmp_path.parent / "escape.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    workspace = WorkspaceIndex(tmp_path)

    assert workspace.ast_parse("../escape.py") is None


def test_projected_paths_with_deps():
    plan = Plan(tasks=[
        TaskSpec(id="T1", claimed_paths=["src/a.py"]),
        TaskSpec(id="T2", depends_on=["T1"], claimed_paths=["src/b.py"]),
        TaskSpec(id="T3", depends_on=["T2"], claimed_paths=["tests/test_b.py"]),
    ])
    project_root = Path(__file__).resolve().parents[2]
    workspace = WorkspaceIndex(project_root)

    projected = workspace.projected_paths(plan, "T3")

    assert projected == {"src/a.py", "src/b.py", "tests/test_b.py"}


def test_is_covered_by_projected_directory(tmp_path):
    workspace = WorkspaceIndex(tmp_path)
    projected = {"src/cccc", "tests/ralph/test_workspace_index.py"}

    assert workspace.is_covered_by_projected("src/cccc/ralph/validator.py", projected) is True
    assert workspace.is_covered_by_projected("tests/ralph/test_workspace_index.py", projected) is True
    assert workspace.is_covered_by_projected("docs/readme.md", projected) is False
