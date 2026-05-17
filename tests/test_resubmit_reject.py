from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state_types import WorkflowTaskStatus


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "models" / "registry.yaml").write_text(
        "\n".join(
            [
                "models:",
                "  codex:",
                "    runtime: codex",
                "    model_id: codex-latest",
                "    strengths: [backend, frontend, general]",
                "    weaknesses: []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return project_root


AGENT_PREFIX = "agent"


def _orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(
        project_root=_prepare_project_root(tmp_path),
        group_id="resubmit-reject-test",
        start_actor_fn=lambda *_args: None,
        send_message_fn=lambda *_args: None,
    )


def _task(task_id: str) -> TaskRef:
    return TaskRef(id=task_id, title=task_id, type="backend", claimed_paths=[f"src/{task_id}.py"], verification=VerificationSpec(command="echo ok"))


def _suggestion(*, workflow_id: str, task_ids: list[str], suggestion_id: str) -> ReadyBatchSuggestion:
    tasks = [_task(task_id) for task_id in task_ids]
    return ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=workflow_id,
        tasks=tasks,
        assignments={task.id: f"agent-{task.id}" for task in tasks},
    )


def _reason(existing_ids: list[str]) -> str:
    return f"tasks_already_exist: {existing_ids}. Use 'cccc workflow retry' instead"


def _write_plan_path(tmp_path: Path) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text("tasks: []\n", encoding="utf-8")
    return plan_path


def _seed_assigned(orchestrator: WorkflowOrchestrator, task: TaskRef, workflow_id: str) -> None:
    """Register a task and advance it to ASSIGNED state (active, non-batchable)."""
    orchestrator.engine.register_task(task, workflow_id)
    agent_id = f"{AGENT_PREFIX}-{task.id}"
    orchestrator.engine.approve_batch(
        f"seed-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": list(task.claimed_paths or [])}],
    )


def test_submit_with_existing_active_task_is_rejected(tmp_path: Path) -> None:
    """Re-submitting a task that's already ASSIGNED should be rejected."""
    orchestrator = _orchestrator(tmp_path)
    existing_task = _task("T-existing")
    _seed_assigned(orchestrator, existing_task, "wf-existing")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id="wf-resubmit",
            task_ids=[existing_task.id],
            suggestion_id="batch-existing",
        ),
        auto_start_agents=False,
    )

    existing_state = orchestrator.engine.get_task(existing_task.id)
    assert result.decision == "rejected"
    assert "tasks_already_exist" in result.reason
    assert [task.id for task in result.rejected_tasks] == ["T-existing"]
    assert existing_state.status == WorkflowTaskStatus.ASSIGNED
    assert existing_state.workflow_id == "wf-existing"


def test_submit_with_all_new_task_ids_passes_normally(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id="wf-new",
            task_ids=["T-new-a", "T-new-b"],
            suggestion_id="batch-new",
        ),
        auto_start_agents=False,
    )

    assert result.decision == "approved"
    assert [task.id for task in result.approved_tasks] == ["T-new-a", "T-new-b"]
    assert orchestrator.engine.get_task("T-new-a").status == WorkflowTaskStatus.ASSIGNED
    assert orchestrator.engine.get_task("T-new-b").workflow_id == "wf-new"


def test_submit_with_mixed_active_and_new_task_ids_is_rejected(tmp_path: Path) -> None:
    """Batch containing both ASSIGNED tasks and new tasks should be rejected."""
    orchestrator = _orchestrator(tmp_path)
    existing_task = _task("T-existing")
    _seed_assigned(orchestrator, existing_task, "wf-existing")

    result = orchestrator.process_batch_suggestion(
        _suggestion(
            workflow_id="wf-resubmit",
            task_ids=[existing_task.id, "T-new"],
            suggestion_id="batch-mixed",
        ),
        auto_start_agents=False,
    )

    assert result.decision == "rejected"
    assert "tasks_already_exist" in result.reason
    assert existing_task.id in [task.id for task in result.rejected_tasks]
    assert orchestrator.engine.get_task(existing_task.id).workflow_id == "wf-existing"


def test_register_and_suggest_existing_active_task_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """register_and_suggest should reject when active tasks exist."""
    orchestrator = _orchestrator(tmp_path)
    existing_task = _task("T-plan-existing")
    _seed_assigned(orchestrator, existing_task, "wf-existing")
    monkeypatch.setattr(
        orchestrator.ralph,
        "suggest_ready_batch",
        lambda *_args, **_kwargs: pytest.fail("suggest_ready_batch should not run"),
    )

    with pytest.raises(ValueError, match="tasks_already_exist"):
        orchestrator.register_and_suggest(
            [existing_task.model_dump()],
            "wf-resubmit",
            plan_path=_write_plan_path(tmp_path),
            auto_start_agents=False,
        )

    assert orchestrator.engine.get_task(existing_task.id).workflow_id == "wf-existing"
