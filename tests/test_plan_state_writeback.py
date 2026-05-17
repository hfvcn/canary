from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import cccc.daemon.foreman.workflow_orchestrator as orchestrator_module
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.ralph.plan_io import compute_structural_plan_digest


TASK_ID = "T-plan"
WORKFLOW_ID = "wf-plan-state"
AGENT_ID = "worker-plan"


def _make_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkflowOrchestrator:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "cccc-home"))
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="plan-state-writeback")
    monkeypatch.setattr(orchestrator.reporter, "on_task_completed", lambda *args, **kwargs: True)
    monkeypatch.setattr(orchestrator.foreman, "release_completed_task", lambda *args: True)
    monkeypatch.setattr(orchestrator, "_check_batch_completion", lambda workflow_id: None)
    monkeypatch.setattr(orchestrator, "_resuggest_ready_tasks", lambda workflow_id: None)
    monkeypatch.setattr(orchestrator._assignment_controller, "_run_completion_monitors", lambda *args: None)
    monkeypatch.setattr(orchestrator, "_notify_foreman_task_update", lambda **kwargs: True)
    monkeypatch.setattr(orchestrator, "_check_workflow_completion_after_terminal", lambda task_id: None)
    return orchestrator


def _register_running_task(orchestrator: WorkflowOrchestrator, plan_path: Path) -> None:
    task = TaskRef(id=TASK_ID, title="Plan state task", type="backend")
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    orchestrator.engine.set_workflow_meta(
        WORKFLOW_ID,
        plan_path=str(plan_path),
        plan_digest=compute_structural_plan_digest(plan_path),
    )
    orchestrator._active_workflows[WORKFLOW_ID] = {
        "started_at": None,
        "batches": [],
        "tasks": {
            TASK_ID: {
                "task_id": TASK_ID,
                "task_title": task.title,
                "task_type": task.type,
                "agent_id": AGENT_ID,
                "agent_name": AGENT_ID,
                "is_new_agent": False,
                "model_runtime": "",
                "model_id": "",
                "claimed_paths": ["src/plan.py"],
                "status": "running",
                "progress_pct": None,
                "last_heartbeat": None,
            }
        },
        "synced_batches": set(),
    }


def _write_plan(plan_path: Path) -> None:
    plan_path.write_text(
        """\
schema_version: "1.0.0"
tasks:
  - id: T-plan
    title: Preserve me
state:
  completed_task_ids: []
  notes: keep
""",
        encoding="utf-8",
    )


def _complete(orchestrator: WorkflowOrchestrator) -> bool:
    return orchestrator.on_task_completed(
        TASK_ID,
        AGENT_ID,
        3,
        ["src/plan.py"],
        workflow_id=WORKFLOW_ID,
    )


def test_task_completion_updates_plan_yaml_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_path = tmp_path / "plan.yaml"
    _write_plan(plan_path)
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    _register_running_task(orchestrator, plan_path)

    assert _complete(orchestrator) is True

    saved: dict[str, Any] = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert saved["state"]["tasks"][TASK_ID] == "completed"
    assert saved["state"]["completed_task_ids"] == [TASK_ID]
    assert saved["state"]["notes"] == "keep"
    assert saved["tasks"][0]["title"] == "Preserve me"


def test_plan_state_write_failure_does_not_crash_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    _write_plan(plan_path)
    orchestrator = _make_orchestrator(tmp_path, monkeypatch)
    _register_running_task(orchestrator, plan_path)

    def raise_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("plan write failed")

    monkeypatch.setattr(orchestrator_module.plan_io, "update_plan_task_state", raise_write)

    assert _complete(orchestrator) is True
    assert orchestrator._active_workflows[WORKFLOW_ID]["tasks"][TASK_ID]["status"] == "completed"
