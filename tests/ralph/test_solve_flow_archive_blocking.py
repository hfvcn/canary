from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import cccc.ralph.flow_engine as flow_engine_module
from cccc.ralph.flow_engine import FlowState, _build_solve_steps


TRACKER = Path("todo/issues-ralph.md")
REVIEW_MESSAGE = "- refresh token misuse\n- contract drift\n"


def test_step4_blocks_short_tracker_strikethrough(tmp_path: Path) -> None:
    repo, workspace = _prepare_repo(
        tmp_path,
        baseline_tracker=_tracker_text(body=_baseline_body()),
        current_tracker=_tracker_text(
            body=_baseline_body() + "- ~~FL-19~~ 已归档\n" + _gap_entry("FL-21"),
        ),
    )

    result = _run_step4(repo, workspace)

    assert not result.passed
    assert _has_failed_check(result, "short tracker strikethrough")


def test_step4_blocks_completed_summary_lines_in_body(tmp_path: Path) -> None:
    repo, workspace = _prepare_repo(
        tmp_path,
        baseline_tracker=_tracker_text(body=_baseline_body()),
        current_tracker=_tracker_text(
            body=_baseline_body()
            + "> 已完成（v42 代码修复）：FL-19\n"
            + _gap_entry("FL-21"),
        ),
    )

    result = _run_step4(repo, workspace)

    assert not result.passed
    assert _has_failed_check(result, "short tracker completed summaries")


def test_step4_blocks_completed_items_left_in_short_tracker(tmp_path: Path) -> None:
    repo, workspace = _prepare_repo(
        tmp_path,
        baseline_tracker=_tracker_text(body=_baseline_body()),
        current_tracker=_tracker_text(
            header_lines=("> 日期：2026-05-24", "> 已完成（v42 代码修复）：FL-19"),
            body=(
                _baseline_body()
                + "#### FL-19\n"
                + "resolved item still present in active tracker body\n"
                + _gap_entry("FL-21")
            ),
        ),
    )

    result = _run_step4(repo, workspace)

    assert not result.passed
    assert _has_failed_check(result, "short tracker archive blocking")


def test_step4_passes_with_clean_short_tracker_and_gap_record(tmp_path: Path) -> None:
    repo, workspace = _prepare_repo(
        tmp_path,
        baseline_tracker=_tracker_text(body=_baseline_body()),
        current_tracker=_tracker_text(
            header_lines=("> 日期：2026-05-24", "> 已完成（v42 代码修复）：FL-19"),
            body=_baseline_body() + _gap_entry("FL-21"),
        ),
    )

    result = _run_step4(repo, workspace)

    assert result.passed
    assert not _has_failed_check(result, "short tracker archive blocking")
    assert not _has_failed_check(result, "short tracker strikethrough")
    assert not _has_failed_check(result, "short tracker completed summaries")


def test_step4_ignores_completed_summary_in_tracker_header(tmp_path: Path) -> None:
    header_lines = ("> 日期：2026-05-24", "> 已完成（v41 代码修复）：FL-19")
    repo, workspace = _prepare_repo(
        tmp_path,
        baseline_tracker=_tracker_text(header_lines=header_lines, body=_baseline_body()),
        current_tracker=_tracker_text(
            header_lines=header_lines,
            body=_baseline_body() + _gap_entry("FL-21"),
        ),
    )

    result = _run_step4(repo, workspace)

    assert result.passed
    assert not _has_failed_check(result, "short tracker completed summaries")


def _prepare_repo(tmp_path: Path, baseline_tracker: str, current_tracker: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write_tracker(repo, baseline_tracker)
    _git(repo, "add", str(TRACKER))
    _git(repo, "commit", "-m", "init tracker")
    _write_tracker(repo, current_tracker)
    _write_review_output(workspace / ".ralph-flow" / "step-3-review" / "review.json")
    return repo, workspace


def _run_step4(repo: Path, workspace: Path):
    step = _build_solve_steps()[3]
    assert step.name == "gaps"
    assert step.check_fn is flow_engine_module._check_gap_record
    assert step.check_fn is not None
    return step.check_fn(_state(repo, workspace))


def _state(repo: Path, workspace: Path) -> FlowState:
    workspace.mkdir(parents=True, exist_ok=True)
    return FlowState(
        flow_type="solve",
        workspace=str(workspace),
        started_at="2026-05-24T00:00:00Z",
        current_step=4,
        params={"cccc_root": str(repo), "tracker": str(TRACKER)},
        steps_completed=[],
        steps_failed={},
    )


def _tracker_text(
    *,
    header_lines: tuple[str, ...] = ("> 日期：2026-05-24",),
    body: str,
) -> str:
    header = "\n".join(header_lines)
    return f"{header}\n---\n{body}"


def _baseline_body() -> str:
    return "#### FL-40\nopen issue\n"


def _gap_entry(issue_id: str) -> str:
    return (
        f"#### {issue_id}\n"
        f"issue_id: {issue_id}\n"
        "detection_type: validate\n"
        "description: refresh token misuse needs validate rule coverage.\n"
    )


def _write_tracker(repo: Path, content: str) -> None:
    tracker_path = repo / TRACKER
    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    tracker_path.write_text(content, encoding="utf-8")


def _write_review_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": REVIEW_MESSAGE,
            }
        ),
        encoding="utf-8",
    )


def _has_failed_check(result, check: str) -> bool:
    return any(detail["check"] == check and not detail["passed"] for detail in result.details)


def _git(repo: Path, *args: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
