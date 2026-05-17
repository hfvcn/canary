from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

from cccc.ralph.flow_engine import FlowEngine, validate_codex_output


def test_start_creates_state(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)

    instruction = engine.start("solve", test_cmd="pytest")

    assert (tmp_path / ".ralph-flow" / "state.json").is_file()
    assert (tmp_path / ".ralph-flow" / "step-1-understand").is_dir()
    assert "Step 1/6" in instruction
    assert engine.state is not None
    assert engine.state.current_step == 1


def test_next_advances_on_pass(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("solve")

    instruction = engine.next()

    assert "Step 2/6" in instruction
    assert engine.state is not None
    assert engine.state.current_step == 2
    assert engine.state.steps_completed == [1]


def test_next_stays_on_fail(tmp_path: Path) -> None:
    engine = FlowEngine(tmp_path)
    engine.start("solve")
    engine.next()

    instruction = engine.next()

    state = engine.state
    assert state is not None
    assert state.current_step == 2
    assert state.steps_failed["2"]["attempts"] == 1
    assert "plan.yaml exists" in instruction
    assert "Step 2/6" in instruction


def test_codex_validation_rejects_invalid(tmp_path: Path) -> None:
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    (output_dir / "bad.json").write_text(
        json.dumps({"success": True, "agent_messages": "x" * 250}),
        encoding="utf-8",
    )

    result = validate_codex_output(output_dir)

    assert not result.passed
    assert any(not detail["passed"] for detail in result.details)


def test_codex_validation_accepts_valid(tmp_path: Path) -> None:
    output_dir = tmp_path / "codex"
    output_dir.mkdir()
    (output_dir / "ok.json").write_text(
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

    assert result.passed
    assert all(detail["passed"] for detail in result.details)


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
