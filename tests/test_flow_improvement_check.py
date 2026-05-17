from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_improvement_check import _check_improvement_register


TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
CURRENT_VERSION = "v38"
STARTED_AT = "2026-05-17T00:00:00Z"


def test_diff_with_current_version_marker_passes(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, f"base\n{CURRENT_VERSION} fixed FL-6\n")

    result = _check_improvement_register(_state(repo))

    assert result.passed
    assert _detail_passed(result.details, "short tracker current marker")
    assert _detail_passed(result.details, "full tracker current marker")


def test_version_set_rejects_additions_without_current_version_marker(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, "base\nold uncommitted tracker note\n")

    result = _check_improvement_register(_state(repo))

    assert not result.passed
    assert not _detail_passed(result.details, "short tracker current marker")
    assert not _detail_passed(result.details, "full tracker current marker")


def test_version_set_ignores_started_at_marker(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, f"base\n{STARTED_AT} timestamp-only note\n")

    result = _check_improvement_register(_state(repo))

    assert not result.passed
    assert not _detail_passed(result.details, "short tracker current marker")
    assert not _detail_passed(result.details, "full tracker current marker")


def test_without_version_rejects_pre_existing_snapshot_additions(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, "base\nold uncommitted tracker note\n")
    snapshot = _pre_flow_snapshot(repo)

    result = _check_improvement_register(_state(repo, version=None, snapshot=snapshot))

    assert not result.passed
    assert not _detail_passed(result.details, "short tracker current addition")
    assert not _detail_passed(result.details, "full tracker current addition")


def test_without_version_accepts_addition_absent_from_snapshot(tmp_path: Path) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(repo, "base\nold uncommitted tracker note\n")
    snapshot = _pre_flow_snapshot(repo)
    _write_tracker_pair(
        repo,
        "base\nold uncommitted tracker note\nnew current session note\n",
    )

    result = _check_improvement_register(_state(repo, version=None, snapshot=snapshot))

    assert result.passed
    assert _detail_passed(result.details, "short tracker current addition")
    assert _detail_passed(result.details, "full tracker current addition")


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


def _pre_flow_snapshot(repo: Path) -> dict[str, object]:
    return {
        "started_at": STARTED_AT,
        "trackers": {
            str(TRACKER_SHORT): (repo / TRACKER_SHORT).read_text(encoding="utf-8"),
            str(TRACKER_FULL): (repo / TRACKER_FULL).read_text(encoding="utf-8"),
        },
    }


def _state(
    repo: Path,
    *,
    version: str | None = CURRENT_VERSION,
    snapshot: dict[str, object] | None = None,
) -> FlowState:
    params: dict[str, object] = {"cccc_root": str(repo), "tracker": str(TRACKER_SHORT)}
    if version is not None:
        params["version"] = version
    if snapshot is not None:
        params["tracker_pre_flow_snapshot"] = snapshot
    return FlowState(
        flow_type="e2e",
        workspace=str(repo),
        started_at=STARTED_AT,
        current_step=6,
        params=params,
        steps_completed=[],
        steps_failed={},
        version=version,
    )


def _detail_passed(details: list[dict], check: str) -> bool:
    return any(detail["check"] == check and detail["passed"] for detail in details)


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
