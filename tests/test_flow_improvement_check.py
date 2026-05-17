from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_improvement_check import _check_improvement_register


TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
CURRENT_VERSION = "v38"


def test_diff_with_current_version_marker_passes(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, f"base\n{CURRENT_VERSION} fixed FL-6\n")

    result = _check_improvement_register(_state(repo))

    assert result.passed
    assert _detail_passed(result.details, "short tracker current marker")
    assert _detail_passed(result.details, "full tracker current marker")


def test_diff_with_only_old_additions_without_version_fails(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, "base\nold uncommitted tracker note\n")

    result = _check_improvement_register(_state(repo))

    assert not result.passed
    assert not _detail_passed(result.details, "short tracker current marker")
    assert not _detail_passed(result.details, "full tracker current marker")


def test_no_diff_fails(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)

    result = _check_improvement_register(_state(repo))

    assert not result.passed
    assert not _detail_passed(result.details, "short tracker additions")
    assert not _detail_passed(result.details, "full tracker additions")


def _repo_with_trackers(repo: Path) -> Path:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write_tracker_pair(repo, "base\n")
    _git(repo, "add", str(TRACKER_SHORT), str(TRACKER_FULL))
    _git(repo, "commit", "-m", "init tracker")
    return repo


def _write_tracker_pair(repo: Path, content: str) -> None:
    short_path = repo / TRACKER_SHORT
    full_path = repo / TRACKER_FULL
    short_path.parent.mkdir(parents=True, exist_ok=True)
    short_path.write_text(content, encoding="utf-8")
    full_path.write_text(content, encoding="utf-8")


def _state(repo: Path) -> FlowState:
    return FlowState(
        flow_type="e2e",
        workspace=str(repo),
        started_at="2026-05-17T00:00:00Z",
        current_step=6,
        params={"cccc_root": str(repo), "tracker": str(TRACKER_SHORT)},
        steps_completed=[],
        steps_failed={},
        version=CURRENT_VERSION,
    )


def _detail_passed(details: list[dict], check: str) -> bool:
    return any(detail["check"] == check and detail["passed"] for detail in details)


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
