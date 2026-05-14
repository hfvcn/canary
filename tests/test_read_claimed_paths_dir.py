from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman import ralph_service as service_module
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph import core as core_module


def _write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_both(project_root: Path, claimed_paths: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    task_ref = TaskRef(id="T-dir", title="directory task", claimed_paths=claimed_paths)
    service = RalphService(project_root=project_root, group_id="test-group")
    service_result = service._read_claimed_paths(task_ref)
    core_result = core_module._read_claimed_paths(claimed_paths, project_root)
    return service_result, core_result


def test_directory_claimed_path_expands_to_sorted_source_files(tmp_path: Path) -> None:
    _write_file(tmp_path / "src/app/b.ts", "ts")
    _write_file(tmp_path / "src/app/a.py", "py")
    _write_file(tmp_path / "src/app/nested/c.tsx", "tsx")
    _write_file(tmp_path / "src/app/nested/d.js", "js")
    _write_file(tmp_path / "src/app/nested/e.jsx", "jsx")
    _write_file(tmp_path / "src/app/nested/ignored.css", "css")

    service_result, core_result = _read_both(tmp_path, ["src/app"])

    expected = {
        "src/app/a.py": "py",
        "src/app/b.ts": "ts",
        "src/app/nested/c.tsx": "tsx",
        "src/app/nested/d.js": "js",
        "src/app/nested/e.jsx": "jsx",
    }
    assert service_result == expected
    assert core_result == expected
    assert "src/app" not in service_result
    assert list(service_result) == sorted(expected)


def test_directory_without_source_files_is_marked_not_found(tmp_path: Path) -> None:
    _write_file(tmp_path / "src/docs/readme.md", "docs")

    service_result, core_result = _read_both(
        tmp_path,
        ["src/docs", "src/missing"],
    )

    expected = {
        "src/docs": "<file not found>",
        "src/missing": "<file not found>",
    }
    assert service_result == expected
    assert core_result == expected


def test_directory_expansion_respects_total_context_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_file(tmp_path / "src/limited/a.py", "a" * 30)
    _write_file(tmp_path / "src/limited/b.py", "b" * 30)
    monkeypatch.setattr(service_module, "SOURCE_CONTEXT_MAX_BYTES", 10)
    monkeypatch.setattr(service_module, "SOURCE_FILE_MAX_BYTES", 100)
    monkeypatch.setattr(core_module, "_SOURCE_CONTEXT_MAX_BYTES", 10)
    monkeypatch.setattr(core_module, "_SOURCE_FILE_MAX_BYTES", 100)

    service_result, core_result = _read_both(tmp_path, ["src/limited"])

    expected = {"src/limited/a.py": "a" * 10 + "\n... (truncated)"}
    assert service_result == expected
    assert core_result == expected
