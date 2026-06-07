from __future__ import annotations

import builtins
import dataclasses
import hashlib
import hmac
import json
import subprocess
import uuid
from pathlib import Path

import pytest

import cccc.ralph.flow_engine as flow_engine_module
from cccc.ralph.flow_engine import (
    CODEX_EXECUTION_MAX_LAG_SECONDS,
    FlowEngine,
    FlowState,
    _build_solve_steps,
    _check_diff_source_correlation,
    _check_codex_mtime_lag,
    _collect_codex_changed_files,
    validate_codex_output,
)


def test_start_creates_state(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)

    instruction = engine.start("solve", test_cmd="pytest")

    assert (tmp_path / ".ralph-flow" / "state.json").is_file()
    assert (tmp_path / ".ralph-flow" / "step-1-understand").is_dir()
    assert "Step 1/7" in instruction
    assert engine.state is not None
    assert engine.state.current_step == 1


def test_start_resolves_cccc_root_to_absolute_path(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo-root"
    workspace = tmp_path / "workspace"
    repo_root.mkdir()
    workspace.mkdir()
    monkeypatch.chdir(repo_root)
    engine = FlowEngine(workspace)

    engine.start("e2e", cccc_root=".")

    state = engine.state
    assert state is not None
    assert state.params["cccc_root"] == str(repo_root.resolve())


def test_solve_review_instruction_mentions_codex_bridge_parallel_and_skill() -> None:
    steps = _build_solve_steps()
    instruction = steps[2].instruction_text

    assert "codex_bridge.py" in instruction
    assert "run_in_background" in instruction
    assert "parallel" in instruction


def test_secret_preflight_pass(tmp_path: Path, monkeypatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_signed_codex_output(
        review_dir / "review.json",
        secret=secret,
        agent_messages="x" * 250,
    )
    state = FlowState(
        flow_type="solve",
        workspace=str(tmp_path),
        started_at="2026-05-24T00:00:00Z",
        current_step=3,
        params={},
        steps_completed=[],
        steps_failed={},
    )

    step = _build_solve_steps()[2]
    assert step.check_fn is not None

    result = step.check_fn(state)

    assert result.passed
    assert all(detail["passed"] for detail in result.details)


def test_secret_preflight_fail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CODEX_BRIDGE_SECRET", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("OTHER_KEY=value\n", encoding="utf-8")
    state = FlowState(
        flow_type="solve",
        workspace=str(workspace),
        started_at="2026-05-24T00:00:00Z",
        current_step=3,
        params={},
        steps_completed=[],
        steps_failed={},
    )

    step = _build_solve_steps()[2]
    assert step.check_fn is not None

    result = step.check_fn(state)

    assert not result.passed
    assert result.details == [
        {
            "check": "secret_preflight",
            "passed": False,
            "message": "CODEX_BRIDGE_SECRET not configured — export CODEX_BRIDGE_SECRET=xxx or add to .env",
        }
    ]


def test_sandbox_write_in_step3() -> None:
    instruction = _build_solve_steps()[2].instruction_text

    assert "workspace-write" in instruction
    assert "read-only" not in instruction


def test_solve_gap_instruction_mentions_codex_findings_and_heading_requirement() -> None:
    steps = _build_solve_steps()
    instruction = steps[3].instruction_text

    assert "Analyze step-3 Codex review findings" in instruction
    assert "`####`" in instruction


def _write_understand_output(workspace: Path) -> None:
    understand_dir = workspace / ".ralph-flow" / "step-1-understand"
    understand_dir.mkdir(parents=True, exist_ok=True)
    (understand_dir / "understand.md").write_text(
        "原始症状：启动失败\n活跃路径假设：entrypoint 经过 daemon bootstrap\n待证明：behavior change 已生效\n",
        encoding="utf-8",
    )


def test_next_advances_on_pass(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    _write_understand_output(tmp_path)

    instruction = engine.next()

    assert "Step 2/7" in instruction
    assert engine.state is not None
    assert engine.state.current_step == 2
    assert engine.state.steps_completed == [1]


def test_next_stays_on_fail(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    _write_understand_output(tmp_path)
    engine.next()

    instruction = engine.next()

    state = engine.state
    assert state is not None
    assert state.current_step == 2
    assert state.steps_failed["2"]["attempts"] == 1
    assert "plan.yaml exists" in instruction
    assert "Step 2/7" in instruction


def test_state_sig_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret")
    engine = FlowEngine(tmp_path)

    engine.start("solve", test_cmd="pytest")

    payload = _read_state_json(tmp_path / ".ralph-flow" / "state.json")
    state = engine.state
    assert payload["_state_sig"]
    assert state is not None
    assert state._state_sig == payload["_state_sig"]


def test_state_sig_tamper_current_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret")
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    state_path = tmp_path / ".ralph-flow" / "state.json"
    payload = _read_state_json(state_path)
    payload["current_step"] = 99
    _write_state_json(state_path, payload)

    with pytest.raises(ValueError, match="state.json integrity check failed"):
        engine._load_state()


def test_state_sig_tamper_params(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret")
    engine = FlowEngine(tmp_path)
    engine.start("solve", test_cmd="pytest")
    state_path = tmp_path / ".ralph-flow" / "state.json"
    payload = _read_state_json(state_path)
    payload["params"]["test_cmd"] = "echo hacked"
    _write_state_json(state_path, payload)

    with pytest.raises(ValueError, match="state.json integrity check failed"):
        engine._load_state()


def test_state_sig_missing_backward_compat(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret")
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    state_path = tmp_path / ".ralph-flow" / "state.json"
    payload = _read_state_json(state_path)
    payload.pop("_state_sig")
    _write_state_json(state_path, payload)

    state = engine.state
    assert state is not None
    assert state._state_sig is None


def test_state_sig_no_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CODEX_BRIDGE_SECRET", raising=False)
    engine = FlowEngine(tmp_path)

    engine.start("solve")

    payload = _read_state_json(tmp_path / ".ralph-flow" / "state.json")
    state = engine.state
    assert payload["_state_sig"] is None
    assert state is not None
    assert state._state_sig is None


def test_codex_validation_rejects_missing_sig(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret")
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    (output_dir / "bad.json").write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 250,
            }
        ),
        encoding="utf-8",
    )

    result = validate_codex_output(output_dir)

    assert not result.passed
    assert any(not detail["passed"] for detail in result.details)


def test_check_regression_run_reports_non_importerror_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = FlowState(
        flow_type="solve",
        workspace=str(tmp_path),
        started_at="2026-05-24T00:00:00Z",
        current_step=7,
        params={},
        steps_completed=[],
        steps_failed={},
    )
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "regression_scenarios" and level == 1:
            raise SyntaxError("broken module")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = flow_engine_module._check_regression_run(state)

    assert result.passed is False
    assert result.details == [
        {
            "check": "regression import",
            "passed": False,
            "message": "cannot import: broken module",
        }
    ]


def test_codex_validation_accepts_valid_hmac_signature(tmp_path: Path, monkeypatch) -> None:
    secret = "test-secret"
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", secret)
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    _write_signed_codex_output(output_dir / "ok.json", secret=secret, agent_messages="x" * 250)

    result = validate_codex_output(output_dir)

    assert result.passed
    assert all(detail["passed"] for detail in result.details)


def test_codex_validation_fails_when_secret_not_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("CODEX_BRIDGE_SECRET", raising=False)
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    _write_signed_codex_output(
        output_dir / "ok.json",
        secret="bridge-only-secret",
        agent_messages="x" * 250,
    )

    result = validate_codex_output(output_dir)

    assert not result.passed
    assert any(
        "not configured" in detail["message"]
        for detail in result.details
        if "authenticity" in detail["check"]
    )


def test_codex_validation_rejects_invalid_sig_when_secret_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "real-secret")
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    (output_dir / "bad.json").write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 250,
            }
        ),
        encoding="utf-8",
    )

    result = validate_codex_output(output_dir)

    assert not result.passed
    assert any(
        detail["check"] == "bad.json: authenticity" and "missing _sig" in detail["message"]
        for detail in result.details
    )


def test_codex_mtime_lag_normal(tmp_path: Path) -> None:
    """JSON created shortly after step dir -> no advisory."""
    step_dir = tmp_path / "step-5-execute"
    step_dir.mkdir()
    json_file = step_dir / "t1.json"
    json_file.write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 300,
            }
        ),
        encoding="utf-8",
    )

    details = _check_codex_mtime_lag(step_dir)

    assert len(details) == 0


def test_codex_mtime_lag_overwrite(tmp_path: Path) -> None:
    """JSON modified way after step dir created -> advisory warning."""
    import os

    step_dir = tmp_path / "step-5-execute"
    step_dir.mkdir()
    json_file = step_dir / "t1.json"
    json_file.write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 300,
            }
        ),
        encoding="utf-8",
    )
    future_time = os.path.getctime(str(step_dir)) + CODEX_EXECUTION_MAX_LAG_SECONDS + 100
    os.utime(str(json_file), (future_time, future_time))

    details = _check_codex_mtime_lag(step_dir)

    assert len(details) == 1
    assert "possible manual override" in details[0]["message"]
    assert details[0]["passed"] is True


def test_collect_codex_changed_files_present(tmp_path: Path) -> None:
    """Extract changed_files from Codex JSON."""
    step_dir = tmp_path / "step-5-execute"
    step_dir.mkdir()
    (step_dir / "t1.json").write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 300,
                "changed_files": ["src/foo.py", "src/bar.py"],
            }
        ),
        encoding="utf-8",
    )

    result = _collect_codex_changed_files(step_dir)

    assert result == {"src/foo.py", "src/bar.py"}


def test_collect_codex_changed_files_missing(tmp_path: Path) -> None:
    """No changed_files field -> returns None."""
    step_dir = tmp_path / "step-5-execute"
    step_dir.mkdir()
    (step_dir / "t1.json").write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 300,
            }
        ),
        encoding="utf-8",
    )

    result = _collect_codex_changed_files(step_dir)

    assert result is None


def test_diff_source_correlation_no_changed_files(tmp_path: Path) -> None:
    """No changed_files -> advisory skip."""
    state = FlowState(
        flow_type="solve",
        workspace=str(tmp_path),
        started_at="2026-01-01T00:00:00Z",
        current_step=5,
        params={},
        steps_completed=[],
        steps_failed={},
    )
    step_dir = tmp_path / ".ralph-flow" / "step-5-execute"
    step_dir.mkdir(parents=True)
    (step_dir / "t1.json").write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 300,
            }
        ),
        encoding="utf-8",
    )

    details = _check_diff_source_correlation(state)

    assert len(details) == 1
    assert "no changed_files" in details[0]["message"]


def test_check_gap_record_rejects_marker_without_heading(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")
    tracker.write_text("base\nv41 代码修复\n", encoding="utf-8")

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert not result.passed
    assert any(detail["check"] == "tracker new findings" and not detail["passed"] for detail in result.details)


def test_check_gap_record_requires_review_keyword_cross_reference(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")
    tracker.write_text("base\nv41 代码修复\n#### FL-21\nmanual placeholder only\n", encoding="utf-8")

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert not result.passed
    assert any(
        detail["check"] == "tracker references step-3 review findings" and not detail["passed"]
        for detail in result.details
    )


def test_check_gap_record_accepts_real_finding_heading_with_review_keyword(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")
    tracker.write_text(
        "base\nv41 代码修复\n#### FL-21\nrefresh token misuse needs verify gate coverage\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert result.passed


def test_gap_record_requires_capability_keywords(tmp_path: Path, monkeypatch) -> None:
    """FL-23: gap recordings without capability keywords should fail."""
    monkeypatch.chdir(tmp_path)
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-23\nrefresh token misuse remained after plan update\n",
        encoding="utf-8",
    )

    failed = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert not failed.passed
    assert any(
        detail["check"] == "tracker capability gap content" and not detail["passed"]
        for detail in failed.details
    )

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-23\nrefresh token misuse needs validate rule coverage in tracker checks\n",
        encoding="utf-8",
    )

    passed = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert passed.passed


def test_gap_record_accepts_main_path_keywords_with_evidence(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-66\n"
        "refresh token misuse remains on main path import chain because orchestrator uses "
        "from cccc.ralph.flow_engine import FlowEngine before register 调用\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert result.passed
    assert any(
        detail["check"] == "main path integration evidence" and detail["passed"]
        for detail in result.details
    )


def test_gap_record_requires_main_path_evidence_keywords(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-66\n"
        "refresh token misuse remains on main path and call path around the orchestrator branch\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert not result.passed
    assert any(
        detail["check"] == "main path integration evidence" and not detail["passed"]
        for detail in result.details
    )


def test_gap_record_existing_capability_keywords_still_pass(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-23\n"
        "refresh token misuse needs detect warning rule coverage in tracker checks\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert result.passed
    assert any(
        detail["check"] == "tracker capability gap content" and detail["passed"]
        for detail in result.details
    )


def test_gap_structure_complete_record_passes(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-23\n"
        "issue_id: FL-23\n"
        "detection_type: validate\n"
        "description: refresh token misuse needs validate rule coverage in tracker checks\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert result.passed
    assert any(
        detail["check"] == "tracker gap record structure"
        and "issue_id, detection_type, and description" in detail["message"]
        for detail in result.details
    )


def test_gap_structure_missing_issue_id_passes_with_suggestion(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-23\n"
        "detection_type: validate\n"
        "description: refresh token misuse needs validate rule coverage in tracker checks\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert result.passed
    assert any(
        detail["check"] == "tracker gap record structure"
        and "issue_id" in detail["message"]
        for detail in result.details
    )


def test_gap_structure_without_capability_keywords_fails(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")

    tracker.write_text(
        "base\nv41 代码修复\n#### FL-23\n"
        "issue_id: FL-23\n"
        "description: refresh token misuse remained after manual triage and follow-up notes\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert not result.passed
    assert any(
        detail["check"] == "tracker capability gap content" and not detail["passed"]
        for detail in result.details
    )
    assert not any(detail["check"] == "tracker gap record structure" for detail in result.details)


def test_archive_content_check_pass(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")
    tracker.write_text(
        "> 日期：2026-05-24\n"
        "> 已完成（v42 代码修复）：FL-19\n"
        "---\n"
        "#### FL-21\n"
        "refresh token misuse needs validate rule coverage\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert result.passed
    assert not any(
        detail["check"] == "tracker archive content (advisory)" and not detail["passed"]
        for detail in result.details
    )


def test_archive_content_check_fail(tmp_path: Path) -> None:
    tracker = _init_solve_tracker_repo(tmp_path)
    review_dir = tmp_path / ".ralph-flow" / "step-3-review"
    review_dir.mkdir(parents=True)
    _write_review_output(review_dir / "review.json", "- refresh token misuse\n- contract drift\n")
    tracker.write_text(
        "> 日期：2026-05-24\n"
        "> 已完成（v42 代码修复）：FL-19\n"
        "---\n"
        "#### FL-19\n"
        "resolved item still present in active tracker body\n"
        "#### FL-21\n"
        "refresh token misuse needs validate rule coverage\n",
        encoding="utf-8",
    )

    result = flow_engine_module._check_gap_record(_solve_gap_state(tmp_path))

    assert not result.passed
    assert any(
        detail["check"] == "short tracker archive blocking"
        and not detail["passed"]
        and detail["message"]
        == "completed-but-not-archived: ['FL-19'] — archive these to full tracker before proceeding"
        for detail in result.details
    )
    assert any(
        detail["check"] == "tracker archive content (advisory)"
        and not detail["passed"]
        and detail["message"]
        == "completed item FL-19 still has active section in tracker (source: header completed marker)"
        for detail in result.details
    )


def test_archive_content_parse_completed_ids() -> None:
    tracker_text = (
        "> 日期：2026-05-24\n"
        "> 已完成（v42 代码修复）：FL-19/RO-12a\n"
        "> 已验证（v42 E2E 确认）：UX-7, AB-9B\n"
        "---\n"
        "#### QQ-77\n"
        "已完成：QQ-77 should not be parsed from the body\n"
    )

    completed_ids = flow_engine_module._parse_completed_ids(tracker_text)

    assert completed_ids == {"FL-19", "RO-12a", "UX-7", "AB-9B"}


def test_completion_removes_flow_dir(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    state = engine.state
    assert state is not None
    engine._save_state(dataclasses.replace(state, current_step=8))

    result = engine.next()

    assert "completed" in result.lower()
    assert not (tmp_path / ".ralph-flow").exists()
    assert engine.state is None


def test_optional_steps_skipped(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    state = engine.state
    assert state is not None
    engine._save_state(dataclasses.replace(state, current_step=4))

    instruction = engine.next()

    state = engine.state
    assert state is not None
    assert state.current_step == 5
    assert state.steps_completed == [4]
    assert "step skipped" in instruction


def _write_signed_codex_output(path: Path, secret: str, agent_messages: str) -> str:
    session_id = str(uuid.uuid4())
    payload = {
        "SESSION_ID": session_id,
        "success": True,
        "agent_messages": agent_messages,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    payload["_sig"] = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return session_id


def _read_state_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_review_output(path: Path, agent_messages: str) -> None:
    path.write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": agent_messages,
                "_sig": "review-sig",
            }
        ),
        encoding="utf-8",
    )


def _init_solve_tracker_repo(repo: Path) -> Path:
    tracker_path = repo / "todo" / "issues-ralph.md"
    tracker_path.parent.mkdir(parents=True)
    tracker_path.write_text("base\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "add", "todo/issues-ralph.md")
    _git(repo, "commit", "-m", "init tracker")
    return tracker_path


def _solve_gap_state(repo: Path) -> FlowState:
    return FlowState(
        flow_type="solve",
        workspace=str(repo),
        started_at="2026-05-19T00:00:00Z",
        current_step=4,
        params={"tracker": "todo/issues-ralph.md"},
        steps_completed=[],
        steps_failed={},
    )


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_codex_validation_rejects_invalid_sig_when_secret_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret")
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    (output_dir / "bad.json").write_text(
        json.dumps(
            {
                "SESSION_ID": str(uuid.uuid4()),
                "success": True,
                "agent_messages": "x" * 250,
                "_sig": "not-a-valid-hmac",
            }
        ),
        encoding="utf-8",
    )

    result = validate_codex_output(output_dir)

    assert not result.passed
    assert any(
        detail["check"] == "bad.json: authenticity" and detail["message"] == "invalid HMAC signature"
        for detail in result.details
    )
