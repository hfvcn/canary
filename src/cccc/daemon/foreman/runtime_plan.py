from __future__ import annotations

from typing import Iterable, List

from cccc.kernel.workflow_state_types import TaskState, WorkflowTaskStatus
from cccc.ralph.models import Plan, PlanState, RunningTask

_STATUS_BUCKETS = {
    WorkflowTaskStatus.COMPLETED: "completed",
    WorkflowTaskStatus.ARCHIVED: "completed",
    WorkflowTaskStatus.RUNNING: "running",
    WorkflowTaskStatus.VERIFYING: "running",
    WorkflowTaskStatus.ASSIGNED: "running",
    WorkflowTaskStatus.FAILED: "failed",
    WorkflowTaskStatus.BLOCKED: "failed",
    WorkflowTaskStatus.DEFERRED: "failed",
    WorkflowTaskStatus.PLANNED: "candidate",
    WorkflowTaskStatus.READY: "candidate",
}

_RUNNING_BUCKET = "running"
_COMPLETED_BUCKET = "completed"
_FAILED_BUCKET = "failed"


def project_engine_state(
    base_plan: Plan,
    engine_tasks: Iterable[TaskState],
    workflow_id: str,
) -> Plan:
    """Return a fresh Plan with state synthesised from engine task states."""
    plan_task_ids = {task.id for task in base_plan.tasks}
    completed_task_ids: List[str] = []
    running_tasks: List[RunningTask] = []
    failed_task_ids: List[str] = []
    seen_completed = set()
    seen_running = set()
    seen_failed = set()

    for task_state in engine_tasks:
        if task_state.workflow_id != workflow_id:
            continue
        bucket = _STATUS_BUCKETS[task_state.status]
        task_id = task_state.task.id

        if bucket == _RUNNING_BUCKET:
            if task_id in seen_running:
                continue
            running_tasks.append(
                RunningTask(
                    task_id=task_id,
                    claimed_paths=list(task_state.task.claimed_paths or []),
                )
            )
            seen_running.add(task_id)
            continue

        if task_id not in plan_task_ids:
            continue
        if bucket == _COMPLETED_BUCKET and task_id not in seen_completed:
            completed_task_ids.append(task_id)
            seen_completed.add(task_id)
            continue
        if bucket == _FAILED_BUCKET and task_id not in seen_failed:
            failed_task_ids.append(task_id)
            seen_failed.add(task_id)

    projected_state = PlanState(
        completed_task_ids=completed_task_ids,
        running_tasks=running_tasks,
        failed_task_ids=failed_task_ids,
    )
    return base_plan.model_copy(update={"state": projected_state}, deep=True)


def derive_running_write_sets(
    engine_tasks: Iterable[TaskState],
    workflow_id: str,
) -> List[List[str]]:
    """Return write sets for running-like tasks in the target workflow."""
    running_write_sets: List[List[str]] = []

    for task_state in engine_tasks:
        if task_state.workflow_id != workflow_id:
            continue
        if _STATUS_BUCKETS[task_state.status] != _RUNNING_BUCKET:
            continue
        running_write_sets.append(list(task_state.task.claimed_paths or []))

    return running_write_sets
