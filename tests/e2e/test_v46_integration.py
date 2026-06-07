"""Integration tests for v46 fixes: flow HMAC, model selection, scope detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import cccc.ralph.flow_engine as flow_engine_module
from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.ralph_service import RalphService, WORKER_SCOPE_WARNING_CODE
from cccc.daemon.foreman.workflow_monitor import (
    WORKER_EXCEEDED_SCOPE_CODE,
    check_file_overstepping,
)
from cccc.daemon.ops.agent_ops import select_model_for_task
from cccc.ralph.flow_engine import CheckResult, FlowEngine


class TestFlowStateHMACIntegration:
    """FL-32: flow state HMAC integrity across multiple steps."""

    def test_hmac_persists_across_step_transitions(self, tmp_path: Path, monkeypatch) -> None:
        """HMAC stays valid when next() persists new state across steps."""
        monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret-v46")
        engine = FlowEngine(tmp_path)

        engine.start("solve", test_cmd="pytest", tracker="tracker.md")
        start_state = engine._load_state()
        understand_dir = tmp_path / ".ralph-flow" / "step-1-understand"
        understand_dir.mkdir(parents=True, exist_ok=True)
        (understand_dir / "understand.md").write_text(
            "原始症状\n活跃路径假设\n需要证明的行为变化\n",
            encoding="utf-8",
        )

        first_instruction = engine.next()
        assert "Step 2/7" in first_instruction
        step_two_state = engine._load_state()
        assert step_two_state.current_step == 2
        assert step_two_state._state_sig is not None
        assert step_two_state._state_sig != start_state._state_sig

        (tmp_path / "plan.yaml").write_text("tasks: []\n", encoding="utf-8")
        monkeypatch.setattr(
            flow_engine_module,
            "_run_process_check",
            lambda command, workspace, check_name: CheckResult(
                True,
                [{"check": check_name, "passed": True, "message": "ok"}],
            ),
        )

        second_instruction = engine.next()
        assert "Step 3/7" in second_instruction
        step_three_state = engine._load_state()
        assert step_three_state.current_step == 3
        assert step_three_state._state_sig is not None
        assert step_three_state._state_sig != step_two_state._state_sig

    def test_hmac_blocks_tampered_state_on_next(self, tmp_path: Path, monkeypatch) -> None:
        """Tampering with state.json breaks the next() flow entrypoint."""
        monkeypatch.setenv("CODEX_BRIDGE_SECRET", "test-secret-v46")
        engine = FlowEngine(tmp_path)
        engine.start("solve", test_cmd="pytest", tracker="tracker.md")

        state_path = tmp_path / ".ralph-flow" / "state.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload["current_step"] = 99
        state_path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match="integrity"):
            engine.next()


class TestModelSelectionPriority:
    """FL-40: strengths > best_for > description priority chain."""

    def test_strengths_beat_best_for(self) -> None:
        """Direct strengths match should win over a best_for-only candidate."""
        registry = ModelRegistry(
            models={
                "strength-model": ModelCapability(
                    runtime="codex",
                    model_id="strength-model",
                    strengths=["backend"],
                ),
                "best-for-model": ModelCapability(
                    runtime="codex",
                    model_id="best-for-model",
                    best_for="backend",
                ),
            }
        )

        assert select_model_for_task("backend", registry) == "strength-model"

    def test_best_for_beats_description(self) -> None:
        """best_for should win when both candidates lack a direct strengths match."""
        registry = ModelRegistry(
            models={
                "best-for-model": ModelCapability(
                    runtime="codex",
                    model_id="best-for-model",
                    best_for="backend",
                ),
                "description-model": ModelCapability(
                    runtime="codex",
                    model_id="description-model",
                    description="backend specialist for API work",
                ),
            }
        )

        assert select_model_for_task("backend", registry) == "best-for-model"


class TestScopeViolationUnified:
    """FL-29: W_WORKER_EXCEEDED_SCOPE unified across detection points."""

    def test_scope_warning_code_is_unified(self, tmp_path: Path) -> None:
        """Ralph warnings and workflow monitor alerts use the same code."""
        service = RalphService(tmp_path, "group-test")
        task = TaskRef(id="T1", title="scope-check", claimed_paths=["backend/"])

        warnings = service._build_scope_warnings(["other/file.py"], task)
        alert = check_file_overstepping(
            task_id="T1",
            changed_files=["other/file.py"],
            claimed_paths=["backend/"],
        )

        assert WORKER_SCOPE_WARNING_CODE == WORKER_EXCEEDED_SCOPE_CODE
        assert warnings == [
            "W_WORKER_EXCEEDED_SCOPE: modified 1 file(s) outside claimed_paths: "
            "other/file.py"
        ]
        assert alert is not None
        assert alert.alert_type == WORKER_EXCEEDED_SCOPE_CODE
