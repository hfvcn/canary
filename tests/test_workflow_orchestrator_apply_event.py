from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_workflow_state import _count_kind, group, temp_home, temp_project_dir


def test_orchestrator_completed_event_auto_transitions_assigned_task(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef, VerificationResult
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-assigned-auto"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)

    def fake_verify_completion(task_id: str, changed_files: list[str], *, workflow_id: str, task_ref: TaskRef) -> VerificationResult:  # noqa: ARG001
        return VerificationResult(verification_id="ver-assigned-auto", workflow_id=workflow_id, task_id=task_id, overall_outcome="passed", checks=[], summary="ok")

    monkeypatch.setattr(orch.ralph, "verify_completion", fake_verify_completion)
    result = orch.apply_task_event(TaskEvent(event_type="completed", task_id="T1", idempotency_key="idem-assigned-auto", payload={"agent_id": "a1", "workflow_id": workflow_id, "duration_seconds": 0, "changed_files": []}))

    assert result["accepted"] is True
    assert result["verification_outcome"] == "passed"
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]
    assert _count_kind(group.ledger_path, kind="workflow.task_started") == 1
    assert _count_kind(group.ledger_path, kind="workflow.task_reported_completed") == 1
    assert _count_kind(group.ledger_path, kind="workflow.verification_passed") == 1


def test_orchestrator_completed_event_rejects_ready_task(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-ready-reject"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)
    engine.register_batch("b1", ["T1"])
    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    result = orch.apply_task_event(TaskEvent(event_type="completed", task_id="T1", idempotency_key="idem-ready-reject", payload={"agent_id": "a1", "workflow_id": workflow_id, "duration_seconds": 0, "changed_files": []}))

    assert result["accepted"] is False
    assert "task_still_ready" in result["reason"]
    assert "auto_process" in result["reason"]
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.READY  # type: ignore[union-attr]
    assert _count_kind(group.ledger_path, kind="workflow.task_reported_completed") == 0


def test_orchestrator_completed_event_rejects_planned_task(group, temp_project_dir: Path) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-planned-reject"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)
    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    result = orch.apply_task_event(TaskEvent(event_type="completed", task_id="T1", idempotency_key="idem-planned-reject", payload={"agent_id": "a1", "workflow_id": workflow_id, "duration_seconds": 0, "changed_files": []}))

    assert result["accepted"] is False
    assert "task_not_running" in result["reason"]
    assert "status=planned" in result["reason"]
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.PLANNED  # type: ignore[union-attr]


def test_orchestrator_hook_transition_rejected_returns_accepted_false(
    group,
    temp_project_dir: Path,
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef
    from cccc.daemon.foreman.workflow_monitor import MonitorMode
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    workflow_id = "wf-hook-reject"
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T1", title="t1"), workflow_id)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    orch = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)

    def hook(kind, data, workflow_engine):  # noqa: ARG001
        from cccc.kernel.workflow_state_types import KIND_TASK_REPORTED_COMPLETED

        if kind != KIND_TASK_REPORTED_COMPLETED:
            return
        raise RuntimeError("boom")

    hook.invariant_id = "completer_mismatch"
    orch.engine.register_pre_transition_hook(hook)
    orch.engine.set_monitor_mode("completer_mismatch", MonitorMode.BLOCK)
    result = orch.apply_task_event(TaskEvent(event_type="completed", task_id="T1", idempotency_key="idem-hook-reject", payload={"agent_id": "a1", "workflow_id": workflow_id, "duration_seconds": 0, "changed_files": []}))

    assert result["accepted"] is False
    assert result["code"] == "hook_error:completer_mismatch"
    assert "Hook error in BLOCK mode: boom" in result["reason"]
    assert orch.engine.get_task("T1").status == WorkflowTaskStatus.RUNNING  # type: ignore[union-attr]
