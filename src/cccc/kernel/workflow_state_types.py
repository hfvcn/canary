from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

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


class WorkflowTaskStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class TaskState:
    task: TaskRef
    workflow_id: str
    status: WorkflowTaskStatus
    batch_id: str = ""
    agent_id: str = ""
    last_completion_idempotency_key: str = ""
    last_verification: Optional[Dict[str, Any]] = None
    last_heartbeat: Optional[float] = None
    progress_pct: Optional[int] = None
    blocked_reason: str = ""
    started_at: Optional[float] = None
