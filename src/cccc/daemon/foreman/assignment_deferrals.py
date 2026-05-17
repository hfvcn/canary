"""Assignment deferral helpers for WorkflowOrchestrator."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from ...kernel.claimed_paths import (
    GLOBAL_WRITE_CLAIM,
    normalize_path as _normalize_path_fn,
    normalize_write_set as _normalize_write_set_fn,
)
from ...kernel.workflow_state_types import TaskState, WorkflowTaskStatus
from .admission import (
    build_deferred_result as _build_deferred_result,
    collect_running_claimed_paths,
    compute_cross_workflow_deferrals,
    get_active_external_tasks,
    record_deferred_tasks,
    split_single_writer_tasks,
)
from .agent_pool import TaskAssignment
from .assignment_constants import (
    EXTERNAL_PRESSURE_REASON,
    SINGLE_WRITER_REASON,
    TASK_STATUS_DEFERRED,
    TASK_STATUS_RUNNING,
)
from .workflow import BatchEvaluationResult

DEFERRED_ACTION_RETRY_WORKER = "retry_worker"
DEFERRED_ACTION_RETRY_VERIFIER = "retry_verifier"
DEFERRED_ACTION_FOREMAN_ACCEPT = "foreman_accept"
DEFERRED_ACTION_CANCEL = "cancel"
DEFERRED_RECOVERY_ACTIONS = frozenset(
    {
        DEFERRED_ACTION_RETRY_WORKER,
        DEFERRED_ACTION_RETRY_VERIFIER,
        DEFERRED_ACTION_FOREMAN_ACCEPT,
        DEFERRED_ACTION_CANCEL,
    }
)


class AssignmentDeferralMixin:
    """Handles single-writer and cross-workflow assignment deferrals."""

    def recover_deferred_task(
        self,
        task_id: str,
        action: str,
        *,
        reason: str = "",
        evidence: Any = None,
        assign_agent_id: str = "",
        changed_files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        tid = self._require_deferred_task_id(task_id)
        action_name = self._normalize_recovery_action(action)
        if action_name == DEFERRED_ACTION_RETRY_WORKER:
            result = self._owner.retry_worker(tid, assign_agent_id=assign_agent_id)
        elif action_name == DEFERRED_ACTION_RETRY_VERIFIER:
            result = self._owner.retry_verifier(tid, changed_files=changed_files)
        elif action_name == DEFERRED_ACTION_FOREMAN_ACCEPT:
            result = self._owner.foreman_accept(tid, reason, evidence)
        elif action_name == DEFERRED_ACTION_CANCEL:
            result = self._owner.cancel_task(tid, reason)
        else:
            raise AssertionError(f"unreachable deferred recovery action: {action_name}")
        return {**result, "recovery_action": action_name}

    def _require_deferred_task_id(self, task_id: str) -> str:
        tid = str(task_id or "").strip()
        if not tid:
            raise ValueError("task_id is required")
        state = self._owner.engine.get_task(tid)
        if state is None:
            raise ValueError(f"task not found: {tid}")
        if state.status != WorkflowTaskStatus.DEFERRED:
            raise ValueError(f"task not deferred: {tid} status={state.status.value}")
        return tid

    @staticmethod
    def _normalize_recovery_action(action: str) -> str:
        action_name = str(action or "").strip()
        if action_name not in DEFERRED_RECOVERY_ACTIONS:
            raise ValueError(f"unsupported deferred recovery action: {action_name}")
        return action_name

    def defer_batch_for_single_writer(
        self,
        suggestion: ReadyBatchSuggestion,
    ) -> Optional[BatchEvaluationResult]:
        running_assignments = [
            assignment
            for assignment in self._owner._get_all_assignments()
            if assignment.get("status") == TASK_STATUS_RUNNING
        ]
        if not running_assignments:
            return None

        running_paths = collect_running_claimed_paths(
            running_assignments,
            self.extract_assignment_claimed_paths,
            self.claims_global_write,
        )
        if running_paths is None:
            return self.build_deferred_result(suggestion, suggestion.tasks)
        return self._defer_conflicting_single_writer_tasks(suggestion, running_paths)

    def _defer_conflicting_single_writer_tasks(
        self,
        suggestion: ReadyBatchSuggestion,
        running_paths: set[str],
    ) -> Optional[BatchEvaluationResult]:
        safe_tasks, deferred_tasks = split_single_writer_tasks(
            suggestion.tasks,
            running_paths,
            self.extract_claimed_paths,
            self.claims_global_write,
        )
        if not deferred_tasks:
            return None
        if not safe_tasks:
            return self.build_deferred_result(suggestion, deferred_tasks)

        self.record_deferred_tasks(suggestion.workflow_id, deferred_tasks)
        suggestion.tasks = safe_tasks
        suggestion.estimated_parallelism = len(safe_tasks)
        self._owner._log(
            f"[orchestrator] Allowing {len(safe_tasks)} tasks from batch "
            f"{suggestion.suggestion_id}; deferred {len(deferred_tasks)} due to single-writer conflicts"
        )
        return None

    def build_deferred_result(
        self,
        suggestion: ReadyBatchSuggestion,
        tasks: List[TaskRef],
    ) -> BatchEvaluationResult:
        deferred_assignments = self.record_deferred_tasks(suggestion.workflow_id, tasks)
        self._owner._log(
            f"[orchestrator] Deferring batch {suggestion.suggestion_id} due to active single-writer assignment"
        )
        return _build_deferred_result(suggestion, deferred_assignments, SINGLE_WRITER_REASON)

    def record_deferred_tasks(
        self,
        workflow_id: str,
        tasks: List[TaskRef],
    ) -> List[TaskAssignment]:
        deferred_assignments = record_deferred_tasks(self._owner.engine, tasks, SINGLE_WRITER_REASON)
        self._release_deferred_task_agents(tasks)
        return deferred_assignments

    def _release_deferred_task_agents(self, tasks: List[TaskRef]) -> None:
        for task in tasks:
            self._owner._release_agent_for_task(task.id)

    def get_active_external_tasks(
        self,
        exclude_workflow_id: str,
        now: float,
    ) -> List[TaskState]:
        """Return tasks from *other* non-terminal workflows that are still active."""
        return get_active_external_tasks(self._owner.engine, exclude_workflow_id, now)

    def defer_batch_for_cross_workflow_pressure(
        self,
        suggestion: ReadyBatchSuggestion,
    ) -> Optional[BatchEvaluationResult]:
        external_tasks = self.get_active_external_tasks(suggestion.workflow_id, time.time())
        if not external_tasks:
            return None

        safe_tasks, deferred_tasks, _deferred_competing = compute_cross_workflow_deferrals(
            suggestion,
            external_tasks,
            self.extract_claimed_paths,
        )
        if not deferred_tasks:
            return None
        return self._apply_cross_workflow_deferral(suggestion, safe_tasks, deferred_tasks)

    def _apply_cross_workflow_deferral(
        self,
        suggestion: ReadyBatchSuggestion,
        safe_tasks: List[TaskRef],
        deferred_tasks: List[TaskRef],
    ) -> Optional[BatchEvaluationResult]:
        deferred_assignments = self._record_cross_workflow_deferred_tasks(suggestion, deferred_tasks)
        if not safe_tasks:
            self._owner._log(
                f"[orchestrator] Deferring entire batch {suggestion.suggestion_id} "
                f"due to cross-workflow pressure"
            )
            return BatchEvaluationResult(
                suggestion=suggestion,
                assignments=deferred_assignments,
                decision="deferred",
                reason=EXTERNAL_PRESSURE_REASON,
            )
        suggestion.tasks = safe_tasks
        suggestion.estimated_parallelism = len(safe_tasks)
        self._owner._log(
            f"[orchestrator] Allowing {len(safe_tasks)} tasks; "
            f"deferred {len(deferred_tasks)} due to cross-workflow pressure"
        )
        return None

    def _record_cross_workflow_deferred_tasks(
        self,
        suggestion: ReadyBatchSuggestion,
        deferred_tasks: List[TaskRef],
    ) -> List[TaskAssignment]:
        deferred_assignments: List[TaskAssignment] = []
        for task in deferred_tasks:
            self._owner._track_task_ref(
                suggestion.workflow_id,
                task,
                status=TASK_STATUS_DEFERRED,
                reason=EXTERNAL_PRESSURE_REASON,
            )
            try:
                self._owner.engine.defer_task(task.id, EXTERNAL_PRESSURE_REASON)
            except ValueError:
                pass
            self._owner._release_agent_for_task(task.id)
            deferred_assignments.append(self._deferred_assignment(task))
        return deferred_assignments

    @staticmethod
    def _deferred_assignment(task: TaskRef) -> TaskAssignment:
        return TaskAssignment(
            task=task,
            agent_id="",
            agent_name="",
            assignment_reason=EXTERNAL_PRESSURE_REASON,
        )

    def extract_claimed_paths(self, task: TaskRef) -> List[str]:
        return self.normalize_claimed_paths(getattr(task, "claimed_paths", []) or [])

    def extract_assignment_claimed_paths(self, assignment: Dict[str, Any]) -> List[str]:
        return self.normalize_claimed_paths(assignment.get("claimed_paths") or [])

    @staticmethod
    def claims_global_write(claimed_paths: set[str] | List[str]) -> bool:
        return not claimed_paths or GLOBAL_WRITE_CLAIM in claimed_paths

    @staticmethod
    def normalize_claimed_paths(claimed_paths: List[str]) -> List[str]:
        return _normalize_write_set_fn(claimed_paths)

    @staticmethod
    def normalize_claimed_path(path: str) -> str:
        return _normalize_path_fn(path)
