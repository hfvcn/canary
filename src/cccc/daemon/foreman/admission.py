"""Batch admission control — single-writer deferral, cross-workflow pressure.

Extracted from workflow_orchestrator.py as a pure refactor (RO-31).
These are module-level helpers called by WorkflowOrchestrator methods.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Set

from ...contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
)
from ...kernel.workflow_state_types import (
    TaskState,
    WorkflowTaskStatus as _WTS,
)
from ...kernel.claimed_paths import (
    GLOBAL_WRITE_CLAIM,
    any_overlap as _any_overlap,
    normalize_write_set as _normalize_write_set_fn,
    paths_overlap as _paths_overlap,
)
from .agent_pool import TaskAssignment
from .workflow import BatchEvaluationResult


SINGLE_WRITER_REASON = "single_writer_active"
EXTERNAL_PRESSURE_REASON = "external_workflow_pressure"
CROSS_WORKFLOW_ACTIVE_WINDOW_SECONDS = 300
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_DEFERRED = _WTS.DEFERRED.value

_TERMINAL_STATUSES = frozenset({
    _WTS.COMPLETED,
    _WTS.FAILED,
    _WTS.ARCHIVED,
})


# ---------------------------------------------------------------------------
# Single-writer deferral
# ---------------------------------------------------------------------------

def collect_running_claimed_paths(
    running_assignments: List[Dict[str, Any]],
    extract_fn: Callable[[Dict[str, Any]], List[str]],
    claims_global_fn: Callable[[Any], bool],
) -> Optional[Set[str]]:
    """Collect claimed paths from running assignments.

    Returns None if any assignment claims the global write sentinel.
    """
    running_paths: Set[str] = set()
    for assignment in running_assignments:
        claimed_paths = extract_fn(assignment)
        if claims_global_fn(claimed_paths):
            return None
        running_paths.update(claimed_paths)
    return running_paths


def split_single_writer_tasks(
    tasks: List[TaskRef],
    running_paths: Set[str],
    extract_fn: Callable[[TaskRef], List[str]],
    claims_global_fn: Callable[[Any], bool],
) -> tuple[List[TaskRef], List[TaskRef]]:
    """Split tasks into (safe_tasks, deferred_tasks) based on path conflicts."""
    safe_tasks: List[TaskRef] = []
    deferred_tasks: List[TaskRef] = []
    for task in tasks:
        claimed_paths = set(extract_fn(task))
        if claims_global_fn(claimed_paths) or _any_overlap(claimed_paths, running_paths):
            deferred_tasks.append(task)
            continue
        safe_tasks.append(task)
    return safe_tasks, deferred_tasks


def build_deferred_result(
    suggestion: ReadyBatchSuggestion,
    deferred_assignments: List[TaskAssignment],
    reason: str,
) -> BatchEvaluationResult:
    """Build a BatchEvaluationResult for a fully deferred batch."""
    return BatchEvaluationResult(
        suggestion=suggestion,
        assignments=deferred_assignments,
        decision="deferred",
        reason=reason,
    )


def record_deferred_tasks(
    engine: Any,
    tasks: List[TaskRef],
    reason: str,
) -> List[TaskAssignment]:
    """Record task deferrals in the engine and return assignments."""
    deferred_assignments: List[TaskAssignment] = []
    for task in tasks:
        try:
            engine.defer_task(task.id, reason)
        except ValueError:
            pass  # Task may already be deferred
        deferred_assignments.append(
            TaskAssignment(
                task=task,
                agent_id="",
                agent_name="",
                assignment_reason=reason,
            )
        )
    return deferred_assignments


# ---------------------------------------------------------------------------
# Cross-workflow pressure
# ---------------------------------------------------------------------------

def _find_overlapping_external_owners(
    task_paths: Set[str],
    external_path_owners: Dict[str, List[TaskState]],
) -> Dict[str, List[TaskState]]:
    overlapping: Dict[str, List[TaskState]] = {}
    for task_path in task_paths:
        owners: List[TaskState] = []
        for external_path, external_owners in external_path_owners.items():
            if _paths_overlap(task_path, external_path):
                owners.extend(external_owners)
        if owners:
            overlapping[task_path] = owners
    return overlapping


def _owner_overlaps_path(
    task_path: str,
    owner: TaskState,
    external_path_owners: Dict[str, List[TaskState]],
) -> bool:
    owner_key = (owner.workflow_id, owner.task.id)
    for external_path, owners in external_path_owners.items():
        if not _paths_overlap(task_path, external_path):
            continue
        if any((candidate.workflow_id, candidate.task.id) == owner_key for candidate in owners):
            return True
    return False


def _build_competing_refs(
    task_paths: Set[str],
    overlapping: Dict[str, List[TaskState]],
    external_path_owners: Dict[str, List[TaskState]],
    now: float,
) -> List[Dict[str, Any]]:
    seen_refs: set[str] = set()
    refs: List[Dict[str, Any]] = []
    for owners in overlapping.values():
        for owner in owners:
            ref_key = f"{owner.workflow_id}:{owner.task.id}"
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            ts_max = max(owner.started_at or 0.0, owner.last_heartbeat or 0.0)
            heartbeat_age_ms = int((now - ts_max) * 1000) if ts_max > 0 else -1
            refs.append({
                "workflow_id": owner.workflow_id,
                "task_id": owner.task.id,
                "overlapping_paths": [
                    path for path in sorted(task_paths)
                    if _owner_overlaps_path(path, owner, external_path_owners)
                ],
                "heartbeat_age_ms": heartbeat_age_ms,
            })
    return refs

def get_active_external_tasks(
    engine: Any,
    exclude_workflow_id: str,
    now: float,
    window: int = CROSS_WORKFLOW_ACTIVE_WINDOW_SECONDS,
) -> List[TaskState]:
    """Return tasks from *other* non-terminal workflows that are still active.

    A workflow is "active" if it has at least one task whose
    ``max(started_at, last_heartbeat)`` is within *window* seconds of *now*.
    Terminal workflows (all tasks completed/failed/archived) are excluded.
    """
    all_tasks = engine.list_tasks()
    # Group tasks by workflow_id
    by_wf: Dict[str, List[TaskState]] = {}
    for ts in all_tasks:
        by_wf.setdefault(ts.workflow_id, []).append(ts)

    active_external: List[TaskState] = []
    for wf_id, wf_tasks in by_wf.items():
        if wf_id == exclude_workflow_id:
            continue
        # Skip terminal workflows (every task terminal)
        if all(t.status in _TERMINAL_STATUSES for t in wf_tasks):
            continue
        # Check if at least one task has a recent heartbeat / start
        has_active = False
        for t in wf_tasks:
            ts_max = max(
                t.started_at or 0.0,
                t.last_heartbeat or 0.0,
            )
            if ts_max > 0 and (now - ts_max) <= window:
                has_active = True
                break
        if not has_active:
            continue
        active_external.extend(wf_tasks)
    return active_external


def compute_cross_workflow_deferrals(
    suggestion: ReadyBatchSuggestion,
    external_tasks: List[TaskState],
    extract_fn: Callable[[TaskRef], List[str]],
) -> tuple[List[TaskRef], List[TaskRef], Dict[str, List[Dict[str, Any]]]]:
    """Split tasks into safe/deferred based on cross-workflow path overlap.

    Returns (safe_tasks, deferred_tasks, deferred_competing_refs).
    """
    now = time.time()

    # Build set of claimed paths and their provenance from external tasks
    external_path_owners: Dict[str, List[TaskState]] = {}
    for ts in external_tasks:
        for p in extract_fn(ts.task):
            external_path_owners.setdefault(p, []).append(ts)

    if not external_path_owners:
        return list(suggestion.tasks), [], {}

    safe_tasks: List[TaskRef] = []
    deferred_tasks: List[TaskRef] = []
    deferred_competing: Dict[str, List[Dict[str, Any]]] = {}

    for task in suggestion.tasks:
        task_paths = set(extract_fn(task))
        overlapping = _find_overlapping_external_owners(task_paths, external_path_owners)
        if not overlapping:
            safe_tasks.append(task)
            continue
        deferred_tasks.append(task)
        deferred_competing[task.id] = _build_competing_refs(
            task_paths,
            overlapping,
            external_path_owners,
            now,
        )

    return safe_tasks, deferred_tasks, deferred_competing


# ---------------------------------------------------------------------------
# Group actor fallback
# ---------------------------------------------------------------------------

def build_group_actor_assignment(
    task: TaskRef,
    actor: Dict[str, Any],
) -> TaskAssignment:
    """Build a TaskAssignment from a group actor dict."""
    actor_id = str(actor.get("id") or "").strip()
    actor_name = str(actor.get("title") or actor_id).strip() or actor_id
    return TaskAssignment(
        task=task,
        agent_id=actor_id,
        agent_name=actor_name,
        is_new_agent=False,
        assignment_reason="group_actor_fallback",
        model_runtime=str(actor.get("runtime") or "").strip(),
    )


def build_fallback_result(
    suggestion: ReadyBatchSuggestion,
    peer_actors: List[Dict[str, Any]],
) -> BatchEvaluationResult:
    """Build a BatchEvaluationResult using group peer actors as fallback."""
    assignments = [
        build_group_actor_assignment(task, peer_actors[index % len(peer_actors)])
        for index, task in enumerate(suggestion.tasks)
    ]
    return BatchEvaluationResult(
        suggestion=suggestion,
        decision="approved",
        reason=f"Assigned to {len(peer_actors)} group peer actors (pool fallback)",
        assignments=assignments,
        approved_tasks=list(suggestion.tasks),
        rejected_tasks=[],
    )
