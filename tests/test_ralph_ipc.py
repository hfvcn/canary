"""
Tests for Ralph-Daemon IPC protocol.

Tests the message models and daemon operations for Ralph-Foreman communication.
"""

import os
import tempfile
import unittest
from uuid import uuid4


class TestRalphIPCContracts(unittest.TestCase):
    """Test Ralph IPC message contracts."""

    def test_ready_batch_suggestion_model(self) -> None:
        from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef

        suggestion = ReadyBatchSuggestion(
            suggestion_id="test-1",
            workflow_id="wf-1",
            tasks=[
                TaskRef(id="t1", title="Task 1", type="backend"),
                TaskRef(id="t2", title="Task 2", type="frontend"),
            ],
            rationale="Independent tasks",
            estimated_parallelism=2,
        )

        self.assertEqual(suggestion.suggestion_id, "test-1")
        self.assertEqual(suggestion.workflow_id, "wf-1")
        self.assertEqual(len(suggestion.tasks), 2)
        self.assertEqual(suggestion.tasks[0].type, "backend")
        self.assertEqual(suggestion.estimated_parallelism, 2)

    def test_verification_result_model(self) -> None:
        from cccc.contracts.v1.ralph_ipc import VerificationResult, VerificationCheck

        result = VerificationResult(
            verification_id="ver-1",
            workflow_id="wf-1",
            task_id="t1",
            overall_outcome="passed",
            checks=[
                VerificationCheck(name="build", outcome="passed", duration_ms=1000),
                VerificationCheck(name="test", outcome="passed", duration_ms=5000),
            ],
            summary="All checks passed",
        )

        self.assertEqual(result.overall_outcome, "passed")
        self.assertEqual(len(result.checks), 2)
        self.assertEqual(result.checks[0].duration_ms, 1000)

    def test_restart_suggestion_model(self) -> None:
        from cccc.contracts.v1.ralph_ipc import RestartSuggestion, TaskRef

        suggestion = RestartSuggestion(
            suggestion_id="rst-1",
            workflow_id="wf-1",
            task=TaskRef(id="t1", title="Failed Task", type="backend"),
            reason="Build failed due to dependency error",
            previous_attempts=1,
            files_to_adopt=["src/main.py", "src/utils.py"],
        )

        self.assertEqual(suggestion.previous_attempts, 1)
        self.assertEqual(len(suggestion.files_to_adopt), 2)

    def test_batch_decision_model(self) -> None:
        from cccc.contracts.v1.ralph_ipc import BatchDecision

        decision = BatchDecision(
            decision_id="dec-1",
            suggestion_id="sug-1",
            workflow_id="wf-1",
            decision="modified",
            approved_tasks=["t1", "t2"],
            rejected_tasks=["t3"],
            reason="t3 has unresolved dependency",
        )

        self.assertEqual(decision.decision, "modified")
        self.assertEqual(len(decision.approved_tasks), 2)
        self.assertEqual(len(decision.rejected_tasks), 1)

    def test_actor_status_model(self) -> None:
        from cccc.contracts.v1.ralph_ipc import ActorStatus

        status = ActorStatus(
            actor_id="ralph-1",
            actor_type="ralph",
            workflow_id="wf-1",
            status="executing",
            current_task_id="t1",
            message="Running verification",
            progress_pct=50,
        )

        self.assertEqual(status.actor_type, "ralph")
        self.assertEqual(status.status, "executing")
        self.assertEqual(status.progress_pct, 50)

    def test_parse_ralph_message(self) -> None:
        from cccc.contracts.v1.ralph_ipc import parse_ralph_message, ReadyBatchSuggestion

        data = {
            "message_type": "ready_batch_suggestion",
            "suggestion_id": "sug-1",
            "workflow_id": "wf-1",
            "tasks": [{"id": "t1", "title": "Task 1", "type": "backend"}],
        }

        msg = parse_ralph_message(data)
        self.assertIsInstance(msg, ReadyBatchSuggestion)
        self.assertEqual(msg.suggestion_id, "sug-1")

    def test_parse_ralph_message_unknown_type(self) -> None:
        from cccc.contracts.v1.ralph_ipc import parse_ralph_message

        with self.assertRaises(ValueError) as ctx:
            parse_ralph_message({"message_type": "unknown"})

        self.assertIn("Unknown Ralph IPC message type", str(ctx.exception))


class TestRalphIPCHandler(unittest.TestCase):
    """Test Ralph IPC daemon operations."""

    def _with_home(self):
        old_home = os.environ.get("CCCC_HOME")
        td_ctx = tempfile.TemporaryDirectory()
        td = td_ctx.__enter__()
        os.environ["CCCC_HOME"] = td

        def cleanup() -> None:
            td_ctx.__exit__(None, None, None)
            if old_home is None:
                os.environ.pop("CCCC_HOME", None)
            else:
                os.environ["CCCC_HOME"] = old_home

        return td, cleanup

    def test_try_handle_ralph_op_unknown_returns_none(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        result = try_handle_ralph_op("not_ralph_op", {})
        self.assertIsNone(result)

    def test_ralph_batch_suggest(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-1",
            "tasks": [
                {"id": "t1", "title": "Task 1", "type": "backend"},
                {"id": "t2", "title": "Task 2", "type": "frontend"},
            ],
            "rationale": "Independent tasks",
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertIn("suggestion_id", resp.result)
        self.assertEqual(resp.result["task_count"], 2)

    def test_ralph_batch_suggest_missing_workflow(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_batch_suggest", {
            "tasks": [{"id": "t1"}],
        })

        self.assertIsNotNone(resp)
        self.assertFalse(resp.ok)
        self.assertEqual(resp.error.code, "missing_field")

    def test_ralph_batch_suggest_empty_tasks(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-1",
            "tasks": [],
        })

        self.assertIsNotNone(resp)
        self.assertFalse(resp.ok)
        self.assertFalse(resp.ok)  # Empty tasks is either missing_field or invalid_tasks

    def test_ralph_verification_result(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_verification_result", {
            "workflow_id": "wf-1",
            "overall_outcome": "passed",
            "checks": [
                {"name": "build", "outcome": "passed", "duration_ms": 1000},
            ],
            "summary": "All checks passed",
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertIn("verification_id", resp.result)
        self.assertEqual(resp.result["overall_outcome"], "passed")

    def test_ralph_verification_result_invalid_outcome(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_verification_result", {
            "workflow_id": "wf-1",
            "overall_outcome": "invalid",
        })

        self.assertIsNotNone(resp)
        self.assertFalse(resp.ok)
        self.assertEqual(resp.error.code, "invalid_outcome")

    def test_ralph_restart_suggest(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_restart_suggest", {
            "workflow_id": "wf-1",
            "task_id": "t1",
            "task_title": "Failed Task",
            "reason": "Build failed",
            "previous_attempts": 1,
            "files_to_adopt": ["src/main.py"],
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertIn("suggestion_id", resp.result)
        self.assertEqual(resp.result["task_id"], "t1")

    def test_ralph_batch_decision_flow(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        # First create a suggestion
        suggest_resp = try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-1",
            "tasks": [{"id": "t1"}, {"id": "t2"}],
        })
        self.assertTrue(suggest_resp.ok)
        suggestion_id = suggest_resp.result["suggestion_id"]

        # Then make a decision
        decision_resp = try_handle_ralph_op("ralph_batch_decision", {
            "suggestion_id": suggestion_id,
            "workflow_id": "wf-1",
            "decision": "approved",
            "approved_tasks": ["t1", "t2"],
        })

        self.assertIsNotNone(decision_resp)
        self.assertTrue(decision_resp.ok)
        self.assertIn("decision_id", decision_resp.result)
        self.assertEqual(decision_resp.result["decision"], "approved")

    def test_ralph_batch_decision_not_found(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_batch_decision", {
            "suggestion_id": "nonexistent",
            "workflow_id": "wf-1",
            "decision": "approved",
        })

        self.assertIsNotNone(resp)
        self.assertFalse(resp.ok)
        self.assertEqual(resp.error.code, "suggestion_not_found")

    def test_ralph_actor_status(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_actor_status", {
            "actor_id": "ralph-1",
            "actor_type": "ralph",
            "workflow_id": "wf-1",
            "status": "executing",
            "current_task_id": "t1",
            "message": "Running verification",
            "progress_pct": 50,
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["status"], "executing")

    def test_ralph_actor_status_invalid_status(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        resp = try_handle_ralph_op("ralph_actor_status", {
            "actor_id": "ralph-1",
            "status": "invalid_status",
        })

        self.assertIsNotNone(resp)
        self.assertFalse(resp.ok)
        self.assertEqual(resp.error.code, "invalid_status")

    def test_ralph_get_pending(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        # Clear state first
        _RALPH_STATE["pending_suggestions"].clear()
        _RALPH_STATE["pending_restarts"].clear()

        # Create a suggestion
        try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-1",
            "tasks": [{"id": "t1"}],
        })

        # Get pending
        resp = try_handle_ralph_op("ralph_get_pending", {
            "workflow_id": "wf-1",
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(len(resp.result["pending_suggestions"]), 1)

    def test_ralph_get_actors(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        # Clear state first
        _RALPH_STATE["actor_statuses"].clear()

        # Create actor statuses
        try_handle_ralph_op("ralph_actor_status", {
            "actor_id": "ralph-1",
            "actor_type": "ralph",
            "workflow_id": "wf-1",
            "status": "idle",
        })
        try_handle_ralph_op("ralph_actor_status", {
            "actor_id": "worker-1",
            "actor_type": "worker",
            "workflow_id": "wf-1",
            "status": "executing",
        })

        # Get all actors
        resp = try_handle_ralph_op("ralph_get_actors", {})
        self.assertTrue(resp.ok)
        self.assertEqual(len(resp.result["actors"]), 2)

        # Filter by type
        resp = try_handle_ralph_op("ralph_get_actors", {"actor_type": "ralph"})
        self.assertTrue(resp.ok)
        self.assertEqual(len(resp.result["actors"]), 1)
        self.assertEqual(resp.result["actors"][0]["actor_type"], "ralph")

    def test_ralph_clear_workflow(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        # Clear state and create data
        for key in _RALPH_STATE:
            _RALPH_STATE[key].clear()

        try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-1",
            "tasks": [{"id": "t1"}],
        })
        try_handle_ralph_op("ralph_actor_status", {
            "actor_id": "ralph-1",
            "workflow_id": "wf-1",
            "status": "idle",
        })

        # Verify data exists
        self.assertEqual(len(_RALPH_STATE["pending_suggestions"]), 1)
        self.assertEqual(len(_RALPH_STATE["actor_statuses"]), 1)

        # Clear workflow
        resp = try_handle_ralph_op("ralph_clear_workflow", {"workflow_id": "wf-1"})
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["workflow_id"], "wf-1")

        # Verify data cleared
        self.assertEqual(len(_RALPH_STATE["pending_suggestions"]), 0)
        self.assertEqual(len(_RALPH_STATE["actor_statuses"]), 0)


if __name__ == "__main__":
    unittest.main()
