from __future__ import annotations

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.ralph_service import (
    WORKER_SCOPE_WARNING_CODE,
    RalphService,
)
from cccc.kernel.claimed_paths import normalize_path, paths_overlap


def _make_task(claimed_paths: list[str]) -> TaskRef:
    return TaskRef(
        id="T1",
        title="scope-check",
        claimed_paths=claimed_paths,
    )


def test_same_directory_init_file_is_exempt(tmp_path) -> None:
    service = RalphService(tmp_path, "group-test")

    warnings = service._build_scope_warnings(
        ["src/x/__init__.py"],
        _make_task(["src/x/foo.py"]),
    )

    assert warnings == []


def test_conftest_is_exempt_outside_claimed_paths(tmp_path) -> None:
    service = RalphService(tmp_path, "group-test")

    warnings = service._build_scope_warnings(
        ["tests/conftest.py"],
        _make_task(["src/x/foo.py"]),
    )

    assert warnings == []


def test_non_exempt_file_outside_claimed_paths_warns(tmp_path) -> None:
    service = RalphService(tmp_path, "group-test")

    warnings = service._build_scope_warnings(
        ["src/y/bar.py"],
        _make_task(["src/x/foo.py"]),
    )

    assert warnings == [
        f"{WORKER_SCOPE_WARNING_CODE}: modified 1 file(s) "
        "outside claimed_paths: src/y/bar.py"
    ]


def test_paths_overlap_behavior_is_unchanged() -> None:
    claimed_file = normalize_path("src/x/foo.py")

    assert paths_overlap(claimed_file, normalize_path("src/x/__init__.py")) is False
    assert paths_overlap(claimed_file, normalize_path("src/x/")) is True
