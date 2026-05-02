"""Control-plane sync helpers for assignment decisions."""

from __future__ import annotations

from typing import Any, Dict, List

from ...contracts.v1 import DaemonRequest
from .agent_pool import TaskAssignment
from .assignment_constants import ORCHESTRATOR_SERVICE_ACTOR
from .workflow import BatchEvaluationResult


class AssignmentControlPlaneMixin:
    """Mirrors Ralph batch decisions into shared coordination state."""

    def sync_batch_to_control_plane(self, result: BatchEvaluationResult) -> None:
        """Mirror Ralph batch decisions into shared coordination/task state."""
        if not self._owner._daemon_request_fn:
            return
        suggestion = result.suggestion
        workflow_state = self._owner._active_workflows.get(suggestion.workflow_id) if suggestion.workflow_id else None
        synced = workflow_state.get("synced_batches") if isinstance(workflow_state, dict) else None
        if isinstance(synced, set) and suggestion.suggestion_id in synced:
            return
        self._dispatch_context_sync(result, synced)

    def _dispatch_context_sync(
        self,
        result: BatchEvaluationResult,
        synced: Any,
    ) -> None:
        batch_id = result.suggestion.suggestion_id
        try:
            req = DaemonRequest(
                op="context_sync",
                args={
                    "group_id": self._owner.group_id,
                    "by": ORCHESTRATOR_SERVICE_ACTOR,
                    "ops": self._build_context_sync_ops(result),
                },
            )
            resp, _ = self._owner._daemon_request_fn(req)
            if resp.ok and isinstance(synced, set):
                synced.add(batch_id)
            elif not resp.ok:
                err_msg = resp.error.message if resp.error else "unknown"
                self._owner._log(f"[orchestrator] Failed to sync batch {batch_id} to control plane: {err_msg}")
        except Exception as exc:
            self._owner._log(f"[orchestrator] Error syncing batch {batch_id} to control plane: {exc}")

    def _build_context_sync_ops(self, result: BatchEvaluationResult) -> List[Dict[str, Any]]:
        suggestion = result.suggestion
        approved_ids = {task.id for task in result.approved_tasks}
        ops = [
            self._context_task_create_op(suggestion.workflow_id, suggestion.suggestion_id, assignment, approved_ids)
            for assignment in result.assignments
        ]
        ops.append(
            {
                "op": "coordination.note.add",
                "kind": "decision",
                "summary": (
                    f"Ralph batch {suggestion.suggestion_id}: decision={result.decision}, "
                    f"approved={len(result.approved_tasks)}, rejected={len(result.rejected_tasks)}"
                ),
            }
        )
        return ops

    @staticmethod
    def _context_task_create_op(
        workflow_id: str,
        batch_id: str,
        assignment: TaskAssignment,
        approved_ids: set[str],
    ) -> Dict[str, Any]:
        task = assignment.task
        status = "active" if task.id in approved_ids and assignment.agent_id else "blocked"
        notes = (
            f"ralph_workflow={workflow_id}\n"
            f"ralph_batch={batch_id}\n"
            f"ralph_task={task.id}\n"
            f"task_type={task.type}\n"
            f"assignment_reason={assignment.assignment_reason}"
        )
        return {
            "op": "task.create",
            "title": task.title,
            "outcome": f"Ralph task {task.id} ({task.type})",
            "status": status,
            "assignee": assignment.agent_id or None,
            "notes": notes,
            "workflow_task_id": task.id,
        }
