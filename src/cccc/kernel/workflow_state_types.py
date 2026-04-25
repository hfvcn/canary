from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from ..contracts.v1.ralph_ipc import TaskRef


WORKFLOW_ENGINE_ACTOR = "service:workflow_engine"

KIND_TASK_REGISTERED = "workflow.task_registered"
KIND_BATCH_REGISTERED = "workflow.batch_registered"
KIND_BATCH_APPROVED = "workflow.batch_approved"
KIND_TASK_STARTED = "workflow.task_started"
KIND_TASK_HEARTBEAT = "workflow.task_heartbeat"
KIND_TASK_REPORTED_COMPLETED = "workflow.task_reported_completed"
KIND_TASK_FAILED = "workflow.task_failed"
KIND_VERIFICATION_PASSED = "workflow.verification_passed"
KIND_VERIFICATION_SKIPPED = "workflow.verification_skipped"
KIND_VERIFICATION_FAILED = "workflow.verification_failed"
KIND_RETRY_REQUESTED = "workflow.retry_requested"
KIND_TASK_BLOCKED = "workflow.task_blocked"
KIND_VERIFICATION_WARNING = "workflow.verification_warning"
KIND_MONITOR_VIOLATION = "workflow.monitor_violation"
KIND_RALPH_INTERNAL_ERROR = "workflow.ralph_internal_error"
KIND_TASK_DEFERRED = "workflow.task_deferred"
KIND_PLAN_DIGEST_DIVERGENCE = "workflow.plan_digest_divergence"
KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC = "workflow.plan_digest_divergence_post_hoc"
KIND_TRANSITION_REJECTED = "workflow.transition_rejected"
KIND_MONITOR_MODE_CHANGED = "workflow.monitor_mode_changed"
KIND_VERIFICATION_AGENT_PENDING = "workflow.verification_agent_pending"


class WorkflowTaskStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    ARCHIVED = "archived"


class PreTransitionVetoed(RuntimeError):
    """Raised by a pre-transition hook to block a state transition."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkflowMeta:
    """Per-workflow metadata tracked by the engine."""

    workflow_id: str
    plan_path: str = ""
    plan_digest: str = ""


@dataclass(frozen=True, slots=True)
class TaskState:
    task: TaskRef
    workflow_id: str
    status: WorkflowTaskStatus
    batch_id: str = ""
    agent_id: str = ""
    attempt_id: str = ""
    assigned_by: str = ""
    assigned_at: Optional[float] = None
    last_completion_idempotency_key: str = ""
    last_verification: Optional[Dict[str, Any]] = None
    last_heartbeat: Optional[float] = None
    progress_pct: Optional[int] = None
    blocked_reason: str = ""
    started_at: Optional[float] = None


class TransitionRejected(Exception):
    """Engine pre-transition hook rejected a state transition."""

    def __init__(self, alert_type: str, message: str, evidence: dict | None = None):
        self.alert_type = alert_type
        self.message = message
        self.evidence = evidence or {}
        super().__init__(message)


if TYPE_CHECKING:
    from .workflow_state_engine import WorkflowEngine

PreTransitionHook = Callable[[str, dict, "WorkflowEngine"], None]
