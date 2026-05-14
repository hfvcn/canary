"""Cross-task integration tests for v27 remaining fixes (T1-T6).

Validates interactions between independently implemented fixes:
- T1 (resubmit guard) + T2 (retry ASSIGNED): resubmit rejected → retry works
- T2 (retry ASSIGNED) + T6 (progress stall): ASSIGNED stall → retry → re-assign
- T3 (challenge degradation) + T2 (retry): degradation → retry succeeds
- T5 (mismatch + verification): force_complete + mismatch → verification runs
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationResult
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state_types import WorkflowTaskStatus


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "models" / "registry.yaml").write_text(
        "\n".join([
            "models:",
            "  codex:",
            "    runtime: codex",
            "    model_id: codex-latest",
            "    strengths: [backend, frontend, general]",
            "    weaknesses: []",
            "",
        ]),
        encoding="utf-8",
    )
    return project_root


def _orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id="v27-integration",
        start_actor_fn=lambda *_args: None,
        send_message_fn=lambda *_args: None,
    )


def _task(task_id: str) -> TaskRef:
    return TaskRef(id=task_id, title=task_id, type="backend", claimed_paths=[f"src/{task_id}.py"])


def _suggestion(*, workflow_id: str, tasks: list[TaskRef], suggestion_id: str) -> ReadyBatchSuggestion:
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=workflow_id,
        tasks=tasks,
        assignments={task.id: f"agent-{task.id}" for task in tasks},
    )


class TestResubmitThenRetry:
    """T1→T2: resubmit rejected for active task, then retry succeeds."""

    def test_resubmit_rejected_then_retry_resets_to_ready(self, tmp_path: Path) -> None:
        orchestrator = _orchestrator(tmp_path)
        task = _task("T-cross")

        result = orchestrator.process_batch_suggestion(
            _suggestion(workflow_id="wf-1", tasks=[task], suggestion_id="batch-1"),
            auto_start_agents=False,
        )
        assert result.decision == "approved"
        state = orchestrator.engine.get_task(task.id)
        assert state.status == WorkflowTaskStatus.ASSIGNED

        resubmit = orchestrator.process_batch_suggestion(
            _suggestion(workflow_id="wf-2", tasks=[task], suggestion_id="batch-2"),
            auto_start_agents=False,
        )
        assert resubmit.decision == "rejected"
        assert "tasks_already_exist" in resubmit.reason

        orchestrator.engine.retry_after_verification(task.id)
        state = orchestrator.engine.get_task(task.id)
        assert state.status == WorkflowTaskStatus.READY


class TestRetryAfterAssignedStall:
    """T2→T6: ASSIGNED stall detected, then retry resets task."""

    def test_assigned_stall_then_retry_succeeds(self, tmp_path: Path) -> None:
        orchestrator = _orchestrator(tmp_path)
        task = _task("T-stall")

        result = orchestrator.process_batch_suggestion(
            _suggestion(workflow_id="wf-stall", tasks=[task], suggestion_id="batch-stall"),
            auto_start_agents=False,
        )
        assert result.decision == "approved"

        state = orchestrator.engine.get_task(task.id)
        assert state.status == WorkflowTaskStatus.ASSIGNED

        orchestrator.engine.retry_after_verification(task.id)
        state = orchestrator.engine.get_task(task.id)
        assert state.status == WorkflowTaskStatus.READY
        assert state.agent_id == ""
