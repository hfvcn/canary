"""
Tests for Ralph-Daemon IPC protocol.

Tests the message models and daemon operations for Ralph-Foreman communication.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


class TestRalphIPCContracts(unittest.TestCase):
    """Test Ralph IPC message contracts."""

    def _make_task_event(self, event_type: str):
        from cccc.contracts.v1.ralph_ipc import TaskEvent

        return TaskEvent(event_type=event_type, task_id="t1")

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

    def test_task_event_assigned(self) -> None:
        event = self._make_task_event("assigned")
        self.assertEqual(event.event_type, "assigned")

    def test_task_event_started(self) -> None:
        event = self._make_task_event("started")
        self.assertEqual(event.event_type, "started")

    def test_task_event_heartbeat(self) -> None:
        event = self._make_task_event("heartbeat")
        self.assertEqual(event.event_type, "heartbeat")

    def test_task_event_completed_still_works(self) -> None:
        event = self._make_task_event("completed")
        self.assertEqual(event.event_type, "completed")

    def test_task_event_failed_still_works(self) -> None:
        event = self._make_task_event("failed")
        self.assertEqual(event.event_type, "failed")

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


class TestTaskRefVerificationContracts(unittest.TestCase):
    """Test TaskRef verification field compatibility."""

    def test_verification_check_spec_roundtrip(self) -> None:
        from cccc.contracts.v1.ralph_ipc import VerificationCheckSpec
        from cccc.ralph.models import CheckSpec

        payload = {
            "name": "lint",
            "command": "ruff check src",
            "required": False,
            "expected_exit_code": 2,
        }

        ipc_spec = VerificationCheckSpec.model_validate(payload)
        ipc_restored = VerificationCheckSpec.model_validate(ipc_spec.model_dump())
        self.assertEqual(ipc_restored.name, "lint")
        self.assertEqual(ipc_restored.command, "ruff check src")
        self.assertFalse(ipc_restored.required)
        self.assertEqual(ipc_restored.expected_exit_code, 2)

        domain_spec = CheckSpec.model_validate(payload)
        domain_restored = CheckSpec.model_validate(domain_spec.model_dump())
        self.assertEqual(domain_restored.model_dump(), payload)

    def test_task_ref_accepts_deprecated_verification_command(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef

        task_ref = TaskRef(id="t1", verification_command="pytest tests/test_ralph_ipc.py -q")

        self.assertEqual(task_ref.verification_command, "pytest tests/test_ralph_ipc.py -q")
        self.assertIsNone(task_ref.verification)

    def test_task_ref_accepts_structured_verification(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef

        task_ref = TaskRef.model_validate(
            {
                "id": "t1",
                "verification": {
                    "level": "integration",
                    "command": "pytest tests/test_ralph_ipc.py -q",
                    "covers_tasks": ["T1"],
                },
            }
        )

        self.assertIsNotNone(task_ref.verification)
        self.assertEqual(task_ref.verification.level, "integration")
        self.assertEqual(task_ref.verification.command, "pytest tests/test_ralph_ipc.py -q")
        self.assertEqual(task_ref.verification.covers_tasks, ["T1"])

    def test_task_ref_round_trip_preserves_verification_fields(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec

        original = TaskRef(
            id="t1",
            verification_command="pytest legacy -q",
            verification=VerificationSpec(
                level="unit",
                command="pytest structured -q",
                covers_paths=["tests/test_ralph_ipc.py"],
            ),
        )

        restored = TaskRef.model_validate(original.model_dump())

        self.assertEqual(restored.verification_command, "pytest legacy -q")
        self.assertIsNotNone(restored.verification)
        self.assertEqual(restored.verification.command, "pytest structured -q")
        self.assertEqual(restored.verification.covers_paths, ["tests/test_ralph_ipc.py"])

    def test_verification_spec_model(self) -> None:
        from cccc.contracts.v1.ralph_ipc import VerificationSpec

        spec = VerificationSpec.model_validate(
            {
                "command": "pytest tests/test_ralph_ipc.py -q",
                "covers_tasks": ["T1"],
                "covers_paths": ["tests/test_ralph_ipc.py"],
                "covers_flows": ["ralph-ipc"],
            }
        )

        self.assertEqual(spec.level, "unit")
        self.assertEqual(spec.command, "pytest tests/test_ralph_ipc.py -q")
        self.assertEqual(spec.expected_exit_code, 0)
        self.assertEqual(spec.covers_flows, ["ralph-ipc"])

    def test_verification_spec_with_checks_roundtrip(self) -> None:
        from cccc.contracts.v1.ralph_ipc import VerificationSpec
        from cccc.ralph.models import Verification

        payload = {
            "level": "integration",
            "command": "pytest tests/test_ralph_ipc.py -q",
            "checks": [
                {"name": "build", "command": "python -m build"},
                {
                    "name": "lint",
                    "command": "ruff check src",
                    "required": False,
                    "expected_exit_code": 1,
                },
            ],
            "covers_tasks": ["T1"],
            "covers_paths": ["tests/test_ralph_ipc.py"],
            "covers_flows": ["ralph-ipc"],
            "expected_exit_code": 0,
        }
        domain_payload = {
            "level": "integration",
            "command": "pytest tests/test_ralph_ipc.py -q",
            "checks": payload["checks"],
            "covers": {
                "tasks": ["T1"],
                "paths": ["tests/test_ralph_ipc.py"],
                "flows": ["ralph-ipc"],
            },
            "expected_exit_code": 0,
        }

        spec = VerificationSpec.model_validate(payload)
        restored = VerificationSpec.model_validate(spec.model_dump())
        self.assertEqual(len(restored.checks), 2)
        self.assertEqual(restored.checks[0].name, "build")
        self.assertFalse(restored.checks[1].required)
        self.assertEqual(restored.covers_tasks, ["T1"])

        domain_verification = Verification.model_validate(domain_payload)
        domain_restored = Verification.model_validate(domain_verification.model_dump())
        self.assertEqual(len(domain_restored.checks), 2)
        self.assertEqual(domain_restored.checks[1].expected_exit_code, 1)
        self.assertEqual(domain_restored.covers.tasks, ["T1"])

    def test_verification_spec_backward_compat(self) -> None:
        from cccc.contracts.v1.ralph_ipc import VerificationSpec
        from cccc.ralph.models import Verification

        spec = VerificationSpec.model_validate({"command": "pytest tests/test_ralph_ipc.py -q"})
        self.assertEqual(spec.command, "pytest tests/test_ralph_ipc.py -q")
        self.assertEqual(spec.checks, [])

        verification = Verification.model_validate(
            {"level": "unit", "command": "pytest tests/test_ralph_ipc.py -q"}
        )
        self.assertEqual(verification.command, "pytest tests/test_ralph_ipc.py -q")
        self.assertEqual(verification.checks, [])

    def test_verification_spec_checks_and_command(self) -> None:
        from cccc.contracts.v1.ralph_ipc import VerificationSpec
        from cccc.ralph.models import Verification

        payload = {
            "level": "unit",
            "command": "pytest tests/test_ralph_ipc.py -q",
            "checks": [{"name": "lint", "command": "ruff check src"}],
        }

        spec = VerificationSpec.model_validate(payload)
        self.assertEqual(spec.command, "pytest tests/test_ralph_ipc.py -q")
        self.assertEqual(len(spec.checks), 1)
        self.assertEqual(spec.checks[0].command, "ruff check src")

        verification = Verification.model_validate(payload)
        self.assertEqual(verification.command, "pytest tests/test_ralph_ipc.py -q")
        self.assertEqual(len(verification.checks), 1)
        self.assertEqual(verification.checks[0].name, "lint")


class TestRalphServiceVerificationCompatibility(unittest.TestCase):
    """Test verification command compatibility in RalphService."""

    def _make_service(self):
        from cccc.daemon.foreman.ralph_service import RalphService

        return RalphService(project_root=Path.cwd(), group_id="group-1")

    def test_verify_completion_uses_deprecated_verification_command(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheck

        service = self._make_service()
        task_ref = TaskRef(id="t1", verification_command="pytest legacy -q")

        with patch.object(
            service,
            "_run_verification_check",
            return_value=VerificationCheck(name="verification", outcome="passed"),
        ) as run_check:
            service.verify_completion("t1", [], workflow_id="wf-1", task_ref=task_ref)

        self.assertEqual(run_check.call_args.kwargs["command"], "pytest legacy -q")

    def test_verify_completion_uses_structured_verification_command(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheck, VerificationSpec

        service = self._make_service()
        task_ref = TaskRef(
            id="t1",
            verification=VerificationSpec(command="pytest structured -q"),
        )

        with patch.object(
            service,
            "_run_verification_check",
            return_value=VerificationCheck(name="verification", outcome="passed"),
        ) as run_check:
            service.verify_completion("t1", [], workflow_id="wf-1", task_ref=task_ref)

        self.assertEqual(run_check.call_args.kwargs["command"], "pytest structured -q")
        self.assertEqual(run_check.call_args.kwargs["expected_exit_code"], 0)

    def test_verify_completion_passes_structured_expected_exit_code(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheck, VerificationSpec

        service = self._make_service()
        task_ref = TaskRef(
            id="t1",
            verification=VerificationSpec(command="pytest structured -q", expected_exit_code=3),
        )

        with patch.object(
            service,
            "_run_verification_check",
            return_value=VerificationCheck(name="verification", outcome="passed"),
        ) as run_check:
            service.verify_completion("t1", [], workflow_id="wf-1", task_ref=task_ref)

        self.assertEqual(run_check.call_args.kwargs["expected_exit_code"], 3)

    def test_verify_completion_prefers_structured_verification_command(self) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheck, VerificationSpec

        service = self._make_service()
        task_ref = TaskRef(
            id="t1",
            verification_command="pytest legacy -q",
            verification=VerificationSpec(command="  pytest structured -q  "),
        )

        with patch.object(
            service,
            "_run_verification_check",
            return_value=VerificationCheck(name="verification", outcome="passed"),
        ) as run_check:
            service.verify_completion("t1", [], workflow_id="wf-1", task_ref=task_ref)

        self.assertEqual(run_check.call_args.kwargs["command"], "pytest structured -q")


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

    def _put_task_in_verifying(self, orchestrator, task_id: str, workflow_id: str) -> None:
        from cccc.contracts.v1.ralph_ipc import TaskRef

        orchestrator.engine.register_task(TaskRef(id=task_id, title=task_id), workflow_id)
        orchestrator.engine.register_batch("b-verification", [task_id])
        orchestrator.engine.approve_batch(
            "b-verification",
            [{"task_id": task_id, "agent_id": "worker-1", "claimed_paths": []}],
        )
        orchestrator.engine.report_worker_started(task_id, "worker-1")
        orchestrator.engine.report_worker_completion(
            task_id,
            {"idempotency_key": f"idem-{uuid4()}"},
        )

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

    def test_ralph_batch_suggest_preserves_caller_suggestion_id(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        _RALPH_STATE["pending_suggestions"].clear()

        resp = try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-1",
            "suggestion_id": "sug-external-1",
            "tasks": [{"id": "t1", "title": "Task 1", "type": "backend"}],
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["suggestion_id"], "sug-external-1")
        self.assertIn("sug-external-1", _RALPH_STATE["pending_suggestions"])

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

    def test_ralph_register_and_suggest(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        daemon_request_fn = object()
        fake_orchestrator = SimpleNamespace(
            _daemon_request_fn=None,
            register_and_suggest=lambda tasks, workflow_id, **kwargs: {
                "registered": len(tasks),
                "submitted": 1,
                "ready_task_ids": ["t1"],
                "workflow_id": workflow_id,
                "kwargs": kwargs,
            },
        )

        with patch(
            "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
            return_value=fake_orchestrator,
        ) as get_orchestrator:
            resp = try_handle_ralph_op(
                "ralph_register_and_suggest",
                {
                    "workflow_id": "wf-1",
                    "group_id": "group-1",
                    "project_root": "/tmp/project",
                    "tasks": [{"id": "t1", "title": "Task 1", "type": "backend"}],
                    "rationale": "phase-ready",
                    "estimated_parallelism": 2,
                    "auto_start_agents": False,
                },
                daemon_request_fn=daemon_request_fn,
            )

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["registered_count"], 1)
        self.assertEqual(resp.result["submitted_count"], 1)
        self.assertEqual(resp.result["ready_task_ids"], ["t1"])
        self.assertIs(fake_orchestrator._daemon_request_fn, daemon_request_fn)
        get_orchestrator.assert_called_once_with(
            "group-1",
            project_root=Path("/tmp/project"),
            daemon_request_fn=daemon_request_fn,
        )

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

    def test_ralph_verification_result_forwards_to_orchestrator(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        forwarded = []
        fake_orchestrator = SimpleNamespace(
            _daemon_request_fn=None,
            on_verification_result=lambda verification: forwarded.append(verification),
        )

        with patch(
            "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
            return_value=fake_orchestrator,
        ) as get_orchestrator:
            daemon_request_fn = object()
            resp = try_handle_ralph_op(
                "ralph_verification_result",
                {
                    "workflow_id": "wf-1",
                    "group_id": "group-1",
                    "project_root": "/tmp/project",
                    "task_id": "t1",
                    "overall_outcome": "failed",
                    "summary": "tests failed",
                },
                daemon_request_fn=daemon_request_fn,
            )

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0].workflow_id, "wf-1")
        self.assertEqual(forwarded[0].task_id, "t1")
        self.assertIs(fake_orchestrator._daemon_request_fn, daemon_request_fn)
        get_orchestrator.assert_called_once_with("group-1", project_root=Path("/tmp/project"))

    def test_ralph_verification_result_updates_engine_failed_state(self) -> None:
        from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator, get_orchestrator
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        _, cleanup = self._with_home()
        group_id = f"group-{uuid4()}"
        workflow_id = "wf-verification-skipped"
        with tempfile.TemporaryDirectory() as project_dir:
            try:
                orchestrator = get_orchestrator(group_id, project_root=Path(project_dir))
                self._put_task_in_verifying(orchestrator, "t1", workflow_id)

                resp = try_handle_ralph_op(
                    "ralph_verification_result",
                    {
                        "workflow_id": workflow_id,
                        "group_id": group_id,
                        "project_root": project_dir,
                        "task_id": "t1",
                        "overall_outcome": "skipped",
                        "summary": "verification skipped",
                    },
                )

                self.assertIsNotNone(resp)
                self.assertTrue(resp.ok)
                state = orchestrator.engine.get_task("t1")
                self.assertIsNotNone(state)
                self.assertEqual(state.status, WorkflowTaskStatus.FAILED)
            finally:
                clear_orchestrator(group_id)
                cleanup()

    def test_ralph_verification_result_updates_engine_completed_state(self) -> None:
        from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator, get_orchestrator
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        _, cleanup = self._with_home()
        group_id = f"group-{uuid4()}"
        workflow_id = "wf-verification-passed"
        with tempfile.TemporaryDirectory() as project_dir:
            try:
                orchestrator = get_orchestrator(group_id, project_root=Path(project_dir))
                self._put_task_in_verifying(orchestrator, "t1", workflow_id)

                resp = try_handle_ralph_op(
                    "ralph_verification_result",
                    {
                        "workflow_id": workflow_id,
                        "group_id": group_id,
                        "project_root": project_dir,
                        "task_id": "t1",
                        "overall_outcome": "passed",
                        "summary": "verification passed",
                    },
                )

                self.assertIsNotNone(resp)
                self.assertTrue(resp.ok)
                state = orchestrator.engine.get_task("t1")
                self.assertIsNotNone(state)
                self.assertEqual(state.status, WorkflowTaskStatus.COMPLETED)
            finally:
                clear_orchestrator(group_id)
                cleanup()

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

    def test_ralph_restart_suggest_auto_processes_with_orchestrator(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

        processed = []
        fake_result = SimpleNamespace(
            decision="approved",
            approved_tasks=[SimpleNamespace(id="t1")],
            rejected_tasks=[],
        )
        fake_orchestrator = SimpleNamespace(
            _daemon_request_fn=None,
            handle_restart=lambda suggestion, auto_start_agents=True: (
                processed.append((suggestion, auto_start_agents)) or fake_result
            ),
        )

        with patch(
            "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
            return_value=fake_orchestrator,
        ) as get_orchestrator:
            daemon_request_fn = object()
            resp = try_handle_ralph_op(
                "ralph_restart_suggest",
                {
                    "workflow_id": "wf-1",
                    "task_id": "t1",
                    "task_title": "Failed Task",
                    "task_type": "backend",
                    "reason": "Build failed",
                    "group_id": "group-1",
                    "project_root": "/tmp/project",
                    "auto_process": True,
                },
                daemon_request_fn=daemon_request_fn,
            )

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0][0].task.id, "t1")
        self.assertTrue(processed[0][1])
        self.assertEqual(resp.result["processing"]["status"], "processed")
        self.assertEqual(resp.result["processing"]["approved_count"], 1)
        self.assertIs(fake_orchestrator._daemon_request_fn, daemon_request_fn)
        get_orchestrator.assert_called_once()

    def test_ralph_restart_suggest_preserves_caller_suggestion_id(self) -> None:
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        _RALPH_STATE["pending_restarts"].clear()

        resp = try_handle_ralph_op("ralph_restart_suggest", {
            "workflow_id": "wf-1",
            "suggestion_id": "rst-external-1",
            "task_id": "t1",
            "task_title": "Failed Task",
            "reason": "Build failed",
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["suggestion_id"], "rst-external-1")
        self.assertIn("rst-external-1", _RALPH_STATE["pending_restarts"])

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
        from cccc.daemon.ralph_ipc_handler import (
            _ACTOR_STATUS_CACHE,
            try_handle_ralph_op,
        )

        # Clear state first
        _ACTOR_STATUS_CACHE.clear()

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
        from cccc.daemon.ralph_ipc_handler import (
            _ACTOR_STATUS_CACHE,
            _RALPH_STATE,
            try_handle_ralph_op,
        )

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
        self.assertEqual(len(_ACTOR_STATUS_CACHE), 1)

        # Clear workflow
        resp = try_handle_ralph_op("ralph_clear_workflow", {"workflow_id": "wf-1"})
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["workflow_id"], "wf-1")

        # Verify data cleared
        self.assertEqual(len(_RALPH_STATE["pending_suggestions"]), 0)
        self.assertEqual(len(_ACTOR_STATUS_CACHE), 0)

    def test_ralph_batch_suggest_preserves_metadata_fields(self) -> None:
        """WF-1: Verify that goal_behavior, acceptance_criteria, verification
        and other TaskRef fields survive the IPC handler round-trip."""
        from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op, _RALPH_STATE

        _RALPH_STATE["pending_suggestions"].clear()

        resp = try_handle_ralph_op("ralph_batch_suggest", {
            "workflow_id": "wf-meta",
            "tasks": [{
                "id": "t1",
                "title": "Test metadata",
                "type": "backend",
                "depends_on": [],
                "claimed_paths": ["src/a.py"],
                "goal_behavior": "Implement feature X",
                "acceptance_criteria": "Feature X works end-to-end",
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/test_x.py -q",
                    "checks": [{"name": "build", "command": "python -m py_compile src/a.py"}],
                },
                "expected_input": {"data_format": "json"},
                "expected_output": {"status": "ok"},
            }],
        })

        self.assertIsNotNone(resp)
        self.assertTrue(resp.ok)

        # Retrieve the stored suggestion and check fields survived
        suggestion_id = resp.result["suggestion_id"]
        stored = _RALPH_STATE["pending_suggestions"][suggestion_id]
        task = stored["tasks"][0]

        self.assertEqual(task["goal_behavior"], "Implement feature X")
        self.assertEqual(task["acceptance_criteria"], "Feature X works end-to-end")
        self.assertIsNotNone(task.get("verification"))
        self.assertEqual(task["verification"]["level"], "unit")
        self.assertEqual(task["verification"]["command"], "pytest tests/test_x.py -q")
        self.assertEqual(len(task["verification"]["checks"]), 1)
        self.assertEqual(task["expected_input"]["data_format"], "json")
        self.assertEqual(task["expected_output"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
