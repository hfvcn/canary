"""
Ralph-Daemon IPC message contracts.

Defines the message models for communication between Ralph (CI/CD orchestrator)
and CCCC Daemon. Uses the existing Daemon IPC infrastructure (Unix socket + JSON line).

Message types:
- ReadyBatchSuggestion: Ralph suggests a batch of tasks ready for parallel execution
- VerificationResult: Verification (build/test/lint) outcome from Ralph
- RestartSuggestion: Ralph suggests restarting a failed/stuck task
- BatchDecision: Foreman's decision on a suggested batch
- ActorStatus: Status update from an actor (Ralph or other agents)
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ...util.time import utc_now_iso


# Status types for actors in the Ralph workflow
ActorStatusType = Literal[
    "idle",           # Ready but not actively working
    "analyzing",      # Analyzing task/code
    "executing",      # Executing task
    "waiting",        # Waiting for external input/approval
    "blocked",        # Blocked on dependency or error
    "completed",      # Finished current work
]

# Decision types for batch suggestions
BatchDecisionType = Literal[
    "approved",       # Batch approved as-is
    "modified",       # Batch modified (some tasks approved, some rejected)
    "rejected",       # Entire batch rejected
    "deferred",       # Decision deferred, try again later
]

# Verification outcome types
VerificationOutcome = Literal[
    "passed",         # All checks passed
    "failed",         # One or more checks failed
    "skipped",        # Verification was skipped
    "timeout",        # Verification timed out
]


class TaskRef(BaseModel):
    """Reference to a task in the workflow."""
    id: str
    title: str = ""
    type: Literal["frontend", "backend", "general"] = "general"

    model_config = ConfigDict(extra="ignore")


class ReadyBatchSuggestion(BaseModel):
    """
    Ralph suggests a batch of tasks that are ready for parallel execution.

    Sent by Ralph to Foreman when it identifies tasks whose dependencies
    are satisfied and can be executed in parallel.
    """
    v: int = 1
    message_type: Literal["ready_batch_suggestion"] = "ready_batch_suggestion"
    suggestion_id: str  # Unique ID for this suggestion
    workflow_id: str    # ID of the current workflow
    tasks: List[TaskRef] = Field(default_factory=list)
    rationale: str = ""  # Why these tasks are suggested together
    estimated_parallelism: int = 1  # Expected degree of parallelism
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="forbid")


class VerificationCheck(BaseModel):
    """Individual verification check result."""
    name: str           # e.g., "build", "test", "lint", "type-check"
    outcome: VerificationOutcome
    message: str = ""
    duration_ms: int = 0
    details: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class VerificationResult(BaseModel):
    """
    Verification outcome from Ralph after running build/test/lint.

    Sent by Ralph to Foreman after completing verification steps.
    """
    v: int = 1
    message_type: Literal["verification_result"] = "verification_result"
    verification_id: str  # Unique ID for this verification run
    workflow_id: str
    task_id: Optional[str] = None  # Task that triggered verification, if any
    overall_outcome: VerificationOutcome
    checks: List[VerificationCheck] = Field(default_factory=list)
    summary: str = ""
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="forbid")


class RestartSuggestion(BaseModel):
    """
    Ralph suggests restarting a failed or stuck task.

    Sent by Ralph to Foreman when it detects a task that should be retried.
    """
    v: int = 1
    message_type: Literal["restart_suggestion"] = "restart_suggestion"
    suggestion_id: str
    workflow_id: str
    task: TaskRef
    reason: str = ""  # Why restart is suggested
    previous_attempts: int = 0
    files_to_adopt: List[str] = Field(default_factory=list)  # Files from previous attempt
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="forbid")


class BatchDecision(BaseModel):
    """
    Foreman's decision on a suggested batch.

    Sent by Foreman to Ralph in response to a ReadyBatchSuggestion.
    """
    v: int = 1
    message_type: Literal["batch_decision"] = "batch_decision"
    decision_id: str
    suggestion_id: str  # References the original suggestion
    workflow_id: str
    decision: BatchDecisionType
    approved_tasks: List[str] = Field(default_factory=list)  # Task IDs approved
    rejected_tasks: List[str] = Field(default_factory=list)  # Task IDs rejected
    reason: str = ""
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="forbid")


class ActorStatus(BaseModel):
    """
    Status update from an actor (Ralph or other agents).

    Actors periodically report their status to enable coordination.
    """
    v: int = 1
    message_type: Literal["actor_status"] = "actor_status"
    actor_id: str
    actor_type: Literal["ralph", "foreman", "worker", "other"] = "other"
    workflow_id: Optional[str] = None
    status: ActorStatusType
    current_task_id: Optional[str] = None
    message: str = ""
    progress_pct: Optional[int] = None  # 0-100 if applicable
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="forbid")


# Union type for all Ralph IPC messages
RalphIPCMessage = (
    ReadyBatchSuggestion
    | VerificationResult
    | RestartSuggestion
    | BatchDecision
    | ActorStatus
)


def parse_ralph_message(data: Dict[str, Any]) -> RalphIPCMessage:
    """Parse a raw dictionary into the appropriate Ralph IPC message type."""
    msg_type = data.get("message_type", "")
    if msg_type == "ready_batch_suggestion":
        return ReadyBatchSuggestion.model_validate(data)
    elif msg_type == "verification_result":
        return VerificationResult.model_validate(data)
    elif msg_type == "restart_suggestion":
        return RestartSuggestion.model_validate(data)
    elif msg_type == "batch_decision":
        return BatchDecision.model_validate(data)
    elif msg_type == "actor_status":
        return ActorStatus.model_validate(data)
    else:
        raise ValueError(f"Unknown Ralph IPC message type: {msg_type}")
