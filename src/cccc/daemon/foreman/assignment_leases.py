"""Agent lease helpers for foreman assignment flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ...contracts.v1.agent_lease import AgentAcquireRequest, AssignmentPolicy


DEFAULT_LEASE_ROLE = "worker"
EXPLICIT_ASSIGNMENT_MODE = "explicit"
LEASE_COMPLETED_OUTCOME = "completed"


@dataclass(frozen=True)
class AssignmentLeaseAcquireContext:
    owner: Any
    task: Any
    agent_id: str
    model_key: str


def acquire_assignment_lease(context: AssignmentLeaseAcquireContext) -> None:
    acquire = _pool_method(context.owner, "acquire")
    if acquire is None:
        return
    lease = acquire(_build_acquire_request(context))
    _owner_task_leases(context.owner)[context.task.id] = lease


def release_assignment_lease(
    owner: Any,
    task_id: str,
    outcome: str = LEASE_COMPLETED_OUTCOME,
) -> None:
    release = _pool_method(owner, "release")
    leases = getattr(owner, "_task_leases", None)
    if release is None or not leases or task_id not in leases:
        return
    lease = leases[task_id]
    release(lease, outcome)
    leases.pop(task_id, None)


def _build_acquire_request(context: AssignmentLeaseAcquireContext) -> AgentAcquireRequest:
    workflow_id = _workflow_id_for_task(context.owner, context.task.id)
    return AgentAcquireRequest(
        run_id=_run_id_for(context.owner, workflow_id),
        workflow_id=workflow_id,
        node_id=context.task.id,
        task=context.task,
        attempt_id=str(getattr(context.task, "attempt_id", "") or ""),
        group_id=str(getattr(context.owner, "group_id", "") or ""),
        project_root=str(getattr(context.owner, "project_root", "") or ""),
        assignment_policy=_assignment_policy_for(context),
    )


def _assignment_policy_for(context: AssignmentLeaseAcquireContext) -> AssignmentPolicy:
    return AssignmentPolicy(
        mode=EXPLICIT_ASSIGNMENT_MODE,
        explicit_actor_id=context.agent_id,
        required_role=str(getattr(context.task, "role", "") or DEFAULT_LEASE_ROLE),
        preferred_model_key=context.model_key,
    )


def _pool_method(owner: Any, method_name: str) -> Callable[..., Any] | None:
    pool_manager = getattr(owner, "_pool_manager", None)
    method = getattr(pool_manager, method_name, None)
    if not callable(method):
        return None
    return method


def _owner_task_leases(owner: Any) -> dict[str, Any]:
    leases = getattr(owner, "_task_leases", None)
    if leases is None:
        leases = {}
        owner._task_leases = leases
    return leases


def _workflow_id_for_task(owner: Any, task_id: str) -> str:
    for workflow_id, workflow_data in getattr(owner, "_active_workflows", {}).items():
        if task_id in workflow_data.get("tasks", {}):
            return str(workflow_id)
    return ""


def _run_id_for(owner: Any, workflow_id: str) -> str:
    return str(
        getattr(owner, "run_id", "")
        or getattr(owner, "_run_id", "")
        or workflow_id
    )
