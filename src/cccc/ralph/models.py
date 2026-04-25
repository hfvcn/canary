"""Ralph domain models — standalone, no CCCC infrastructure dependencies.

These models define the plan file schema that Ralph reads and validates.
The plan file (YAML/JSON) is the single source of truth; Ralph never mutates it.
"""

from __future__ import annotations

import hashlib
import json
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
# Semantic blocks
# ---------------------------------------------------------------------------


class SemanticTarget(BaseModel):
    """A single symbol-level operation target."""

    path: str
    symbol: str
    op: str = "modify_body"  # modify_body, modify_interface, rename, delete, create
    inferred: bool = False

    model_config = ConfigDict(extra="ignore")


class SemanticBlock(BaseModel):
    """Per-task semantic annotation block."""

    mode: str = "advisory"  # advisory, strict, off
    targets: List[SemanticTarget] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


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
    verification_mode: Literal["ralph", "agent"] = "ralph"

    verification: Optional[Verification] = None

    provides: List[Contract] = Field(default_factory=list)
    consumes: List[Contract] = Field(default_factory=list)

    addresses: List[str] = Field(default_factory=list)  # issue IDs this task fixes
    failure_path: str = ""

    semantic: Optional[SemanticBlock] = None

    # Default: extra="ignore" (legacy).  Switched to "forbid" by
    # _apply_strict_schema() when Plan.schema_version is set.
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
            verification_mode=self.verification_mode,
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
    test_created_by: List[str] = Field(default_factory=list)
    required_verification_level: VerificationLevel = "integration"

    model_config = ConfigDict(extra="ignore")


class ForbiddenFlow(BaseModel):
    """A negative flow that must NOT be possible — anti-bypass declarations."""

    id: str
    description: str = ""
    test_created_by: List[str] = Field(default_factory=list)
    required_verification_level: VerificationLevel = "e2e"

    model_config = ConfigDict(extra="ignore")


class FindingRef(BaseModel):
    """Links a finding to its mitigation and enforcement mechanisms."""

    id: str = ""
    mitigation: str = ""
    enforced_by: List[str] = Field(default_factory=list)

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


# ---------------------------------------------------------------------------
# Suppress lease (W8b)
# ---------------------------------------------------------------------------

# Placeholder strings that disqualify a field from being "real"
_SUPPRESS_PLACEHOLDERS = frozenset({
    "todo", "tbd", "fixme", "xxx", "placeholder", "changeme",
    "tba", "n/a", "na", "none", "unknown",
})

# Maximum allowed expiry horizon from today (2 years)
_MAX_EXPIRY_YEARS = 2


class SuppressInstance(BaseModel):
    """Per-code suppression with optional lease metadata.

    A suppression is *managed* iff all three governance fields are non-empty
    AND valid (no placeholder values, expiry within 2 years).
    """

    code: str
    owner: str = ""
    expiry: Optional[str] = None   # ISO date  e.g. "2026-12-31"
    review_after: Optional[str] = None  # ISO date

    model_config = ConfigDict(extra="ignore")

    def is_managed(self) -> bool:
        """True when all three governance fields are present and valid."""
        if not self.owner or not self.expiry or not self.review_after:
            return False
        if self._is_placeholder(self.owner):
            return False
        if self._is_placeholder(self.expiry):
            return False
        if self._is_placeholder(self.review_after):
            return False
        if not self._is_valid_expiry(self.expiry):
            return False
        return True

    def has_any_governance(self) -> bool:
        """True when at least one governance field is non-empty and non-placeholder."""
        for val in (self.owner, self.expiry, self.review_after):
            if val and not self._is_placeholder(val):
                return True
        return False

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        return value.strip().lower() in _SUPPRESS_PLACEHOLDERS

    @staticmethod
    def _is_valid_expiry(value: str) -> bool:
        """Check that expiry is a parseable date within 2 years of today."""
        import datetime as _dt
        try:
            expiry_date = _dt.date.fromisoformat(value)
        except (ValueError, TypeError):
            return False
        today = _dt.date.today()
        max_date = today.replace(year=today.year + _MAX_EXPIRY_YEARS)
        return expiry_date <= max_date

    def is_expired(self) -> bool:
        """True when expiry is a valid date in the past."""
        import datetime as _dt
        if not self.expiry:
            return False
        try:
            expiry_date = _dt.date.fromisoformat(self.expiry)
        except (ValueError, TypeError):
            return False
        return expiry_date < _dt.date.today()


class Plan(BaseModel):
    """Top-level plan document — the file Ralph reads."""

    schema_version: Optional[str] = None

    tasks: List[TaskSpec] = Field(default_factory=list)
    state: PlanState = Field(default_factory=PlanState)

    plan_scope: List[str] = Field(default_factory=list)
    critical_entrypoints: List[str] = Field(default_factory=list)
    critical_flows: List[CriticalFlow] = Field(default_factory=list)
    forbidden_flows: List[ForbiddenFlow] = Field(default_factory=list)
    finding_refs: List[FindingRef] = Field(default_factory=list)
    registration_invariants: List[RegistrationInvariant] = Field(default_factory=list)
    suppress_flows: List[str] = Field(default_factory=list)

    required_issues: List[str] = Field(default_factory=list)  # issue IDs that must be addressed
    suppress_codes: List[str] = Field(default_factory=list)
    suppress_instances: List["SuppressInstance"] = Field(default_factory=list)

    # Semantic validation config
    semantic_mode: str = "off"  # advisory, strict, off
    auto_infer: bool = False

    _provenance: Dict[str, str] = PrivateAttr(default_factory=dict)

    # Default: extra="ignore" (legacy).  Switched to "forbid" by
    # _apply_strict_schema() when schema_version is set.
    model_config = ConfigDict(extra="ignore")

    @property
    def provenance(self) -> Dict[str, str]:
        return self._provenance

    @property
    def effective_suppress_codes(self) -> List[str]:
        """Union of suppress_codes + codes from suppress_instances (managed or legacy)."""
        codes = list(self.suppress_codes)
        for si in self.suppress_instances:
            if si.code and si.code not in codes:
                codes.append(si.code)
        return codes


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
    task_metadata: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    batch_sequence: int = 0
    batch_boundary: bool = True
    task_summaries: Dict[str, str] = Field(default_factory=dict)


IssueSeverity = Literal["error", "warning", "hint"]


class ValidationIssue(BaseModel):
    """A single issue found by ralph validate."""

    code: str
    severity: IssueSeverity
    message: str
    task_ids: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)

    # W8a: deterministic instance identity — sha1(code + evidence_json + task_ids)[:16]
    issue_instance_id: str = ""

    # W4 finding metadata — classification fields for downstream consumers
    confidence: Literal["exact", "best_effort", "opaque"] = "opaque"
    source: str = ""
    action_owner: Literal["author", "worker", "shared", "unknown"] = "unknown"
    worker_relevance: Literal["blocking", "execution_risk", "verification_risk", "none"] = "none"
    beyond_scope: bool = False


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


def compute_issue_instance_id(issue: "ValidationIssue") -> str:
    """Compute a deterministic instance identity for a ValidationIssue.

    Hash = sha1(code + canonical_evidence_json + tuple(sorted(task_ids)))[:16].
    """
    canonical_evidence = json.dumps(
        issue.evidence, sort_keys=True, ensure_ascii=False,
    )
    sorted_task_ids = tuple(sorted(issue.task_ids))
    data = f"{issue.code}|{canonical_evidence}|{sorted_task_ids}"
    return hashlib.sha1(data.encode("utf-8")).hexdigest()[:16]


def stamp_issue_ids(issues: "List[ValidationIssue]") -> None:
    """Set issue_instance_id on every issue in the list (mutates in-place)."""
    for issue in issues:
        issue.issue_instance_id = compute_issue_instance_id(issue)


class ValidationReport(BaseModel):
    """Output of ralph validate."""

    valid: bool = True
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)
    hints: List[ValidationIssue] = Field(default_factory=list)

    # W8a provenance fields
    report_schema_version: str = "1.0.0"
    ruleset_digest: str = ""
    ralph_version: str = ""
