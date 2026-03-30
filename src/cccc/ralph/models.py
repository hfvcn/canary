"""Ralph domain models — standalone, no CCCC infrastructure dependencies.

These models define the plan file schema that Ralph reads and validates.
The plan file (YAML/JSON) is the single source of truth; Ralph never mutates it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class Verification(BaseModel):
    """Structured verification spec — replaces free-text verification_command."""

    level: VerificationLevel
    command: str
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
    schema_hint: str = ""  # loose description or type hint for matching

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
    depends_on: List[str] = Field(default_factory=list)
    claimed_paths: List[str] = Field(default_factory=list)

    goal_behavior: str = ""
    acceptance_criteria: str = ""

    verification: Optional[Verification] = None

    provides: List[Contract] = Field(default_factory=list)
    consumes: List[Contract] = Field(default_factory=list)

    addresses: List[str] = Field(default_factory=list)  # issue IDs this task fixes

    model_config = ConfigDict(extra="ignore")


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

    required_issues: List[str] = Field(default_factory=list)  # issue IDs that must be addressed

    model_config = ConfigDict(extra="ignore")


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


class ValidationReport(BaseModel):
    """Output of ralph validate."""

    valid: bool = True
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)
    hints: List[ValidationIssue] = Field(default_factory=list)
