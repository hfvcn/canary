"""Workflow submit guards for existing task ids."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from ...contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from .workflow import BatchEvaluationResult

RETRY_HINT = "Use 'cccc workflow retry' instead"


class _WorkflowTaskState(Protocol):
    status: object


GetTask = Callable[[str], _WorkflowTaskState | None]


class TasksAlreadyExistError(ValueError):
    """Raised when workflow submit receives task ids already known to engine."""

    def __init__(self, existing_ids: list[str]) -> None:
        self.existing_ids = list(existing_ids)
        super().__init__(tasks_already_exist_reason(self.existing_ids))


_BATCHABLE_STATUSES: frozenset[str] = frozenset({"planned", "ready", "failed", "deferred"})
_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "archived"})


def find_existing_task_ids(
    task_refs: Iterable[TaskRef],
    get_task: GetTask,
    *,
    allowed_task_ids: set[str] | None = None,
) -> list[str]:
    """Find tasks that exist in an active (non-batchable, non-terminal) state.

    Tasks in batchable states (planned/ready/failed/deferred) or terminal
    states (completed/archived) are NOT considered conflicts — only tasks
    in active states (assigned/running/verifying) trigger rejection.
    """
    allowed = allowed_task_ids or set()
    existing_ids = []
    for task_ref in task_refs:
        if task_ref.id in allowed:
            continue
        state = get_task(task_ref.id)
        if state is None or state.status is None:
            continue
        status_val = str(state.status.value if hasattr(state.status, "value") else state.status)
        if status_val in _BATCHABLE_STATUSES or status_val in _TERMINAL_STATUSES:
            continue
        existing_ids.append(task_ref.id)
    return existing_ids


def tasks_already_exist_reason(existing_ids: list[str]) -> str:
    return f"tasks_already_exist: {existing_ids}. {RETRY_HINT}"


def reject_if_tasks_already_exist(
    suggestion: ReadyBatchSuggestion,
    get_task: GetTask,
    *,
    allowed_task_ids: set[str] | None = None,
) -> BatchEvaluationResult | None:
    existing_ids = find_existing_task_ids(
        suggestion.tasks,
        get_task,
        allowed_task_ids=allowed_task_ids,
    )
    if not existing_ids:
        return None
    return BatchEvaluationResult(
        suggestion=suggestion,
        approved_tasks=[],
        rejected_tasks=list(suggestion.tasks),
        assignments=[],
        decision="rejected",
        reason=tasks_already_exist_reason(existing_ids),
    )


def ensure_tasks_are_new(task_refs: Iterable[TaskRef], get_task: GetTask) -> None:
    existing_ids = find_existing_task_ids(task_refs, get_task)
    if existing_ids:
        raise TasksAlreadyExistError(existing_ids)


MIXED_WORKFLOW_IDS_REASON = "mixed_workflow_ids: tasks belong to different workflows"


class MixedWorkflowIdsError(ValueError):
    def __init__(self) -> None:
        super().__init__(MIXED_WORKFLOW_IDS_REASON)


def resolve_workflow_id_for_tasks(
    task_refs: Iterable[TaskRef],
    workflow_id: str,
    get_task: GetTask,
) -> str:
    """Resolve canonical workflow_id for batchable tasks that already exist."""
    existing_workflow_ids: set[str] = set()
    for task in task_refs:
        state = get_task(task.id)
        if state is not None and hasattr(state, "workflow_id"):
            existing_workflow_ids.add(state.workflow_id)
    if len(existing_workflow_ids) > 1:
        raise MixedWorkflowIdsError()
    if len(existing_workflow_ids) != 1:
        return workflow_id
    existing_wf = next(iter(existing_workflow_ids))
    if existing_wf == workflow_id:
        return workflow_id
    import logging
    logging.getLogger(__name__).info(
        "resubmit: reusing existing workflow_id=%s instead of %s",
        existing_wf, workflow_id,
    )
    return existing_wf


def resolve_suggestion_workflow_id_for_resubmit(
    suggestion: ReadyBatchSuggestion,
    get_task: GetTask,
) -> tuple[ReadyBatchSuggestion, BatchEvaluationResult | None]:
    try:
        workflow_id = resolve_workflow_id_for_tasks(
            suggestion.tasks, suggestion.workflow_id, get_task,
        )
    except MixedWorkflowIdsError:
        return suggestion, BatchEvaluationResult(
            suggestion=suggestion,
            approved_tasks=[],
            rejected_tasks=list(suggestion.tasks),
            assignments=[],
            decision="rejected",
            reason=MIXED_WORKFLOW_IDS_REASON,
        )
    if workflow_id == suggestion.workflow_id:
        return suggestion, None
    return suggestion.model_copy(update={"workflow_id": workflow_id}), None
