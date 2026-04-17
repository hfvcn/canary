"""Tests for the structured internal failure envelope (W1-7).

Acceptance criteria:
  (a) CLI malformed YAML -> exit 2 stage="load"
  (b) simulated semantic provider crash via monkeypatch -> exit 2 stage="semantic"
  (c) regular validation failure -> exit 1
  (d) daemon handler with simulated internal exception -> IPC response with structured error, no traceback leak
  (e) orchestrator apply_task_event internal failure emits workflow.ralph_internal_error ledger event
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from cccc.ralph.agent import (
    RALPH_STAGES,
    RULE_ERROR_REGISTRY,
    build_error_envelope,
    _is_debug_traceback_enabled,
)


# ---------------------------------------------------------------------------
# Unit tests for the shared agent module
# ---------------------------------------------------------------------------


class TestRalphStages:
    def test_all_expected_stages_present(self):
        expected = {"load", "validate", "semantic", "ipc", "completion", "register", "suggest", "verify"}
        assert RALPH_STAGES == expected

    def test_registry_stages_are_valid(self):
        for stage, code in RULE_ERROR_REGISTRY.items():
            assert stage in RALPH_STAGES, f"{stage} is not a valid Ralph stage"
            assert code.startswith("E_INTERNAL_"), f"{stage} has invalid code: {code}"


class TestBuildErrorEnvelope:
    def test_basic_envelope(self):
        exc = ValueError("test error message")
        envelope = build_error_envelope(stage="load", exception=exc)
        assert envelope["stage"] == "load"
        assert envelope["internal_error_code"] == "E_INTERNAL_LOAD"
        assert envelope["exception_type"] == "ValueError"
        assert envelope["message"] == "test error message"
        assert "traceback_truncated" not in envelope

    def test_custom_error_code(self):
        exc = RuntimeError("oops")
        envelope = build_error_envelope(
            stage="ipc",
            exception=exc,
            internal_error_code="E_CUSTOM_CODE",
        )
        assert envelope["internal_error_code"] == "E_CUSTOM_CODE"

    def test_registry_controls_default_error_code(self, monkeypatch):
        monkeypatch.setitem(RULE_ERROR_REGISTRY, "load", "E_INTERNAL_PATCHED_LOAD")
        exc = ValueError("test error message")
        envelope = build_error_envelope(stage="load", exception=exc)
        assert envelope["internal_error_code"] == "E_INTERNAL_PATCHED_LOAD"

    def test_debug_traceback(self, monkeypatch):
        monkeypatch.setenv("CCCC_DEBUG_TRACEBACK", "1")
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            envelope = build_error_envelope(stage="load", exception=exc)
        assert "traceback_truncated" in envelope
        assert "boom" in envelope["traceback_truncated"]

    def test_no_traceback_by_default(self, monkeypatch):
        monkeypatch.delenv("CCCC_DEBUG_TRACEBACK", raising=False)
        exc = RuntimeError("test")
        envelope = build_error_envelope(stage="load", exception=exc)
        assert "traceback_truncated" not in envelope

    def test_extra_fields(self):
        exc = ValueError("x")
        envelope = build_error_envelope(stage="ipc", exception=exc, extra={"task_id": "T1"})
        assert envelope["task_id"] == "T1"


# ---------------------------------------------------------------------------
# (a) CLI malformed YAML -> exit 2 stage="load"
# ---------------------------------------------------------------------------


class TestCLIMalformedYAML:
    def test_malformed_yaml_exits_2_with_load_stage(self, tmp_path, capsys):
        plan_file = tmp_path / "bad.yaml"
        plan_file.write_text("{{{{invalid yaml: [[[", encoding="utf-8")

        from cccc.ralph.cli import main

        exit_code = main(["validate", str(plan_file)])

        assert exit_code == 2
        captured = capsys.readouterr()
        error_output = json.loads(captured.err)
        assert error_output["error"]["stage"] == "load"
        assert error_output["error"]["internal_error_code"] == "E_INTERNAL_LOAD"

    def test_missing_file_exits_2_with_load_stage(self, tmp_path, capsys):
        plan_file = tmp_path / "nonexistent.yaml"

        from cccc.ralph.cli import main

        exit_code = main(["validate", str(plan_file)])

        assert exit_code == 2
        captured = capsys.readouterr()
        error_output = json.loads(captured.err)
        assert error_output["error"]["stage"] == "load"
        assert error_output["error"]["exception_type"] == "FileNotFoundError"


# ---------------------------------------------------------------------------
# (b) Simulated semantic provider crash via monkeypatch -> exit 2 stage="semantic"
# ---------------------------------------------------------------------------


class TestCLISemanticCrash:
    def test_semantic_crash_exits_2_with_semantic_stage(self, tmp_path, capsys):
        # Valid plan that passes load but will trigger validate_with_project
        plan_content = textwrap.dedent("""\
            tasks:
              - id: T1
                title: Test task
                claimed_paths: ["src/foo.py"]
                verification:
                  level: unit
                  command: "pytest tests/"
                  covers:
                    tasks: [T1]
        """)
        plan_file = tmp_path / "plan.yaml"
        plan_file.write_text(plan_content, encoding="utf-8")

        from cccc.ralph.cli import main

        def _crash_validate(*args, **kwargs):
            raise RuntimeError("semantic provider exploded")

        with patch("cccc.ralph.cli.validate_with_project", side_effect=_crash_validate):
            exit_code = main(["validate", str(plan_file), "--project-root", str(tmp_path)])

        assert exit_code == 2
        captured = capsys.readouterr()
        error_output = json.loads(captured.err)
        assert error_output["error"]["stage"] == "semantic"
        assert error_output["error"]["internal_error_code"] == "E_INTERNAL_SEMANTIC"
        assert "semantic provider exploded" in error_output["error"]["message"]


# ---------------------------------------------------------------------------
# (c) Regular validation failure -> exit 1
# ---------------------------------------------------------------------------


class TestCLIValidationFailure:
    def test_validation_failure_exits_1(self, tmp_path, capsys):
        # Plan with duplicate task IDs -> structural validation error -> exit 1
        plan_content = textwrap.dedent("""\
            tasks:
              - id: T1
                title: First
                claimed_paths: ["a.py"]
                verification:
                  level: unit
                  command: "pytest"
                  covers:
                    tasks: [T1]
              - id: T1
                title: Duplicate
                claimed_paths: ["b.py"]
                verification:
                  level: unit
                  command: "pytest"
                  covers:
                    tasks: [T1]
        """)
        plan_file = tmp_path / "plan.yaml"
        plan_file.write_text(plan_content, encoding="utf-8")

        from cccc.ralph.cli import main

        exit_code = main(["validate", str(plan_file)])

        # exit 1 = plan-level validation failure (not internal error)
        assert exit_code == 1


# ---------------------------------------------------------------------------
# (d) Daemon handler with simulated internal exception -> IPC structured error
# ---------------------------------------------------------------------------


class TestDaemonIPCErrorEnvelope:
    def test_apply_task_event_internal_error(self, tmp_path):
        from cccc.daemon.foreman.ralph_service import RalphService
        from cccc.contracts.v1.ralph_ipc import TaskEvent

        service = RalphService(
            project_root=tmp_path,
            group_id="test-group",
        )

        event = TaskEvent(
            event_type="completed",
            task_id="T99",
        )

        # Monkey-patch the inner method to raise an exception
        def _explode(ev):
            raise RuntimeError("database connection lost")

        service._apply_task_event_inner = _explode

        result = service.apply_task_event(event)

        assert result["accepted"] is False
        assert result["reason"] == "internal_error"
        assert result["task_id"] == "T99"
        assert "error" in result
        error = result["error"]
        assert error["stage"] == "ipc"
        assert error["internal_error_code"] == "E_INTERNAL_IPC"
        assert error["exception_type"] == "RuntimeError"
        assert "database connection lost" in error["message"]
        # No traceback leak unless CCCC_DEBUG_TRACEBACK=1
        assert "traceback_truncated" not in error

    def test_no_traceback_leak_in_ipc_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CCCC_DEBUG_TRACEBACK", raising=False)

        from cccc.daemon.foreman.ralph_service import RalphService
        from cccc.contracts.v1.ralph_ipc import TaskEvent

        service = RalphService(
            project_root=tmp_path,
            group_id="test-group",
        )

        event = TaskEvent(
            event_type="started",
            task_id="T100",
        )

        def _explode(ev):
            raise ValueError("secret internal info")

        service._apply_task_event_inner = _explode

        result = service.apply_task_event(event)
        assert result["accepted"] is False
        error = result["error"]
        # Message is included but traceback is not
        assert "secret internal info" in error["message"]
        assert "traceback_truncated" not in error


# ---------------------------------------------------------------------------
# (e) Orchestrator apply_task_event emits workflow.ralph_internal_error ledger event
# ---------------------------------------------------------------------------


class TestOrchestratorLedgerErrorEvent:
    def test_apply_task_event_emits_ledger_event(self, tmp_path):
        """When apply_task_event has an internal failure, it should emit a
        workflow.ralph_internal_error ledger event with the stable fields."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        # Create a minimal orchestrator
        group_dir = tmp_path / ".cccc" / "orchestrator" / "test-group"
        group_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = group_dir / "ledger.jsonl"
        ledger_path.touch()

        orchestrator = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group",
        )

        # Create a mock event that will cause an internal failure
        mock_event = MagicMock()
        mock_event.task_id = "T42"
        mock_event.event_type = "completed"
        mock_event.payload = {}

        # Make the inner method raise
        def _blow_up(ev):
            raise RuntimeError("kaboom in apply_task_event")

        orchestrator._apply_task_event_inner = _blow_up

        # The exception should propagate but a ledger event should be emitted first
        with pytest.raises(RuntimeError, match="kaboom"):
            orchestrator.apply_task_event(mock_event)

        # Read the ledger to verify the error event was written
        ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
        error_events = []
        for line in ledger_lines:
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("kind") == "workflow.ralph_internal_error":
                error_events.append(ev)

        assert len(error_events) >= 1, f"Expected at least one ralph_internal_error event in ledger, got: {ledger_lines}"
        error_data = error_events[0]["data"]
        assert error_data["stage"] == "completion"
        assert error_data["internal_error_code"] == "E_INTERNAL_COMPLETION"
        assert error_data["exception_type"] == "RuntimeError"
        assert "kaboom" in error_data["message"]

    def test_register_and_suggest_emits_ledger_event(self, tmp_path):
        """When register_and_suggest has an internal failure, it should emit a
        workflow.ralph_internal_error ledger event."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        group_dir = tmp_path / ".cccc" / "orchestrator" / "test-group"
        group_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = group_dir / "ledger.jsonl"
        ledger_path.touch()

        orchestrator = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group",
        )

        def _blow_up(*args, **kwargs):
            raise RuntimeError("register failure")

        orchestrator._register_and_suggest_inner = _blow_up

        with pytest.raises(RuntimeError, match="register failure"):
            orchestrator.register_and_suggest([], "wf-test")

        ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
        error_events = [
            json.loads(line)
            for line in ledger_lines
            if line.strip() and json.loads(line).get("kind") == "workflow.ralph_internal_error"
        ]

        assert len(error_events) >= 1
        error_data = error_events[0]["data"]
        assert error_data["stage"] == "register"
        assert error_data["internal_error_code"] == "E_INTERNAL_REGISTER"

    def test_on_task_completed_emits_ledger_event(self, tmp_path):
        """When on_task_completed has an internal failure, it should emit a
        workflow.ralph_internal_error ledger event."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        group_dir = tmp_path / ".cccc" / "orchestrator" / "test-group"
        group_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = group_dir / "ledger.jsonl"
        ledger_path.touch()

        orchestrator = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-group",
        )

        def _blow_up(*args, **kwargs):
            raise RuntimeError("completion blowup")

        orchestrator._on_task_completed_inner = _blow_up

        with pytest.raises(RuntimeError, match="completion blowup"):
            orchestrator.on_task_completed(
                task_id="T50",
                agent_id="agent-1",
                duration_seconds=10,
                changed_files=["a.py"],
                workflow_id="wf-1",
            )

        ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
        error_events = [
            json.loads(line)
            for line in ledger_lines
            if line.strip() and json.loads(line).get("kind") == "workflow.ralph_internal_error"
        ]

        assert len(error_events) >= 1
        error_data = error_events[0]["data"]
        assert error_data["stage"] == "completion"
        assert error_data["internal_error_code"] == "E_INTERNAL_COMPLETION"
        assert "completion blowup" in error_data["message"]
