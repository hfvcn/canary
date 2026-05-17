"""Ledger-backed workflow state projection helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...kernel.workflow_state_types import TaskState
from ...kernel.workflow_state_types import WorkflowTaskStatus as _WTS


TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_COMPLETED_BY_OVERRIDE = _WTS.COMPLETED_BY_OVERRIDE.value
TASK_STATUS_FAILED = "failed"
TASK_STATUS_DEFERRED = _WTS.DEFERRED.value


class WorkflowProjection:
    """Build workflow read models from the workflow engine projection."""

    def __init__(self, owner: Any):
        self._owner = owner

    def get_pool_active_assignments(self) -> Dict[str, str]:
        """Get active agent assignments from the Foreman pool."""
        pool_manager = getattr(self._owner.foreman, "pool_manager", None)
        if pool_manager is None:
            return {}
        get_active_assignments = getattr(pool_manager, "get_active_assignments", None)
        if not callable(get_active_assignments):
            return {}
        return get_active_assignments()

    def get_all_assignments(self) -> List[Dict[str, Any]]:
        """Get assignment state from engine projection and the live agent pool."""
        active_pool_assignments = self.get_pool_active_assignments()
        agent_by_task = {task_id: agent_id for agent_id, task_id in active_pool_assignments.items()}
        assignments = self.build_engine_state_assignments("", self._owner._list_engine_tasks())
        seen_task_ids = set()

        for assignment in assignments:
            task_id = str(assignment.get("task_id") or "")
            if not task_id:
                continue
            if task_id in agent_by_task:
                assignment["agent_id"] = assignment.get("agent_id") or agent_by_task[task_id]
                assignment["status"] = TASK_STATUS_RUNNING
            seen_task_ids.add(task_id)

        for agent_id, task_id in active_pool_assignments.items():
            if task_id in seen_task_ids:
                continue
            assignments.append(
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "agent_name": agent_id,
                    "claimed_paths": [],
                    "status": TASK_STATUS_RUNNING,
                }
            )

        return assignments

    def build_task_snapshot(
        self,
        assignments: List[Dict[str, Any]],
        fallback: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build task counts for workflow state, including deferred tasks."""
        default_counts = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
            "deferred": 0,
        }
        task_counts = {**default_counts, **(fallback or {})}
        if not assignments:
            return task_counts

        status_counts = {key: 0 for key in default_counts if key != "total"}
        for assignment in assignments:
            status = str(assignment.get("status") or TASK_STATUS_PENDING)
            bucket = self.snapshot_bucket_for_status(status)
            if bucket:
                status_counts[bucket] += 1

        task_counts.update({"total": len(assignments), **status_counts})
        return task_counts

    @staticmethod
    def snapshot_bucket_for_status(status: str) -> Optional[str]:
        normalized = str(status or TASK_STATUS_PENDING)
        if normalized in {TASK_STATUS_COMPLETED, TASK_STATUS_COMPLETED_BY_OVERRIDE, _WTS.ARCHIVED.value}:
            return "completed"
        if normalized in {TASK_STATUS_FAILED, _WTS.BLOCKED.value, _WTS.CANCELLED.value}:
            return "failed"
        if normalized in {TASK_STATUS_RUNNING, _WTS.ASSIGNED.value, _WTS.VERIFYING.value}:
            return "running"
        if normalized in {TASK_STATUS_PENDING, _WTS.PLANNED.value, _WTS.READY.value}:
            return "pending"
        if normalized == TASK_STATUS_DEFERRED:
            return "deferred"
        return None

    def build_engine_state_assignments(
        self,
        workflow_id: str,
        engine_tasks: List[TaskState],
    ) -> List[Dict[str, Any]]:
        scoped_tasks = engine_tasks if not workflow_id else [ts for ts in engine_tasks if ts.workflow_id == workflow_id]
        assignments: List[Dict[str, Any]] = []
        for task_state in scoped_tasks:
            assignments.append(self._owner._serialize_assignment(self._assignment_for_task(task_state)))
        return assignments

    @staticmethod
    def _assignment_for_task(task_state: TaskState) -> Dict[str, Any]:
        return {
            "task_id": task_state.task.id,
            "task_title": task_state.task.title,
            "title": task_state.task.title,
            "task_type": task_state.task.type,
            "task_ref": task_state.task,
            "workflow_id": task_state.workflow_id,
            "status": task_state.status.value,
            "agent_id": task_state.agent_id,
            "assigned_by": getattr(task_state, "assigned_by", ""),
            "assigned_at": getattr(task_state, "assigned_at", None),
            "attempt_id": getattr(task_state, "attempt_id", ""),
            "claimed_paths": list(task_state.task.claimed_paths or []),
            "batch_id": task_state.batch_id,
        }

    def get_workflow_state(self, workflow_id: str) -> Dict[str, Any]:
        """Get current state of a workflow from the engine projection."""
        progress = self._owner.reporter.summarize_progress()
        engine_tasks = self._owner._list_engine_tasks(workflow_id)
        all_engine_tasks = engine_tasks if workflow_id else self._owner._list_engine_tasks()
        kind = "idle" if not all_engine_tasks else progress.get("status", "idle")
        assignments = self.build_engine_state_assignments(workflow_id, all_engine_tasks)

        snapshot = {
            "batches": progress.get("batches", {"total": 0, "completed": 0}),
            "tasks": self.build_task_snapshot(assignments, None),
            "duration": progress.get("duration", {"workflow_seconds": 0, "batch_seconds": 0}),
            "recent_events": progress.get("recent_events", []),
            "assignments": assignments,
        }
        active = bool(all_engine_tasks) if not workflow_id else bool(engine_tasks)
        return {
            "kind": kind,
            "reason_code": "",
            "snapshot": snapshot,
            "workflow_id": workflow_id or progress.get("workflow_id", ""),
            "active": active,
        }
