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
    "skipped_blocked",  # Verification was skipped and completion is blocked
    "timeout",        # Verification timed out
    "infra_error",    # Verification infrastructure failed
    "agent_pending",  # Awaiting external agent verification (RA-3)
    "force_passed",   # Force-complete override — verification skipped, task completed
]


class VerificationCheckSpec(BaseModel):
    """Individual verification check specification (e.g., build, test, lint)."""

    name: str
    command: str
    required: bool = True
    expected_exit_code: int = 0
    timeout: Optional[int] = None

    model_config = ConfigDict(extra="ignore")


class MockTestCase(BaseModel):
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)
    expected_output: Dict[str, Any] = Field(default_factory=dict)
    setup_command: str = ""
    verify_command: str = ""
    description: str = ""

    model_config = ConfigDict(extra="ignore")


class VerificationSpec(BaseModel):
    """Structured verification spec — contracts-layer mirror of ralph.models.Verification."""

    level: str = "unit"  # compile, unit, integration, e2e
    command: str = ""
    checks: List[VerificationCheckSpec] = Field(default_factory=list)
    covers_tasks: List[str] = Field(default_factory=list)
    covers_paths: List[str] = Field(default_factory=list)
    covers_flows: List[str] = Field(default_factory=list)
    expected_exit_code: int = 0
    cleanup_patterns: Optional[List[str]] = None
    mock_tests: Optional[List[MockTestCase]] = None


class TaskRef(BaseModel):
    """Reference to a task in the workflow."""
    id: str
    title: str = ""
    type: Literal["frontend", "backend", "general"] = "general"
    depends_on: List[str] = Field(default_factory=list)
    claimed_paths: List[str] = Field(default_factory=list)
    awareness_paths: List[str] = Field(default_factory=list)

    # New (D-10): goal + acceptance
    goal_behavior: str = ""
    acceptance_criteria: str = ""

    # New (D-10/D-11): verification
    verification_command: str = ""  # DEPRECATED — use verification.command
    verification: Optional[VerificationSpec] = None

    # New (D-10): expected I/O (mock-friendly contract)
    expected_input: Dict[str, Any] = Field(default_factory=dict)
    expected_output: Dict[str, Any] = Field(default_factory=dict)

    # WF-4 alignment: fields from TaskSpec (plan schema)
    role: str = ""  # leaf, integration, verification
    verification_mode: str = "ralph"
    provides: List[Dict[str, Any]] = Field(default_factory=list)
    consumes: List[Dict[str, Any]] = Field(default_factory=list)
    addresses: List[str] = Field(default_factory=list)
    failure_path: str = ""
    aegis: Optional[Dict[str, Any]] = None

    # BP-2: module decomposition (advisory, rendered in worker prompt)
    modules: Optional[List[Dict[str, Any]]] = None

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
    # ARCH-1: Foreman-explicit task→actor assignments (empty = agent pool decides)
    assignments: Dict[str, str] = Field(default_factory=dict)
    fallback_allowed: bool = False
    # Worker prompt projection metadata. Values are serialized to keep this IPC
    # layer independent from Ralph implementation classes.
    prompt_issues: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    recommended_tests: Dict[str, List[str]] = Field(default_factory=dict)
    forbidden_flows: List[Dict[str, Any]] = Field(default_factory=list)

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
    warnings: List[str] = Field(default_factory=list)
    summary: str = ""
    challenge_outcome: str = ""
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


class TaskEvent(BaseModel):
    """Unified task lifecycle event for the ralph_task_event daemon op."""
    event_type: Literal["assigned", "started", "heartbeat", "completed", "failed"]
    task_id: str
    assignment_id: str = ""
    actor_run_id: str = ""
    idempotency_key: str = ""
    occurred_at: str = Field(default_factory=utc_now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation issue IPC contract (W4 finding metadata)
# ---------------------------------------------------------------------------

class IpcValidationError(BaseModel):
    """IPC-layer mirror of ralph.models.ValidationIssue.

    Carries the same finding-metadata fields so downstream consumers
    (Foreman prompt injection, UI, etc.) can filter and display issues
    without accessing Ralph internals.
    """
    code: str
    severity: Literal["error", "warning", "hint"]
    message: str
    task_ids: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)

    # W4 finding metadata
    confidence: Literal["exact", "best_effort", "opaque"] = "opaque"
    source: str = ""
    action_owner: Literal["author", "worker", "shared", "unknown"] = "unknown"
    worker_relevance: Literal["blocking", "execution_risk", "verification_risk", "none"] = "none"

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Semantic summary for IPC (W5-3)
# ---------------------------------------------------------------------------

class TaskSemanticSummary(BaseModel):
    """Per-task semantic summary — bounded, serializable."""

    risk_level: Literal["low", "medium", "high"] = "low"
    total_fanout: int = 0
    touched_symbol_count: int = 0
    suggested_deps_count: int = 0
    suggested_deps_digest: str = ""  # sha256[:12]
    confidence: Literal["exact", "best_effort", "opaque"] = "opaque"

    model_config = ConfigDict(extra="ignore")


class SemanticSummary(BaseModel):
    """Bounded semantic summary transmitted over IPC."""

    version: int = 1
    per_task: Dict[str, TaskSemanticSummary] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


# Ledger event kind for plan validation failures
WORKFLOW_PLAN_VALIDATION_FAILED = "workflow.plan_validation_failed"

# IPC validation codes that are considered fatal (block workflow registration)
FATAL_IPC_VALIDATION_CODES = frozenset({
    "E_DEP_CYCLE",
    "E_DUPLICATE_TASK_ID",
    "E_SEMANTIC_PROVIDER_UNAVAILABLE",
})


class RalphRegisterResponse(BaseModel):
    """Response from ralph_register_and_suggest daemon op."""
    workflow_id: str
    registered_count: int = 0
    submitted_count: int = 0
    ready_task_ids: List[str] = Field(default_factory=list)
    validation_errors: List[IpcValidationError] = Field(default_factory=list)
    validation_warnings: List[IpcValidationError] = Field(default_factory=list)
    validation_hints: List[IpcValidationError] = Field(default_factory=list)
    plan_validation_failed_event_emitted: bool = False

    model_config = ConfigDict(extra="ignore")


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


# ---------------------------------------------------------------------------
# Shared validation event serializer — W8d-ledger-schema-parity
# ---------------------------------------------------------------------------

from .event import (  # noqa: E402
    KIND_PLAN_VALIDATED,
    KIND_PLAN_VALIDATION_FAILED,
    PlanValidatedData,
    PlanValidationFailedData,
    SchemaStatsData,
    ValidationFindingV1,
    VALIDATION_EVENT_SCHEMA_VERSION,
    VALIDATION_REPORT_SCHEMA_VERSION,
)

# Re-export constants for downstream import convenience
WORKFLOW_PLAN_VALIDATED = KIND_PLAN_VALIDATED


def _issue_to_finding_v1(issue: IpcValidationError) -> Dict[str, Any]:
    """Convert an IpcValidationError to canonical v1 finding dict."""
    return ValidationFindingV1(
        code=issue.code,
        issue_instance_id=str(getattr(issue, "issue_instance_id", "") or ""),
        confidence=issue.confidence,
        action_owner=issue.action_owner,
        worker_relevance=issue.worker_relevance,
        summary=issue.message,
    ).model_dump()


def serialize_validation_event_v1(
    *,
    valid: bool,
    errors: List[IpcValidationError],
    warnings: List[IpcValidationError],
    hints: List[IpcValidationError],
    ruleset_digest: str = "",
    plan_hash: str = "",
) -> Dict[str, Any]:
    """Serialize a validation result to the canonical v1 event data payload.

    Returns the ``data`` dict suitable for a ``workflow.plan_validated`` or
    ``workflow.plan_validation_failed`` ledger event.
    """
    error_findings = [_issue_to_finding_v1(e) for e in errors]
    warning_findings = [_issue_to_finding_v1(w) for w in warnings]
    hint_findings = [_issue_to_finding_v1(h) for h in hints]

    counts = {
        "errors": len(errors),
        "warnings": len(warnings),
        "hints": len(hints),
        "total": len(errors) + len(warnings) + len(hints),
    }

    if valid:
        model = PlanValidatedData(
            event_schema_version=VALIDATION_EVENT_SCHEMA_VERSION,
            valid=True,
            report_schema_version=VALIDATION_REPORT_SCHEMA_VERSION,
            ruleset_digest=ruleset_digest,
            plan_hash=plan_hash,
            errors=error_findings,
            warnings=warning_findings,
            hints=hint_findings,
            counts=counts,
        )
    else:
        model = PlanValidationFailedData(
            event_schema_version=VALIDATION_EVENT_SCHEMA_VERSION,
            valid=False,
            report_schema_version=VALIDATION_REPORT_SCHEMA_VERSION,
            ruleset_digest=ruleset_digest,
            plan_hash=plan_hash,
            errors=error_findings,
            warnings=warning_findings,
            hints=hint_findings,
            counts=counts,
        )

    return model.model_dump()


def validation_event_kind(valid: bool) -> str:
    """Return the appropriate event kind based on validation outcome."""
    return KIND_PLAN_VALIDATED if valid else KIND_PLAN_VALIDATION_FAILED


class _SchemaStats:
    """Mutable counters for schema migration observability."""

    __slots__ = ("events_written_v1", "events_read_v0", "events_read_v1")

    def __init__(self) -> None:
        self.events_written_v1: int = 0
        self.events_read_v0: int = 0
        self.events_read_v1: int = 0

    def record_write_v1(self) -> None:
        self.events_written_v1 += 1

    def record_read(self, version: int) -> None:
        if version >= 1:
            self.events_read_v1 += 1
        else:
            self.events_read_v0 += 1

    def to_event_data(self) -> Dict[str, Any]:
        return SchemaStatsData(
            event_schema_version=VALIDATION_EVENT_SCHEMA_VERSION,
            events_written_v1=self.events_written_v1,
            events_read_v0=self.events_read_v0,
            events_read_v1=self.events_read_v1,
        ).model_dump()

    def reset(self) -> None:
        self.events_written_v1 = 0
        self.events_read_v0 = 0
        self.events_read_v1 = 0


# Module-level singleton for stats tracking
schema_stats = _SchemaStats()


def read_validation_event(data: Dict[str, Any]) -> Dict[str, Any]:
    """Dual-read v0/v1 validation event data.

    v0 events lack ``event_schema_version`` — normalize them into v1 shape.
    v1 events are returned as-is after model validation.
    """
    version = data.get("event_schema_version", 0)
    schema_stats.record_read(version)

    if version >= 1:
        # v1 — validate and return
        if data.get("valid", True):
            return PlanValidatedData.model_validate(data).model_dump()
        return PlanValidationFailedData.model_validate(data).model_dump()

    # v0 compat: normalize bare issue lists into v1 findings
    errors_raw = data.get("errors", data.get("validation_errors", []))
    warnings_raw = data.get("warnings", data.get("validation_warnings", []))
    hints_raw = data.get("hints", data.get("validation_hints", []))

    def _coerce_finding(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return ValidationFindingV1(
                code=str(raw.get("code", "")),
                summary=str(raw.get("message", raw.get("summary", ""))),
                confidence=str(raw.get("confidence", "opaque")),
                action_owner=str(raw.get("action_owner", "unknown")),
                worker_relevance=str(raw.get("worker_relevance", "none")),
            ).model_dump()
        return ValidationFindingV1(code="", summary=str(raw)).model_dump()

    errors = [_coerce_finding(e) for e in (errors_raw if isinstance(errors_raw, list) else [])]
    warnings = [_coerce_finding(w) for w in (warnings_raw if isinstance(warnings_raw, list) else [])]
    hints = [_coerce_finding(h) for h in (hints_raw if isinstance(hints_raw, list) else [])]
    valid = data.get("valid", len(errors) == 0)

    return {
        "event_schema_version": VALIDATION_EVENT_SCHEMA_VERSION,
        "valid": valid,
        "report_schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
        "ruleset_digest": data.get("ruleset_digest", ""),
        "plan_hash": str(data.get("plan_hash", "")),
        "errors": errors,
        "warnings": warnings,
        "hints": hints,
        "counts": {
            "errors": len(errors),
            "warnings": len(warnings),
            "hints": len(hints),
            "total": len(errors) + len(warnings) + len(hints),
        },
    }
