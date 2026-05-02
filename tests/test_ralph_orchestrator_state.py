from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


GROUP_ID = "test-ralph-state"
WORKFLOW_ID = "wf-state"


def _make_orchestrator(tmp_path: Path, monkeypatch) -> WorkflowOrchestrator:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path))
    return WorkflowOrchestrator(project_root=tmp_path, group_id=GROUP_ID)


def _task(task_id: str = "task-1") -> TaskRef:
    return TaskRef(
        id=task_id,
        title="Engine task",
        type="backend",
        claimed_paths=["src/engine.py"],
    )


def _pollute_shadow(orchestrator: WorkflowOrchestrator, task: TaskRef) -> None:
    orchestrator._active_workflows[WORKFLOW_ID] = {
        "started_at": "",
        "batches": ["stale-batch"],
        "tasks": {
            task.id: {
                "task_id": task.id,
                "task_title": "Shadow task",
                "task_type": "backend",
                "task_ref": task,
                "status": "completed",
                "agent_id": "shadow-agent",
                "claimed_paths": ["src/shadow.py"],
                "changed_files": ["src/shadow.py"],
                "duration_seconds": 999,
                "error_message": "stale cache error",
            }
        },
        "synced_batches": set(),
        "auto_process": False,
        "auto_start_agents": True,
    }


def test_workflow_state_reads_engine_projection_not_shadow(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    task = _task()
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    _pollute_shadow(orchestrator, task)

    state = orchestrator.get_workflow_state(WORKFLOW_ID)
    assignments = state["snapshot"]["assignments"]

    assert state["active"] is True
    assert len(assignments) == 1
    assert assignments[0]["status"] == "planned"
    assert assignments[0]["agent_id"] == ""
    assert assignments[0]["task_title"] == "Engine task"
    assert "changed_files" not in assignments[0]
    assert "duration_seconds" not in assignments[0]
    assert "error_message" not in assignments[0]
    assert state["snapshot"]["tasks"]["pending"] == 1
    assert state["snapshot"]["tasks"]["completed"] == 0


def test_shadow_pollution_is_ignored_when_engine_empty(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    _pollute_shadow(orchestrator, _task("stale-task"))

    state = orchestrator.get_workflow_state(WORKFLOW_ID)

    assert state["active"] is False
    assert state["kind"] == "idle"
    assert state["snapshot"]["assignments"] == []
    assert state["snapshot"]["tasks"]["total"] == 0


def test_deleting_task_statuses_has_no_effect(tmp_path: Path, monkeypatch) -> None:
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    task = _task("task-status")
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator.ralph._task_statuses = {task.id: "completed"}
    del orchestrator.ralph._task_statuses

    state = orchestrator.get_workflow_state(WORKFLOW_ID)
    assignments = state["snapshot"]["assignments"]

    assert not hasattr(orchestrator.ralph, "_task_statuses")
    assert assignments[0]["task_id"] == task.id
    assert assignments[0]["status"] == "planned"
