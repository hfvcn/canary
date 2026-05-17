from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from cccc.ralph.flow_engine import FlowEngine
from cccc.ralph.flow_engine import FlowState
from cccc.ralph.flow_steps_e2e import E2E_STEPS, _check_env_prepare, _check_improvement_register


def test_e2e_flow_starts(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)

    instruction = engine.start("e2e")

    assert (tmp_path / ".ralph-flow" / "state.json").is_file()
    assert (tmp_path / ".ralph-flow" / "step-0-code-verify").is_dir()
    assert "Step 0/7" in instruction
    assert E2E_STEPS[1].instruction_text == "Step-1 checks workspace and copies docs from cccc_root if needed."
    assert engine.state is not None
    assert engine.state.flow_type == "e2e"
    assert engine.state.current_step == 0


def test_e2e_step_0_code_verify(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("e2e")
    state = engine.state
    assert state is not None

    result = E2E_STEPS[0].check_fn(state)

    assert result is not None
    assert isinstance(result.passed, bool)
    assert result.details


def test_e2e_codex_review_requires_two_files(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("e2e")
    state = engine.state
    assert state is not None
    review_dir = tmp_path / ".ralph-flow" / "step-4-review"
    evaluation = tmp_path / "WORKFLOW_EVALUATION.md"
    evaluation.write_text("x" * 501, encoding="utf-8")
    _write_codex_output(review_dir / "one.json")

    one_file_result = E2E_STEPS[4].check_fn(state)

    assert one_file_result is not None
    assert not one_file_result.passed
    assert any(detail["check"] == "codex output count" for detail in one_file_result.details)

    _write_codex_output(review_dir / "two.json")
    two_file_result = E2E_STEPS[4].check_fn(state)

    assert two_file_result is not None
    assert two_file_result.passed


def test_check_env_prepare_copies_docs_and_passes_when_docs_exist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cccc_root = tmp_path / "cccc-root"
    source_docs = cccc_root / "docs"
    source_docs.mkdir(parents=True)
    (source_docs / "guide.md").write_text("hello", encoding="utf-8")
    state = FlowState(
        flow_type="e2e",
        workspace=str(workspace),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=1,
        params={"cccc_root": str(cccc_root)},
        steps_completed=[],
        steps_failed={},
    )

    copied_result = _check_env_prepare(state)

    assert copied_result.passed
    assert (workspace / "docs" / "guide.md").read_text(encoding="utf-8") == "hello"
    assert any(detail["check"] == "copy docs" and detail["passed"] for detail in copied_result.details)

    existing_result = _check_env_prepare(state)

    assert existing_result.passed
    assert any(detail["check"] == "workspace/docs exists" and detail["passed"] for detail in existing_result.details)
    assert all(detail["check"] != "copy docs" for detail in existing_result.details)


def test_check_improvement_register_detects_tracker_additions(tmp_path: Path) -> None:
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    _init_git_repo(tmp_path)
    tracker_short_path = tmp_path / tracker_short
    tracker_full_path = tmp_path / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    tracker_short_path.write_text("base\n", encoding="utf-8")
    tracker_full_path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", str(tracker_short))
    _git(tmp_path, "add", str(tracker_full))
    _git(tmp_path, "commit", "-m", "init tracker")
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )

    no_change_result = _check_improvement_register(state)

    assert not no_change_result.passed

    tracker_short_path.write_text("base\nv37 added short\n", encoding="utf-8")

    only_short_result = _check_improvement_register(state)

    assert not only_short_result.passed

    tracker_full_path.write_text("base\nv37 added full\n", encoding="utf-8")

    both_result = _check_improvement_register(state)

    assert both_result.passed
    assert any(d["check"] == "short tracker additions" and d["passed"] for d in both_result.details)
    assert any(d["check"] == "full tracker additions" and d["passed"] for d in both_result.details)


def test_check_improvement_register_requires_version_marker(tmp_path: Path) -> None:
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    _init_git_repo(tmp_path)
    tracker_short_path = tmp_path / tracker_short
    tracker_full_path = tmp_path / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    tracker_short_path.write_text("base\n", encoding="utf-8")
    tracker_full_path.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", str(tracker_short))
    _git(tmp_path, "add", str(tracker_full))
    _git(tmp_path, "commit", "-m", "init tracker")
    state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )

    tracker_short_path.write_text("base\nadded short\n", encoding="utf-8")
    tracker_full_path.write_text("base\nadded full\n", encoding="utf-8")
    no_marker_result = _check_improvement_register(state)

    assert not no_marker_result.passed

    tracker_short_path.write_text("base\nv37 added short\n", encoding="utf-8")
    tracker_full_path.write_text("base\nv37 added full\n", encoding="utf-8")
    marker_result = _check_improvement_register(state)

    assert marker_result.passed

    version_state = FlowState(
        flow_type="e2e",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(tmp_path), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )
    tracker_short_path.write_text("base\nv36 added short\n", encoding="utf-8")
    tracker_full_path.write_text("base\nv36 added full\n", encoding="utf-8")
    missing_version_result = _check_improvement_register(version_state)

    assert not missing_version_result.passed


def test_check_improvement_register_archive_advisory(tmp_path: Path) -> None:
    positive_result = _run_archive_advisory_case(
        tmp_path / "positive",
        "#### FL-6\nshort remnant\n#### RL-26\nshort remnant\n",
    )

    detail = next(
        d for d in positive_result.details if d["check"] == "short tracker archive advisory"
    )
    assert detail["passed"]
    assert "FL-6" in detail["message"]
    assert "RL-26" in detail["message"]

    negative_result = _run_archive_advisory_case(tmp_path / "negative", "short body\n")

    assert all(d["check"] != "short tracker archive advisory" for d in negative_result.details)


def test_flow_cli_help() -> None:
    result = subprocess.run(["ralph", "flow", "--help"], capture_output=True, text=True)

    assert result.returncode == 0
    assert "start" in result.stdout
    assert "next" in result.stdout
    assert "status" in result.stdout


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _run_archive_advisory_case(repo: Path, short_body: str):
    tracker_short = Path("todo/issues-ralph.md")
    tracker_full = Path("todo/issues-ralph-full.md")
    repo.mkdir()
    _init_git_repo(repo)
    tracker_short_path = repo / tracker_short
    tracker_full_path = repo / tracker_full
    tracker_short_path.parent.mkdir(parents=True)
    baseline_header = "> 已完成（v36 修复）：RO-1\n"
    completed_header = "> 已完成（v37 修复）：FL-6, RL-26\n"
    tracker_short_path.write_text(f"{baseline_header}---\nbase\n", encoding="utf-8")
    tracker_full_path.write_text(f"{baseline_header}---\nbase\n", encoding="utf-8")
    _git(repo, "add", str(tracker_short))
    _git(repo, "add", str(tracker_full))
    _git(repo, "commit", "-m", "init tracker")
    tracker_short_path.write_text(
        f"{baseline_header}{completed_header}---\n{short_body}",
        encoding="utf-8",
    )
    tracker_full_path.write_text(
        f"{baseline_header}{completed_header}---\nfull v37\n",
        encoding="utf-8",
    )
    state = FlowState(
        flow_type="e2e",
        workspace=str(repo),
        started_at="2026-01-01T00:00:00+00:00",
        current_step=6,
        params={"cccc_root": str(repo), "tracker": str(tracker_short), "version": "v37"},
        steps_completed=[],
        steps_failed={},
    )
    return _check_improvement_register(state)


def _write_codex_output(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 501,
            }
        ),
        encoding="utf-8",
    )
