from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


@pytest.fixture
def orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    return WorkflowOrchestrator(project_root=tmp_path, group_id="g-stall-idle")


def test_actor_idle_provider_prevents_false_stall(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch, task_id="T-live", agent_id="worker-live")
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1405.0)

    stalled = orchestrator.check_stalled_tasks(
        threshold_seconds=300,
        actor_idle_provider=lambda actor_id: 0.0 if actor_id == "worker-live" else None,
    )

    assert stalled == []


def test_actor_idle_provider_still_flags_when_both_idle_and_heartbeat_are_stale(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch, task_id="T-stale", agent_id="worker-stale")
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1405.0)

    stalled = orchestrator.check_stalled_tasks(
        threshold_seconds=300,
        actor_idle_provider=lambda actor_id: 405.0 if actor_id == "worker-stale" else None,
    )

    assert stalled == ["T-stale"]


def test_actor_idle_provider_none_falls_back_to_heartbeat_only(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch, task_id="T-fallback", agent_id="worker-fallback")
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1405.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=300)

    assert stalled == ["T-fallback"]


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
    *,
    task_id: str,
    agent_id: str,
) -> None:
    task = TaskRef(id=task_id, title=f"Task {task_id}", type="backend")
    orchestrator.engine.register_task(task, "wf-stall-idle")
    orchestrator.engine.register_batch(f"batch-{task_id}", [task_id])
    orchestrator.engine.approve_batch(
        f"batch-{task_id}",
        [{"task_id": task_id, "agent_id": agent_id, "claimed_paths": ["src/demo.py"]}],
    )
    orchestrator.engine.report_worker_started(task_id, agent_id)
    monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: 1000.0)
    orchestrator.engine.record_heartbeat(task_id, 50, "working")

