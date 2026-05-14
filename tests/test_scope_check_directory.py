from __future__ import annotations

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.daemon.foreman.workflow_monitor import check_file_overstepping
from cccc.kernel.claimed_paths import normalize_path, paths_overlap


def _make_task(claimed_paths: list[str]) -> TaskRef:
    return TaskRef(
        id="T1",
        title="scope-check",
        claimed_paths=claimed_paths,
    )


def test_scope_warnings_directory_trailing_slash(tmp_path) -> None:
    service = RalphService(tmp_path, "group-test")
    warnings = service._build_scope_warnings(
        ["backend/main.py"],
        _make_task(["backend/"]),
    )

    assert warnings == []


def test_scope_warnings_truly_outside(tmp_path) -> None:
    service = RalphService(tmp_path, "group-test")
    warnings = service._build_scope_warnings(
        ["other/file.py"],
        _make_task(["backend/"]),
    )

    assert len(warnings) == 1
    assert "other/file.py" in warnings[0]


def test_monitor_directory_trailing_slash() -> None:
    alert = check_file_overstepping(
        task_id="T1",
        changed_files=["backend/main.py"],
        claimed_paths=["backend/"],
    )

    assert alert is None


def test_unnormalized_would_fail_without_fix() -> None:
    assert paths_overlap("backend/main.py", "backend/") is False
    assert paths_overlap(
        normalize_path("backend/main.py"),
        normalize_path("backend/"),
    ) is True
