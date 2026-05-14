"""Regression tests for verification artifact cleanup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from cccc.contracts.v1.ralph_ipc import (
    TaskRef,
    VerificationCheck,
    VerificationCheckSpec,
    VerificationSpec,
)
from cccc.daemon.foreman.ralph_service import RalphService


def _service(project_root: Path) -> RalphService:
    return RalphService(project_root=project_root, group_id="cleanup-test")


def _task_ref(
    *,
    cleanup_patterns: Optional[list[str]] = None,
    claimed_paths: Optional[list[str]] = None,
) -> TaskRef:
    return TaskRef(
        id="T-cleanup",
        claimed_paths=claimed_paths or ["src"],
        verification=VerificationSpec(
            command="true",
            cleanup_patterns=cleanup_patterns,
        ),
    )


def _run_verification(
    service: RalphService,
    task_ref: TaskRef,
    monkeypatch: Any,
) -> None:
    def fake_run_check(**kwargs: Any) -> VerificationCheck:
        return VerificationCheck(name=kwargs["name"], outcome="passed")

    monkeypatch.setattr(service, "_run_verification_check", fake_run_check)
    result = service.verify_completion(
        task_ref.id,
        [],
        workflow_id="wf-cleanup",
        task_ref=task_ref,
    )

    assert result.overall_outcome == "passed"


def test_cleanup_removes_db_files_within_claimed_paths(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    src = tmp_path / "src"
    nested = src / "nested"
    nested.mkdir(parents=True)
    root_db = src / "state.db"
    nested_db = nested / "cache.db"
    root_db.write_text("dirty\n")
    nested_db.write_text("dirty\n")
    service = _service(tmp_path)
    task_ref = _task_ref(cleanup_patterns=["*.db"])

    _run_verification(service, task_ref, monkeypatch)

    assert not root_db.exists()
    assert not nested_db.exists()


def test_cleanup_leaves_files_outside_claimed_paths(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    src = tmp_path / "src"
    other = tmp_path / "other"
    src.mkdir()
    other.mkdir()
    claimed_db = src / "state.db"
    outside_db = other / "state.db"
    claimed_db.write_text("dirty\n")
    outside_db.write_text("must stay\n")
    service = _service(tmp_path)
    task_ref = _task_ref(cleanup_patterns=["*.db"])

    _run_verification(service, task_ref, monkeypatch)

    assert not claimed_db.exists()
    assert outside_db.read_text() == "must stay\n"


def test_default_cleanup_patterns_are_used_when_not_configured(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    src = tmp_path / "src"
    cache_dir = src / "pkg" / "__pycache__"
    pytest_cache = src / ".pytest_cache"
    cache_dir.mkdir(parents=True)
    pytest_cache.mkdir(parents=True)
    db_file = src / "default.db"
    pyc_file = src / "pkg" / "module.pyc"
    cache_file = cache_dir / "module.cpython.pyc"
    db_file.write_text("dirty\n")
    pyc_file.write_text("dirty\n")
    cache_file.write_text("dirty\n")
    (pytest_cache / "README.md").write_text("dirty\n")
    service = _service(tmp_path)
    task_ref = _task_ref()

    _run_verification(service, task_ref, monkeypatch)

    assert not db_file.exists()
    assert not pyc_file.exists()
    assert not cache_dir.exists()
    assert not pytest_cache.exists()


def test_cleanup_runs_before_resolving_verification_specs(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    db_file = src / "state.db"
    db_file.write_text("dirty\n")
    service = _service(tmp_path)
    task_ref = _task_ref(cleanup_patterns=["*.db"])

    def resolve_specs(task: TaskRef) -> list[tuple[VerificationCheckSpec, str]]:
        assert task.id == task_ref.id
        assert not db_file.exists()
        spec = VerificationCheckSpec(name="verification", command="true")
        return [(spec, "true")]

    monkeypatch.setattr(service, "_resolve_verification_specs", resolve_specs)
    _run_verification(service, task_ref, monkeypatch)


def test_cleanup_is_logged(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: Any,
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    db_file = src / "state.db"
    db_file.write_text("dirty\n")
    service = _service(tmp_path)
    task_ref = _task_ref(cleanup_patterns=["*.db"])

    with caplog.at_level(logging.INFO, logger="cccc.daemon.foreman.ralph_service"):
        _run_verification(service, task_ref, monkeypatch)

    messages = [record.message for record in caplog.records]
    assert any("verification cleanup removed artifact" in msg for msg in messages)
    assert any("src/state.db" in msg for msg in messages)
