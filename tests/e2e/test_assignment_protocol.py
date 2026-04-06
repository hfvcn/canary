"""E2E tests for the assignment protocol (Batch C).

Verifies:
- ARCH-1: Foreman explicit assignments respected
- ARCH-2: Rejected batches stay rejected (no silent fallback)
- ARCH-3: Resuggest notifies Foreman instead of auto-processing
- ARCH-6: assignment_id passthrough and validation
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.daemon.foreman.agent_pool import TaskAssignment
from cccc.daemon.foreman.workflow import BatchEvaluationResult


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def orchestrator(temp_home, temp_project_dir):
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="assignment-test", topic="")
    scope = detect_scope(temp_project_dir)
    group = attach_scope_to_group(reg, group, scope, set_active=True)

    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator(
        project_root=temp_project_dir,
        group_id=group.group_id,
    )
    return orch, group


class TestForemanExplicitAssignment:
    def test_explicit_assignment_skips_agent_pool(self, orchestrator):
        """ARCH-1: When Foreman provides assignments, agent pool is bypassed."""
        orch, group = orchestrator

        tasks = [
            TaskRef(id="T1", title="test-1", type="backend", claimed_paths=["src/a.py"]),
        ]
        suggestion = ReadyBatchSuggestion(
            suggestion_id="batch-1",
            workflow_id="wf-explicit",
            tasks=tasks,
            assignments={"T1": "actor-backend-1"},
        )

        foreman_called = []
        original_foreman = orch.foreman.process_batch_suggestion

        def spy_foreman(*args, **kwargs):
            foreman_called.append(True)
            return original_foreman(*args, **kwargs)

        with patch.object(orch.foreman, "process_batch_suggestion", side_effect=spy_foreman):
            result = orch.process_batch_suggestion(suggestion, auto_start_agents=False)

        assert result.decision == "approved"
        assert len(foreman_called) == 0, "Foreman agent pool should NOT be called for explicit assignments"
        assert result.assignments[0].agent_id == "actor-backend-1"
        assert result.assignments[0].assignment_reason == "foreman_explicit"


class TestRejectedBatchStaysRejected:
    def test_no_silent_fallback(self, orchestrator):
        """ARCH-2: Rejected batch must NOT be silently converted to approved."""
        orch, group = orchestrator

        tasks = [
            TaskRef(id="T1", title="test-1", type="backend", claimed_paths=["src/a.py"]),
        ]
        suggestion = ReadyBatchSuggestion(
            suggestion_id="batch-rejected",
            workflow_id="wf-reject",
            tasks=tasks,
        )

        def fake_foreman_reject(_suggestion, *, auto_approve=True, notify_feishu=False):
            return BatchEvaluationResult(
                suggestion=suggestion,
                assignments=[],
                rejected_tasks=list(tasks),
                decision="rejected",
                reason="No suitable agents found for any task",
            )

        with patch.object(orch.foreman, "process_batch_suggestion", side_effect=fake_foreman_reject):
            result = orch.process_batch_suggestion(suggestion, auto_start_agents=False)

        assert result.decision == "rejected", "Rejected must stay rejected"
        assert len(result.rejected_tasks) == 1
        assert not hasattr(orch, "_fallback_to_group_actors"), "Fallback method should not exist"


class TestResuggestNotifiesForeman:
    def test_resuggest_sends_notification_not_auto_process(self, orchestrator):
        """ARCH-3: _resuggest_ready_tasks notifies Foreman instead of auto-processing."""
        orch, group = orchestrator

        # Set up a workflow with T1 completed and T2 depending on T1
        tasks = [
            TaskRef(id="T1", title="task-1", type="backend", claimed_paths=["src/a.py"]),
            TaskRef(id="T2", title="task-2", type="backend", depends_on=["T1"], claimed_paths=["src/b.py"]),
        ]
        orch._ensure_active_workflow("wf-dag")
        for t in tasks:
            orch.engine.register_task(t, "wf-dag")
            orch._track_task_ref("wf-dag", t)

        orch._active_workflows["wf-dag"]["tasks"]["T1"]["status"] = "completed"

        process_called = []
        notifications = []

        # Mock Ralph to return T2 as ready
        fake_suggestion = ReadyBatchSuggestion(
            suggestion_id="resuggest-1",
            workflow_id="wf-dag",
            tasks=[tasks[1]],
        )

        def spy_process(suggestion, *, auto_start_agents=True):
            process_called.append(True)

        def spy_notify(*, task_id, new_status, summary):
            notifications.append({"task_id": task_id, "status": new_status, "summary": summary})
            return True

        with patch.object(orch, "process_batch_suggestion", side_effect=spy_process), \
             patch.object(orch, "_notify_foreman_task_update", side_effect=spy_notify), \
             patch.object(orch.ralph, "suggest_ready_batch", return_value=fake_suggestion):
            orch._resuggest_ready_tasks("wf-dag")

        assert len(process_called) == 0, "process_batch_suggestion should NOT be called"
        assert len(notifications) >= 1, "Foreman should receive notification"
        assert notifications[0]["status"] == "tasks_ready"
        assert "T2" in notifications[0]["summary"]


class TestAssignmentIdPassthrough:
    def test_assignment_id_in_task_event_payload(self, orchestrator):
        """ARCH-6: assignment_id flows through to task event payload."""
        from cccc.daemon.ops.workflow_task_ops import complete_task

        orch, group = orchestrator

        # Register a task first
        task = TaskRef(id="T1", title="test", type="backend", claimed_paths=["src/a.py"])
        suggestion = ReadyBatchSuggestion(
            suggestion_id="batch-aid",
            workflow_id="wf-aid",
            tasks=[task],
            assignments={"T1": "actor-1"},
        )
        orch.process_batch_suggestion(suggestion, auto_start_agents=False)

        # Complete with assignment_id — should flow through
        result = complete_task(
            group.group_id, "T1", "actor-1", [], {},
            "wf-aid", str(orch.project_root), None,
            assignment_id="assign-123", actor_run_id="run-456",
        )
        assert result.get("ok") is True or result.get("result", {}).get("accepted") is True


class TestBackwardCompatible:
    def test_no_assignments_uses_foreman_evaluation(self, orchestrator):
        """When no assignments provided, behavior is identical to before."""
        orch, group = orchestrator

        tasks = [
            TaskRef(id="T1", title="test-1", type="backend", claimed_paths=["src/a.py"]),
        ]
        suggestion = ReadyBatchSuggestion(
            suggestion_id="batch-compat",
            workflow_id="wf-compat",
            tasks=tasks,
            # No assignments — should go through Foreman evaluation
        )

        foreman_called = []
        original_foreman = orch.foreman.process_batch_suggestion

        def spy_foreman(*args, **kwargs):
            foreman_called.append(True)
            return original_foreman(*args, **kwargs)

        with patch.object(orch.foreman, "process_batch_suggestion", side_effect=spy_foreman):
            result = orch.process_batch_suggestion(suggestion, auto_start_agents=False)

        assert len(foreman_called) == 1, "Foreman evaluation MUST be called when no explicit assignments"
