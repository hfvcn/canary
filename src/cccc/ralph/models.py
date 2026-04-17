"""Ralph domain models — standalone, no CCCC infrastructure dependencies.

These models define the plan file schema that Ralph reads and validates.
The plan file (YAML/JSON) is the single source of truth; Ralph never mutates it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

VerificationLevel = Literal["compile", "unit", "integration", "e2e"]


class VerificationCovers(BaseModel):
    """What a verification check covers — tasks, paths, or named flows."""

    tasks: List[str] = Field(default_factory=list)
    paths: List[str] = Field(default_factory=list)
    flows: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class CheckSpec(BaseModel):
    """Individual verification check specification (e.g., build, test, lint)."""

    name: str
    command: str
    required: bool = True
    expected_exit_code: int = 0

    model_config = ConfigDict(extra="ignore")


class Verification(BaseModel):
    """Structured verification spec — replaces free-text verification_command."""

    level: VerificationLevel
    command: str = ""
    checks: List[CheckSpec] = Field(default_factory=list)
    covers: VerificationCovers = Field(default_factory=VerificationCovers)
    expected_exit_code: int = 0

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Contracts (provides / consumes)
# ---------------------------------------------------------------------------

class Contract(BaseModel):
    """A named artifact that a task provides or consumes."""

    name: str
    kind: str = "artifact"  # artifact, runtime_capability, api_endpoint, ...
    from_task: Optional[str] = Field(default=None, alias="from")
    schema_hint: Union[str, Dict[str, Any], None] = ""
    # Supports legacy free-text hints and structured descriptors like
    # {"type": "string", "format": "uuid"}.

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

TaskRole = Literal["leaf", "integration", "verification"]


class TaskSpec(BaseModel):
    """A single task in a plan — the unit of work assignment."""

    id: str
    title: str = ""
    role: TaskRole = "leaf"
    type: Literal["frontend", "backend", "general"] = "general"  # WF-4 alignment
    depends_on: List[str] = Field(default_factory=list)
    claimed_paths: List[str] = Field(default_factory=list)
    awareness_paths: List[str] = Field(default_factory=list)

    goal_behavior: str = ""
    acceptance_criteria: str = ""

    verification: Optional[Verification] = None

    provides: List[Contract] = Field(default_factory=list)
    consumes: List[Contract] = Field(default_factory=list)

    addresses: List[str] = Field(default_factory=list)  # issue IDs this task fixes

    model_config = ConfigDict(extra="ignore")

    def to_task_ref(self) -> "TaskRef":
        """Convert this TaskSpec to a TaskRef for IPC transmission."""
        from ..contracts.v1.ralph_ipc import TaskRef, VerificationSpec

        verification_spec = None
        if self.verification is not None:
            covers = self.verification.covers
            verification_spec = VerificationSpec(
                level=self.verification.level,
                command=self.verification.command,
                checks=[
                    {"name": c.name, "command": c.command, "required": c.required, "expected_exit_code": c.expected_exit_code}
                    for c in self.verification.checks
                ],
                covers_tasks=covers.tasks if covers else [],
                covers_paths=covers.paths if covers else [],
                covers_flows=covers.flows if covers else [],
                expected_exit_code=self.verification.expected_exit_code,
            )

        return TaskRef(
            id=self.id,
            title=self.title,
            type=self.type,
            role=self.role,
            depends_on=self.depends_on,
            claimed_paths=self.claimed_paths,
            goal_behavior=self.goal_behavior,
            acceptance_criteria=self.acceptance_criteria,
            verification=verification_spec,
            provides=[c.model_dump() for c in self.provides],
            consumes=[c.model_dump() for c in self.consumes],
            addresses=self.addresses,
        )


# ---------------------------------------------------------------------------
# Plan-level declarations
# ---------------------------------------------------------------------------

class CriticalFlow(BaseModel):
    """A named end-to-end flow that must be covered by the plan."""

    id: str
    description: str = ""
    entrypoints: List[str] = Field(default_factory=list)
    required_verification_level: VerificationLevel = "integration"

    model_config = ConfigDict(extra="ignore")


class ForbiddenFlow(BaseModel):
    """A negative flow that must NOT be possible — anti-bypass declarations."""

    id: str
    description: str = ""
    required_verification_level: VerificationLevel = "e2e"

    model_config = ConfigDict(extra="ignore")


class RegistrationInvariant(BaseModel):
    """A registry that must be updated when new items are added."""

    name: str
    description: str = ""
    registry_file: str
    registry_symbol: str = ""

    model_config = ConfigDict(extra="ignore")


class RunningTask(BaseModel):
    """A currently running task — used in PlanState for write-set awareness."""

    task_id: str
    claimed_paths: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class PlanState(BaseModel):
    """Runtime state of a plan — what's done, running, failed."""

    completed_task_ids: List[str] = Field(default_factory=list)
    running_tasks: List[RunningTask] = Field(default_factory=list)
    failed_task_ids: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class Plan(BaseModel):
    """Top-level plan document — the file Ralph reads."""

    tasks: List[TaskSpec] = Field(default_factory=list)
    state: PlanState = Field(default_factory=PlanState)

    critical_entrypoints: List[str] = Field(default_factory=list)
    critical_flows: List[CriticalFlow] = Field(default_factory=list)
    forbidden_flows: List[ForbiddenFlow] = Field(default_factory=list)
    registration_invariants: List[RegistrationInvariant] = Field(default_factory=list)

    required_issues: List[str] = Field(default_factory=list)  # issue IDs that must be addressed
    suppress_codes: List[str] = Field(default_factory=list)
    _provenance: Dict[str, str] = PrivateAttr(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    @property
    def provenance(self) -> Dict[str, str]:
        return self._provenance


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

BlockedKind = Literal["waiting", "deferred"]


class BlockedTask(BaseModel):
    """A task that cannot run yet, with reasons."""

    task_id: str
    kind: BlockedKind = "waiting"  # waiting=hard dep, deferred=batch conflict
    reasons: List[str] = Field(default_factory=list)


class BatchResult(BaseModel):
    """Output of ralph suggest — ready batch + blocked reasons."""

    ready: List[str] = Field(default_factory=list)
    blocked: List[BlockedTask] = Field(default_factory=list)
    rationale: str = ""


IssueSeverity = Literal["error", "warning", "hint"]


class ValidationIssue(BaseModel):
    """A single issue found by ralph validate."""

    code: str
    severity: IssueSeverity
    message: str
    task_ids: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)

    # W4 finding metadata — classification fields for downstream consumers
    confidence: Literal["exact", "best_effort", "opaque"] = "opaque"
    source: str = ""
    action_owner: Literal["author", "worker", "shared", "unknown"] = "unknown"
    worker_relevance: Literal["blocking", "execution_risk", "verification_risk", "none"] = "none"


def classify_issue_metadata(issue: "ValidationIssue") -> "ValidationIssue":
    """Populate W4 finding-metadata fields based on the issue code prefix.

    Classification rules:
    - E_* / W_* (non-verification) structural rules → author, exact
    - S_* semantic rules → confidence from evidence if available, else best_effort
    - W_VERIFICATION_* → shared, verification_risk
    """
    code = issue.code

    if code.startswith("W_VERIFICATION_"):
        issue.action_owner = "shared"
        issue.confidence = "exact"
        issue.worker_relevance = "verification_risk"
        issue.source = "filesystem_validator"
    elif code.startswith("S_"):
        # Semantic rules — confidence from provider evidence if available
        provider_confidence = str(issue.evidence.get("confidence", "")).strip()
        if provider_confidence in ("exact", "best_effort", "opaque"):
            issue.confidence = provider_confidence  # type: ignore[assignment]
        else:
            issue.confidence = "best_effort"
        issue.action_owner = "author"
        issue.source = "semantic_validator"
    else:
        # Structural rules (E_*, W_* non-verification)
        issue.action_owner = "author"
        issue.confidence = "exact"
        issue.source = "validator"

    return issue


class ValidationReport(BaseModel):
    """Output of ralph validate."""

    valid: bool = True
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)
    hints: List[ValidationIssue] = Field(default_factory=list)
