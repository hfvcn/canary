from __future__ import annotations

import subprocess
from pathlib import Path

from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_improvement_check import (
    ARCHIVE_ADVISORY_MESSAGE,
    _check_improvement_register,
)

TRACKER_SHORT = Path("todo/issues-ralph.md")
TRACKER_FULL = Path("todo/issues-ralph-full.md")
CURRENT_VERSION = "v38"


def test_completed_header_addition_prints_archive_advisory(tmp_path: Path, capsys) -> None:
    repo = _repo_with_trackers(tmp_path)
    completed_header = f"> 已完成（{CURRENT_VERSION} 代码修复）：FL-7\n"
    _write_tracker_pair(
        repo,
        f"{completed_header}---\n#### FL-7\nshort remnant\n",
        f"{completed_header}---\nfull archive\n",
    )

    result = _check_improvement_register(_state(repo))
    output = capsys.readouterr()

    assert result.passed
    assert ARCHIVE_ADVISORY_MESSAGE in output.out
    assert output.err == ""


def test_without_completed_header_addition_prints_no_archive_advisory(
    tmp_path: Path,
    capsys,
) -> None:
    repo = _repo_with_trackers(tmp_path)
    _write_tracker_pair(
        repo,
        f"> 日期：2026-05-17\n---\n{CURRENT_VERSION} short update\n",
        f"> 日期：2026-05-17\n---\n{CURRENT_VERSION} full update\n",
    )

    result = _check_improvement_register(_state(repo))
    output = capsys.readouterr()

    assert result.passed
    assert ARCHIVE_ADVISORY_MESSAGE not in output.out
    assert output.err == ""


def _repo_with_trackers(repo: Path) -> Path:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write_tracker_pair(
        repo,
        "> 日期：2026-05-17\n---\nbase short\n",
        "> 日期：2026-05-17\n---\nbase full\n",
    )
    _git(repo, "add", str(TRACKER_SHORT), str(TRACKER_FULL))
    _git(repo, "commit", "-m", "init tracker")
    return repo


def _write_tracker_pair(repo: Path, short_content: str, full_content: str) -> None:
    short_path = repo / TRACKER_SHORT
    full_path = repo / TRACKER_FULL
    short_path.parent.mkdir(parents=True, exist_ok=True)
    short_path.write_text(short_content, encoding="utf-8")
    full_path.write_text(full_content, encoding="utf-8")


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


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
