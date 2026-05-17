from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_orchestrator import (
    TASK_STATUS_RUNNING,
    WorkflowOrchestrator,
)
from cccc.kernel.workflow_state import WorkflowTaskStatus


def _task(task_id: str, claimed_paths: list[str] | None = None) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        type="backend",
        claimed_paths=claimed_paths or [f"src/{task_id}.py"],
        verification=VerificationSpec(command="echo ok"),
    )


@pytest.fixture
def orchestrator_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], WorkflowOrchestrator]:
    def create() -> WorkflowOrchestrator:
        orchestrator = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="release-on-fail-test",
            log_fn=lambda _message: None,
        )
        monkeypatch.setattr(
            orchestrator.reporter,
            "on_task_failed",
            lambda *args, **kwargs: True,
        )
        monkeypatch.setattr(
            orchestrator.reporter,
            "on_task_completed",
            lambda *args, **kwargs: True,
        )
        return orchestrator

    return create


def _register_running_engine_task(
    orchestrator: WorkflowOrchestrator,
    task: TaskRef,
    agent_id: str,
    workflow_id: str,
) -> None:
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"batch-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"batch-{task.id}",
        [
            {
                "task_id": task.id,
                "agent_id": agent_id,
                "attempt_id": f"attempt-{task.id}",
                "claimed_paths": list(task.claimed_paths or []),
            }
        ],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)


def test_on_task_failed_releases_active_assignment(
    orchestrator_factory: Callable[[], WorkflowOrchestrator],
) -> None:
    orchestrator = orchestrator_factory()
    workflow_id = "wf-failed-release"
    task = _task("T-fail")
    agent_id = "worker-fail"

    _register_running_engine_task(orchestrator, task, agent_id, workflow_id)
    orchestrator.engine.report_worker_failed(task.id, {"error_message": "boom"})
    tracked = orchestrator._track_task_ref(workflow_id, task, status=TASK_STATUS_RUNNING)
    tracked["agent_id"] = ""
    orchestrator._track_task_ref(workflow_id, _task("T-pending"))
    assert orchestrator.foreman.pool_manager.assign_agent(agent_id, task.id)

    assert orchestrator.on_task_failed(task.id, "boom", agent_name=agent_id) is True

    active_assignments = orchestrator.foreman.pool_manager.get_active_assignments()
    assert agent_id not in active_assignments


def test_deferred_transition_releases_active_assignment(
    orchestrator_factory: Callable[[], WorkflowOrchestrator],
) -> None:
    orchestrator = orchestrator_factory()
    task = _task("T-deferred", ["src/shared.py"])
    agent_id = "worker-stale"
    suggestion = ReadyBatchSuggestion(
        suggestion_id="batch-deferred-release",
        workflow_id="wf-deferred-release",
        tasks=[task],
        rationale="ready",
        estimated_parallelism=1,
    )
    assert orchestrator.foreman.pool_manager.assign_agent(agent_id, task.id)

    result = orchestrator.process_batch_suggestion(suggestion, auto_start_agents=False)

    assert result.decision == "deferred"
    assert orchestrator.engine.get_task(task.id).status == WorkflowTaskStatus.DEFERRED
    active_assignments = orchestrator.foreman.pool_manager.get_active_assignments()
    assert agent_id not in active_assignments


def test_on_task_completed_still_releases_active_assignment(
    orchestrator_factory: Callable[[], WorkflowOrchestrator],
) -> None:
    orchestrator = orchestrator_factory()
    workflow_id = "wf-completed-release"
    task = _task("T-complete")
    agent_id = "worker-complete"
    tracked = orchestrator._track_task_ref(workflow_id, task, status=TASK_STATUS_RUNNING)
    tracked["agent_id"] = agent_id
    tracked["agent_name"] = agent_id
    orchestrator._track_task_ref(workflow_id, _task("T-still-pending"))
    assert orchestrator.foreman.pool_manager.assign_agent(agent_id, task.id)

    assert orchestrator.on_task_completed(task.id, agent_id, 3, ["src/T-complete.py"]) is True

    active_assignments = orchestrator.foreman.pool_manager.get_active_assignments()
    assert agent_id not in active_assignments
