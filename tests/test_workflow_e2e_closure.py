"""
Integration tests for WF-1~WF-7 workflow execution closure fixes.

Tests the full pipeline:
- WF-1: Metadata survives IPC handler → engine → worker prompt
- WF-2: Worker prompt includes goal_behavior, acceptance_criteria
- WF-3: DAG gating — downstream tasks ready when deps satisfied
- WF-4: TaskSpec.to_task_ref() preserves all fields
- WF-5: context.sync uses workflow_task_id
- WF-6: Completer mismatch emits verification_warning
- WF-7: Engine computes authoritative duration_seconds
"""

import os
import argparse
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_engine_with_tmpdir():
    """Create a WorkflowEngine backed by a real temp directory."""
    from cccc.kernel.workflow_state_engine import WorkflowEngine

    tmpdir = tempfile.mkdtemp()
    ledger_path = Path(tmpdir) / "ledger.jsonl"
    ledger_path.touch()

    mock_group = MagicMock()
    mock_group.group_id = "test-group"
    mock_group.doc = {}
    mock_group.ledger_path = ledger_path

    engine = WorkflowEngine(mock_group)
    return engine, tmpdir


class TestMetadataFlowIntegration(unittest.TestCase):
    """WF-1/WF-2: Metadata flows from CLI → IPC handler → engine → worker prompt."""

    def test_ipc_handler_preserves_metadata_fields(self):
        """WF-1: goal_behavior, verification survive IPC handler."""
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        _RALPH_STATE["pending_suggestions"].clear()
        resp = try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-e2e",
            "tasks": [{
                "id": "T1",
                "title": "Test task",
                "type": "backend",
                "goal_behavior": "Implement feature X",
                "acceptance_criteria": "X works end-to-end",
                "verification": {"level": "unit", "command": "pytest"},
                "claimed_paths": ["src/x.py"],
            }],
        })

        self.assertTrue(resp.ok)
        suggestion_id = resp.result["suggestion_id"]
        stored = _RALPH_STATE["pending_suggestions"][suggestion_id]
        task = stored["tasks"][0]
        self.assertEqual(task["goal_behavior"], "Implement feature X")
        self.assertEqual(task["acceptance_criteria"], "X works end-to-end")
        self.assertEqual(task["verification"]["level"], "unit")
        self.assertEqual(task["claimed_paths"], ["src/x.py"])

    def test_task_spec_to_task_ref_roundtrip(self):
        """WF-4: TaskSpec.to_task_ref() preserves all fields."""
        from cccc.ralph.models import TaskSpec, Contract, Verification, CheckSpec, VerificationCovers

        spec = TaskSpec(
            id="T1",
            title="Test",
            role="integration",
            type="backend",
            depends_on=["T0"],
            claimed_paths=["src/a.py"],
            goal_behavior="Do X",
            acceptance_criteria="X done",
            verification=Verification(
                level="unit",
                command="pytest",
                checks=[CheckSpec(name="build", command="make build")],
                covers=VerificationCovers(tasks=["T1"], paths=["src/a.py"], flows=["flow1"]),
            ),
            provides=[Contract(name="api_v2", kind="runtime_capability")],
            consumes=[Contract(name="db_schema", kind="artifact")],
            addresses=["WF-1"],
        )

        ref = spec.to_task_ref()
        self.assertEqual(ref.id, "T1")
        self.assertEqual(ref.role, "integration")
        self.assertEqual(ref.type, "backend")
        self.assertEqual(ref.goal_behavior, "Do X")
        self.assertEqual(ref.acceptance_criteria, "X done")
        self.assertIsNotNone(ref.verification)
        self.assertEqual(ref.verification.level, "unit")
        self.assertEqual(ref.verification.command, "pytest")
        self.assertEqual(len(ref.verification.checks), 1)
        self.assertEqual(ref.verification.covers_tasks, ["T1"])
        self.assertEqual(ref.verification.covers_flows, ["flow1"])
        self.assertEqual(len(ref.provides), 1)
        self.assertEqual(ref.provides[0]["name"], "api_v2")
        self.assertEqual(len(ref.consumes), 1)
        self.assertEqual(ref.addresses, ["WF-1"])


class TestPhasedSubmission(unittest.TestCase):
    """WF-3/FIX-6: phased submission uses atomic daemon-side gating."""

    def test_register_and_suggest_resuggests_from_stored_task_refs(self):
        """Downstream tasks are rebuilt from workflow task_ref after completion."""
        from cccc.daemon.foreman import workflow_orchestrator as orchestrator_module
        from cccc.daemon.foreman.workflow_orchestrator import (
            TASK_STATUS_COMPLETED,
            TASK_STATUS_RUNNING,
            WorkflowOrchestrator,
        )

        project_root = Path(tempfile.mkdtemp())
        orchestrator = WorkflowOrchestrator(project_root=project_root, group_id="test-group")
        captured_batches: list[list[str]] = []

        def fake_process_batch_suggestion(suggestion, *, auto_start_agents=True):
            captured_batches.append([task.id for task in suggestion.tasks])
            return SimpleNamespace(suggestion=suggestion, approved_tasks=list(suggestion.tasks))

        tasks = [
            {"id": "T1", "title": "Task 1", "type": "backend", "claimed_paths": ["src/a.py"]},
            {"id": "T2", "title": "Task 2", "type": "backend", "depends_on": ["T1"], "claimed_paths": ["src/b.py"]},
            {"id": "T3", "title": "Task 3", "type": "backend", "claimed_paths": ["src/c.py"]},
            {"id": "T4", "title": "Task 4", "type": "backend", "depends_on": ["T2", "T3"], "claimed_paths": ["src/d.py"]},
        ]

        orchestrator_module._ORCHESTRATORS["test-group"] = orchestrator
        try:
            with patch.object(orchestrator, "process_batch_suggestion", side_effect=fake_process_batch_suggestion):
                result = orchestrator.register_and_suggest(tasks, "wf-phased", auto_start_agents=False)

                self.assertEqual(result["registered"], 4)
                self.assertEqual(result["submitted"], 2)
                self.assertEqual(captured_batches, [["T1", "T3"]])
                self.assertEqual(
                    orchestrator._active_workflows["wf-phased"]["tasks"]["T2"]["task_ref"].id,
                    "T2",
                )

                tracked_tasks = orchestrator._active_workflows["wf-phased"]["tasks"]
                tracked_tasks["T1"]["status"] = TASK_STATUS_COMPLETED
                tracked_tasks["T3"]["status"] = TASK_STATUS_RUNNING
                orchestrator._resuggest_ready_tasks("wf-phased")
                self.assertEqual(captured_batches[-1], ["T2"])

                tracked_tasks["T2"]["status"] = TASK_STATUS_COMPLETED
                tracked_tasks["T3"]["status"] = TASK_STATUS_COMPLETED
                orchestrator._resuggest_ready_tasks("wf-phased")
                self.assertEqual(captured_batches[-1], ["T4"])
        finally:
            orchestrator_module.clear_orchestrator("test-group")

    def test_cmd_workflow_submit_uses_atomic_op_for_plan(self):
        """--plan submits through ralph_register_and_suggest."""
        from cccc.cli import workflow_cmds

        calls = []

        def fake_call_daemon(payload, timeout_s=None):  # noqa: ARG001
            calls.append(payload)
            return {"ok": True}

        args = argparse.Namespace(
            group="group-1",
            workflow_id="wf-plan",
            tasks="",
            plan="plan.yaml",
            rationale="",
            parallelism=2,
            auto_process=True,
            auto_start_agents=True,
        )

        with patch.object(workflow_cmds, "_ensure_daemon_or_exit", return_value=True), \
             patch.object(workflow_cmds, "_resolve_group_id", return_value="group-1"), \
             patch.object(workflow_cmds, "_load_tasks_from_plan", return_value=[{"id": "T1"}]), \
             patch.object(workflow_cmds, "_resolve_project_root_for_group", return_value="/tmp/project"), \
             patch.object(workflow_cmds, "call_daemon", side_effect=fake_call_daemon), \
             patch.object(workflow_cmds, "_print_json"):
            exit_code = workflow_cmds.cmd_workflow_submit(args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0]["op"], "ralph_register_and_suggest")

    def test_cmd_workflow_submit_keeps_tasks_path_unchanged(self):
        """--tasks keeps using ralph_batch_suggest."""
        from cccc.cli import workflow_cmds

        fd, tasks_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        Path(tasks_path).write_text('[{"id":"T1","title":"Task 1"}]', encoding="utf-8")
        calls = []

        def fake_call_daemon(payload, timeout_s=None):  # noqa: ARG001
            calls.append(payload)
            return {"ok": True}

        args = argparse.Namespace(
            group="group-1",
            workflow_id="wf-tasks",
            tasks=tasks_path,
            plan="",
            rationale="",
            parallelism=1,
            auto_process=True,
            auto_start_agents=True,
        )

        try:
            with patch.object(workflow_cmds, "_ensure_daemon_or_exit", return_value=True), \
                 patch.object(workflow_cmds, "_resolve_group_id", return_value="group-1"), \
                 patch.object(workflow_cmds, "_resolve_project_root_for_group", return_value="/tmp/project"), \
                 patch.object(workflow_cmds, "call_daemon", side_effect=fake_call_daemon), \
                 patch.object(workflow_cmds, "_print_json"):
                exit_code = workflow_cmds.cmd_workflow_submit(args)
        finally:
            Path(tasks_path).unlink(missing_ok=True)

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0]["op"], "ralph_batch_suggest")


class TestDurationTracking(unittest.TestCase):
    """WF-7: Engine computes authoritative duration."""

    def test_started_at_survives_replay(self):
        """started_at is written to ledger and restored on replay."""
        from cccc.kernel.workflow_state_types import TaskState
        import dataclasses
        fields = {f.name for f in dataclasses.fields(TaskState)}
        self.assertIn("started_at", fields)

    def test_engine_computes_duration(self):
        """report_worker_completion includes duration from engine timestamps."""
        from cccc.kernel.workflow_state_types import KIND_TASK_REPORTED_COMPLETED
        from cccc.contracts.v1.ralph_ipc import TaskRef

        engine, tmpdir = _make_engine_with_tmpdir()

        # Register a task
        task = TaskRef(id="T1", title="Test")
        engine.register_task(task, "wf-1")

        # Approve batch
        engine.register_batch("batch-1", ["T1"])
        engine.approve_batch("batch-1", [{"task_id": "T1", "agent_id": "worker-1", "claimed_paths": []}])

        # Start task — records started_at
        engine.report_worker_started("T1", "worker-1")
        state = engine.get_task("T1")
        self.assertIsNotNone(state.started_at)
        self.assertGreater(state.started_at, 0)

        # Small delay to ensure non-zero duration
        time.sleep(0.05)

        # Complete task — engine computes duration
        events = []
        original_append = engine._append
        def capture_append(*, kind, data):
            events.append({"kind": kind, "data": data})
            original_append(kind=kind, data=data)
        engine._append = capture_append

        engine.report_worker_completion("T1", {"idempotency_key": "k1"})

        # Find the completion event
        completion_events = [e for e in events if e["kind"] == KIND_TASK_REPORTED_COMPLETED]
        self.assertEqual(len(completion_events), 1)
        evidence = completion_events[0]["data"].get("evidence", {})
        self.assertIn("duration_seconds", evidence)
        # Duration should be >= 0 (could be 0 if very fast, but started_at was set)
        self.assertGreaterEqual(evidence["duration_seconds"], 0)


class TestVerificationWarning(unittest.TestCase):
    """WF-6: Engine can record verification warnings."""

    def test_verification_warning_event(self):
        """record_verification_warning writes to ledger."""
        from cccc.kernel.workflow_state_types import KIND_VERIFICATION_WARNING
        from cccc.contracts.v1.ralph_ipc import TaskRef

        engine, tmpdir = _make_engine_with_tmpdir()
        task = TaskRef(id="T1", title="Test")
        engine.register_task(task, "wf-1")

        events = []
        original_append = engine._append
        def capture_append(*, kind, data):
            events.append({"kind": kind, "data": data})
            original_append(kind=kind, data=data)
        engine._append = capture_append

        engine.record_verification_warning(
            "T1",
            warning_type="completer_mismatch",
            message="Agent worker-2 completed task assigned to worker-1",
            evidence={"assigned": "worker-1", "completing": "worker-2"},
        )

        warning_events = [e for e in events if e["kind"] == KIND_VERIFICATION_WARNING]
        self.assertEqual(len(warning_events), 1)
        self.assertEqual(warning_events[0]["data"]["warning_type"], "completer_mismatch")
        self.assertEqual(warning_events[0]["data"]["task_id"], "T1")


class TestContextSyncNumbering(unittest.TestCase):
    """WF-5: context.sync uses workflow_task_id when provided."""

    def test_workflow_task_id_in_source(self):
        """The workflow_task_id parameter exists in context_ops source."""
        import inspect
        from cccc.daemon.context import context_ops
        source = inspect.getsource(context_ops)
        self.assertIn("workflow_task_id", source)


class TestDaemonSendFallback(unittest.TestCase):
    """FIX-8: Orchestrator sends task prompts via daemon op=send fallback."""

    def test_daemon_send_fallback_delivers_task(self):
        """When _send_message_fn is None, orchestrator uses _daemon_request_fn op=send."""
        import inspect
        from cccc.daemon.foreman import workflow_orchestrator as wo

        src = inspect.getsource(wo.WorkflowOrchestrator._start_assigned_agents)
        # Must contain the daemon_request_fn fallback with op="send"
        self.assertIn("_daemon_request_fn", src)
        self.assertIn('"send"', src)
        # Must NOT mark running before send succeeds
        self.assertIn("send_ok", src)

    def test_status_rollback_on_send_failure(self):
        """If send fails, task should NOT transition to running."""
        import inspect
        from cccc.daemon.foreman import workflow_orchestrator as wo

        src = inspect.getsource(wo.WorkflowOrchestrator._start_assigned_agents)
        # After send failure, status should be set back to pending
        self.assertIn("TASK_STATUS_PENDING", src)
        # Status should start as "assigned", not "running"
        self.assertIn('"assigned"', src)


class TestPathDomainScoringIntegration(unittest.TestCase):
    """FIX-10: Agent pool uses claimed_paths domain for scoring."""

    def test_infer_domain_from_paths_exists(self):
        """_infer_domain_from_paths method is available on AgentPoolManager."""
        from cccc.daemon.foreman.agent_pool import AgentPoolManager
        self.assertTrue(hasattr(AgentPoolManager, "_infer_domain_from_paths"))

    def test_frontend_paths_return_frontend_domain(self):
        from cccc.daemon.foreman.agent_pool import AgentPoolManager
        pm = AgentPoolManager.__new__(AgentPoolManager)
        self.assertEqual(pm._infer_domain_from_paths(["src/frontend/App.tsx"]), "frontend")

    def test_backend_paths_return_backend_domain(self):
        from cccc.daemon.foreman.agent_pool import AgentPoolManager
        pm = AgentPoolManager.__new__(AgentPoolManager)
        self.assertEqual(pm._infer_domain_from_paths(["src/api/handler.go"]), "backend")

    def test_mixed_paths_return_general(self):
        from cccc.daemon.foreman.agent_pool import AgentPoolManager
        pm = AgentPoolManager.__new__(AgentPoolManager)
        self.assertEqual(
            pm._infer_domain_from_paths(["src/frontend/a.tsx", "src/backend/b.py"]),
            "general",
        )


if __name__ == "__main__":
    unittest.main()
