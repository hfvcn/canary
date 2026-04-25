"""Shared error-envelope definitions for the Ralph subsystem.

Provides a single source of truth for:
- Processing stages (RALPH_STAGES)
- Internal error codes (RULE_ERROR_REGISTRY)
- Structured error envelope builder (build_error_envelope)
- Rule capability manifest (RULE_REGISTRY)

Used by the CLI, daemon IPC, and orchestrator surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import Plan, ValidationIssue


@dataclass(frozen=True)
class AgentConfig:
    provider: str = "stub"
    enabled: bool = True
    api_key_env: str = ""


@dataclass(frozen=True)
class AgentFinding:
    issue_ref: str
    advisory_only: bool = True


@dataclass
class AgentSuggestion:
    """A single advisory suggestion produced by the agent for a beyond-scope issue.

    Suggestions are always advisory — the agent has no decision power.
    """

    issue_id: str  # matches ValidationIssue.issue_instance_id
    checklist_item_id: str  # from beyond_scope_checklist.yaml
    suggestion: str  # advisory text
    confidence: str = "low"  # "low", "medium", "high"
    advisory: bool = True  # always True — agent has no decision power


class RalphAgent:
    """Lightweight advisory agent wrapper used by Ralph integration tests.

    The agent reviews beyond-scope issues identified during static validation
    and produces structured advisory suggestions.  It does NOT call any LLM —
    it is a placeholder that generates formatted review requests.
    """

    def __init__(
        self,
        *,
        workflow_id: str = "",
        plan: Plan | None = None,
        beyond_scope_items: list[object] | None = None,
        config: AgentConfig | None = None,
        checklist_path: Path | None = None,
    ) -> None:
        self.workflow_id = workflow_id
        self.plan = plan
        self.beyond_scope_items = beyond_scope_items or []
        self.config = config or AgentConfig()
        self.available = self._is_available()
        self._checklist: List[Dict[str, Any]] = []
        if checklist_path is not None:
            self._checklist = _load_checklist(checklist_path)

    def _is_available(self) -> bool:
        if not self.config.enabled:
            return False
        if self.config.provider == "stub":
            return True
        if not self.config.api_key_env:
            return False
        return bool(os.environ.get(self.config.api_key_env))

    def review(self, issues: list[ValidationIssue]) -> list[AgentFinding]:
        if not self.available:
            return []
        findings: list[AgentFinding] = []
        for issue in issues:
            if not issue.beyond_scope:
                continue
            task_suffix = ",".join(issue.task_ids) if issue.task_ids else "plan"
            findings.append(AgentFinding(issue_ref=f"{issue.code}[{task_suffix}]"))
        return findings

    def review_beyond_scope(self, issues: list[ValidationIssue]) -> list[AgentSuggestion]:
        """Review beyond-scope issues and return advisory suggestions.

        For each beyond-scope issue, matches it against checklist items and
        produces a placeholder suggestion.  No LLM is called.
        """
        if not self.available:
            return []

        beyond = [i for i in issues if i.beyond_scope]
        if not beyond:
            return []

        suggestions: list[AgentSuggestion] = []
        for issue in beyond:
            matched_item = self._match_checklist(issue)
            item_id = matched_item.get("id", "unknown") if matched_item else "unknown"
            description = (
                matched_item.get("description", issue.message)
                if matched_item
                else issue.message
            )
            suggestions.append(AgentSuggestion(
                issue_id=issue.issue_instance_id or issue.code,
                checklist_item_id=item_id,
                suggestion=f"Requires manual review: {description}",
                confidence="low",
                advisory=True,
            ))
        return suggestions

    def _match_checklist(self, issue: ValidationIssue) -> Dict[str, Any] | None:
        """Find the best matching checklist item for an issue."""
        for item in self._checklist:
            match_type = item.get("match_type", "")
            pattern = item.get("pattern", "")
            if match_type == "code_prefix" and issue.code.startswith(pattern.rstrip("*")):
                return item
            if match_type == "field_content" and pattern in issue.message:
                return item
            if match_type == "manual":
                # manual items match everything as a fallback
                continue
        # Fall back to the first manual item if no specific match
        for item in self._checklist:
            if item.get("match_type") == "manual":
                return item
        return None


def _load_checklist(checklist_path: Path) -> List[Dict[str, Any]]:
    """Load checklist items from a YAML file.  Returns [] on any error."""
    try:
        if not checklist_path.exists():
            return []
        with checklist_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return list(data.get("items", []))
    except Exception:
        return []


def create_agent(checklist_path: Path) -> RalphAgent:
    """Factory: create a RalphAgent backed by a beyond-scope checklist.

    If *checklist_path* does not exist the agent is still usable — it will
    produce generic suggestions without checklist metadata.
    """
    return RalphAgent(checklist_path=checklist_path)


# ---------------------------------------------------------------------------
# Stable stage enum
# ---------------------------------------------------------------------------

RALPH_STAGES = frozenset({
    "load",
    "validate",
    "semantic",
    "ipc",
    "completion",
    "register",
    "suggest",
    "verify",
})


# ---------------------------------------------------------------------------
# Internal error code registry — single canonical copy
# ---------------------------------------------------------------------------

RULE_ERROR_REGISTRY: Dict[str, str] = {
    "load": "E_INTERNAL_LOAD",
    "validate": "E_INTERNAL_VALIDATE",
    "semantic": "E_INTERNAL_SEMANTIC",
    "ipc": "E_INTERNAL_IPC",
    "completion": "E_INTERNAL_COMPLETION",
    "register": "E_INTERNAL_REGISTER",
    "suggest": "E_INTERNAL_SUGGEST",
    "verify": "E_INTERNAL_VERIFY",
}

UNKNOWN_INTERNAL_ERROR_CODE = "E_INTERNAL_UNKNOWN"


# ---------------------------------------------------------------------------
# Rule documentation — source of truth for ``ralph explain --code``
# ---------------------------------------------------------------------------

class _RuleDoc:
    """Structured documentation for a single validation rule code."""

    __slots__ = ("description", "why_it_matters", "fix_template", "suppress_hint")

    def __init__(
        self,
        *,
        description: str,
        why_it_matters: str,
        fix_template: str,
        suppress_hint: str,
    ) -> None:
        self.description = description
        self.why_it_matters = why_it_matters
        self.fix_template = fix_template
        self.suppress_hint = suppress_hint


RULE_DOCS: Dict[str, _RuleDoc] = {
    "E_COVERS_UNKNOWN_FLOW": _RuleDoc(
        description=(
            "A task's verification.covers.flows references a flow ID that is "
            "not declared in the plan's critical_flows or forbidden_flows."
        ),
        why_it_matters=(
            "Typos in flow IDs are silently ignored, so the verification "
            "that you think covers a critical flow actually covers nothing. "
            "This leaves the flow unprotected."
        ),
        fix_template=(
            "Check the flow ID in the task's verification.covers.flows list "
            "and ensure it matches an id in critical_flows or forbidden_flows:\n"
            "  verification:\n"
            "    covers:\n"
            "      flows: [<correct-flow-id>]"
        ),
        suppress_hint=(
            "Add 'E_COVERS_UNKNOWN_FLOW' to the plan's suppress_codes list, "
            "or pass --suppress E_COVERS_UNKNOWN_FLOW on the CLI."
        ),
    ),
    "E_DUPLICATE_TASK_ID": _RuleDoc(
        description="Two or more tasks share the same id.",
        why_it_matters=(
            "Task IDs are the primary key for dependency resolution and "
            "state tracking. Duplicates cause ambiguous scheduling and "
            "may corrupt completion state."
        ),
        fix_template=(
            "Rename one of the duplicate tasks so each id is unique:\n"
            "  - id: T1-auth   # was T1\n"
            "  - id: T1-db     # was T1"
        ),
        suppress_hint=(
            "This is a fatal structural error and cannot be suppressed."
        ),
    ),
    "W_REGISTERED_PLAN_STALE": _RuleDoc(
        description=(
            "The plan file on disk has been modified since the Foreman "
            "registered it. The running daemon is using an older snapshot."
        ),
        why_it_matters=(
            "Edits made after registration are invisible to the running "
            "Foreman. Workers will execute against the stale version, so "
            "fixes or new tasks will not take effect until re-registration."
        ),
        fix_template=(
            "Re-register the plan with the Foreman:\n"
            "  ralph register plan.yaml\n"
            "Or restart the daemon so it picks up the updated file."
        ),
        suppress_hint=(
            "Add 'W_REGISTERED_PLAN_STALE' to suppress_codes or pass "
            "--suppress W_REGISTERED_PLAN_STALE on the CLI."
        ),
    ),
    "E_MISSING_VERIFICATION": _RuleDoc(
        description="A task has no verification block at all.",
        why_it_matters=(
            "Without a verification spec, the task cannot be automatically "
            "checked after completion. This defeats the purpose of the "
            "plan-driven workflow and leaves the task's outcome unverifiable."
        ),
        fix_template=(
            "Add a verification block to the task:\n"
            "  verification:\n"
            "    level: unit\n"
            "    command: pytest tests/test_<module>.py -v"
        ),
        suppress_hint=(
            "Add 'E_MISSING_VERIFICATION' to suppress_codes or pass "
            "--suppress E_MISSING_VERIFICATION on the CLI."
        ),
    ),
    "W_TEST_COVERAGE_GAP": _RuleDoc(
        description=(
            "A task claims source files that have related test files, but "
            "those tests are not covered by the task's verification command."
        ),
        why_it_matters=(
            "Existing tests for the changed code will not run as part of "
            "verification, so regressions may go undetected until much later."
        ),
        fix_template=(
            "Include the related tests in the task's verification:\n"
            "  verification:\n"
            "    level: unit\n"
            "    command: pytest tests/test_<module>.py -v\n"
            "    covers:\n"
            "      tasks: [<this-task-id>]"
        ),
        suppress_hint=(
            "Add 'W_TEST_COVERAGE_GAP' to suppress_codes or pass "
            "--suppress W_TEST_COVERAGE_GAP on the CLI."
        ),
    ),
    "W_COVERS_PATHS_UNVERIFIED": _RuleDoc(
        description=(
            "A compile/unit verification command references a literal file or "
            "directory path that is outside claimed_paths and verification.covers.paths."
        ),
        why_it_matters=(
            "The task is executing verification against files that were not "
            "declared as part of its owned or explicitly covered surface. "
            "That weakens traceability and can hide accidental scope creep."
        ),
        fix_template=(
            "Either add the referenced path under verification.covers.paths "
            "or narrow the command so it only targets declared files:\n"
            "  verification:\n"
            "    command: pytest tests/test_feature.py -q\n"
            "    covers:\n"
            "      paths: [tests/test_feature.py]"
        ),
        suppress_hint=(
            "Add 'W_COVERS_PATHS_UNVERIFIED' to suppress_codes or pass "
            "--suppress W_COVERS_PATHS_UNVERIFIED on the CLI."
        ),
    ),
    "W_STATE_UNKNOWN_TASK_REF": _RuleDoc(
        description="A task id recorded under state.* does not exist in the plan tasks list.",
        why_it_matters=(
            "Runtime state is no longer aligned with the plan source of truth. "
            "That makes scheduler decisions and completion summaries unreliable."
        ),
        fix_template=(
            "Remove or correct the unknown task id from state.completed_task_ids, "
            "state.failed_task_ids, or state.running_tasks."
        ),
        suppress_hint=(
            "Add 'W_STATE_UNKNOWN_TASK_REF' to suppress_codes or pass "
            "--suppress W_STATE_UNKNOWN_TASK_REF on the CLI."
        ),
    ),
    "E_DUPLICATE_FLOW_ID": _RuleDoc(
        description="Two critical_flows entries share the same id.",
        why_it_matters=(
            "Flow ids are used as coverage keys. Duplicates make coverage "
            "ambiguous and can hide whether the intended flow is actually verified."
        ),
        fix_template="Rename one of the duplicate critical_flows ids so each is unique.",
        suppress_hint=(
            "Add 'E_DUPLICATE_FLOW_ID' to suppress_codes or pass "
            "--suppress E_DUPLICATE_FLOW_ID on the CLI."
        ),
    ),
    "E_DUPLICATE_FORBIDDEN_FLOW_ID": _RuleDoc(
        description="Two forbidden_flows entries share the same id.",
        why_it_matters=(
            "Forbidden flow ids are also coverage keys. Duplicates make it "
            "unclear which negative path a verification task is meant to cover."
        ),
        fix_template="Rename one of the duplicate forbidden_flows ids so each is unique.",
        suppress_hint=(
            "Add 'E_DUPLICATE_FORBIDDEN_FLOW_ID' to suppress_codes or pass "
            "--suppress E_DUPLICATE_FORBIDDEN_FLOW_ID on the CLI."
        ),
    ),
    "E_DUPLICATE_INVARIANT_NAME": _RuleDoc(
        description="Two registration_invariants entries share the same name.",
        why_it_matters=(
            "Invariant names are used as stable identifiers in validation output. "
            "Duplicates make failures hard to interpret and fix."
        ),
        fix_template="Rename one of the duplicate registration_invariants names so each is unique.",
        suppress_hint=(
            "Add 'E_DUPLICATE_INVARIANT_NAME' to suppress_codes or pass "
            "--suppress E_DUPLICATE_INVARIANT_NAME on the CLI."
        ),
    ),
    "W_CRITICAL_FLOW_NO_ENTRYPOINTS": _RuleDoc(
        description="A critical flow is declared without any entrypoints.",
        why_it_matters=(
            "Without entrypoints, reviewers and workers cannot tell where the "
            "flow starts in code, which weakens ownership and verification planning."
        ),
        fix_template=(
            "Add one or more entrypoints to the critical flow:\n"
            "  critical_flows:\n"
            "    - id: my-flow\n"
            "      entrypoints: [src/app.py]"
        ),
        suppress_hint=(
            "Add 'W_CRITICAL_FLOW_NO_ENTRYPOINTS' to suppress_codes or pass "
            "--suppress W_CRITICAL_FLOW_NO_ENTRYPOINTS on the CLI."
        ),
    ),
    "H_SUPPRESS_UNUSED": _RuleDoc(
        description="A suppress_codes entry did not match any emitted issue.",
        why_it_matters=(
            "Unused suppressions add noise and can hide when the plan drifted "
            "away from the original reason for suppression."
        ),
        fix_template="Remove the unused suppress code or update it to match the intended rule.",
        suppress_hint=(
            "Add 'H_SUPPRESS_UNUSED' to suppress_codes or pass "
            "--suppress H_SUPPRESS_UNUSED on the CLI."
        ),
    ),
    "W_PLAN_SCOPE_UNUSED": _RuleDoc(
        description="A plan-level scope declaration references a path no task claims.",
        why_it_matters=(
            "Plan-level declarations are meant to point at code the plan actually owns. "
            "If no task claims that path, the declaration is effectively dead metadata."
        ),
        fix_template=(
            "Either add the referenced path to a task's claimed_paths or remove "
            "the unused plan-level declaration."
        ),
        suppress_hint=(
            "Add 'W_PLAN_SCOPE_UNUSED' to suppress_codes or pass "
            "--suppress W_PLAN_SCOPE_UNUSED on the CLI."
        ),
    ),
    "E_DEP_CYCLE": _RuleDoc(
        description="The task dependency graph contains a cycle.",
        why_it_matters=(
            "Cyclic dependencies make it impossible to determine a valid "
            "execution order. No task in the cycle can ever become ready."
        ),
        fix_template=(
            "Break the cycle by removing one of the depends_on edges. "
            "Identify the weakest dependency and either remove it or "
            "extract shared logic into a new task that both can depend on."
        ),
        suppress_hint=(
            "This is a fatal structural error and cannot be suppressed."
        ),
    ),
    "E_DEP_UNKNOWN": _RuleDoc(
        description="A task depends on a task ID that does not exist in the plan.",
        why_it_matters=(
            "The task will be permanently blocked waiting for a dependency "
            "that can never be satisfied."
        ),
        fix_template=(
            "Fix the depends_on entry to reference an existing task id:\n"
            "  depends_on: [<correct-task-id>]"
        ),
        suppress_hint=(
            "This is a fatal structural error and cannot be suppressed."
        ),
    ),
    "E_DEP_SELF": _RuleDoc(
        description="A task lists itself in its own depends_on.",
        why_it_matters=(
            "A self-dependency creates a trivial cycle — the task can "
            "never become ready."
        ),
        fix_template="Remove the task's own ID from its depends_on list.",
        suppress_hint=(
            "This is a fatal structural error and cannot be suppressed."
        ),
    ),
    "E_CRITICAL_FLOW_UNCOVERED": _RuleDoc(
        description=(
            "A declared critical flow is not covered by any task's "
            "verification.covers.flows."
        ),
        why_it_matters=(
            "Critical flows represent end-to-end paths that must be "
            "verified. An uncovered flow means no task is responsible "
            "for proving the flow works."
        ),
        fix_template=(
            "Add the flow ID to a verification task's covers.flows:\n"
            "  verification:\n"
            "    level: integration\n"
            "    covers:\n"
            "      flows: [<flow-id>]"
        ),
        suppress_hint=(
            "Add 'E_CRITICAL_FLOW_UNCOVERED' to suppress_codes or pass "
            "--suppress E_CRITICAL_FLOW_UNCOVERED on the CLI."
        ),
    ),
    "W_EMPTY_ACCEPTANCE": _RuleDoc(
        description="A task has an empty acceptance_criteria field.",
        why_it_matters=(
            "Without acceptance criteria, it is unclear when the task is "
            "truly complete. This makes review and verification subjective."
        ),
        fix_template=(
            "Add concrete acceptance criteria:\n"
            "  acceptance_criteria: |\n"
            "    - Feature X returns 200 for valid input\n"
            "    - Unit tests pass with >= 90% coverage"
        ),
        suppress_hint=(
            "Add 'W_EMPTY_ACCEPTANCE' to suppress_codes or pass "
            "--suppress W_EMPTY_ACCEPTANCE on the CLI."
        ),
    ),
    "E_MISSING_CLAIMED_PATHS": _RuleDoc(
        description="A task has no claimed_paths entries.",
        why_it_matters=(
            "claimed_paths define the task's write-set for conflict "
            "detection. Without them, the scheduler cannot detect "
            "overlapping work or verify file ownership."
        ),
        fix_template=(
            "Add the files or directories the task will modify:\n"
            "  claimed_paths:\n"
            "    - src/mymodule/\n"
            "    - tests/test_mymodule.py"
        ),
        suppress_hint=(
            "Add 'E_MISSING_CLAIMED_PATHS' to suppress_codes or pass "
            "--suppress E_MISSING_CLAIMED_PATHS on the CLI."
        ),
    ),
}


def _is_debug_traceback_enabled() -> bool:
    """Check whether raw traceback output is enabled via environment variable."""
    return os.environ.get("CCCC_DEBUG_TRACEBACK", "").strip() in ("1", "true", "yes")


def build_error_envelope(
    *,
    stage: str,
    exception: BaseException,
    internal_error_code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a structured error envelope dict.

    This is the canonical shape used across all three surfaces (CLI JSON
    output, daemon IPC response, and orchestrator ledger events).

    Parameters
    ----------
    stage:
        One of RALPH_STAGES (e.g. "load", "semantic", "ipc").
    exception:
        The caught exception.
    internal_error_code:
        Explicit error code. Derived from *stage* via RULE_ERROR_REGISTRY when omitted.
    extra:
        Additional key-value pairs merged into the envelope.

    Returns
    -------
    dict with keys: stage, internal_error_code, exception_type, message,
    and optionally traceback_truncated (only when CCCC_DEBUG_TRACEBACK=1).
    """
    if internal_error_code is None:
        code = RULE_ERROR_REGISTRY.get(stage, UNKNOWN_INTERNAL_ERROR_CODE)
    else:
        code = internal_error_code
    envelope: Dict[str, Any] = {
        "stage": stage,
        "internal_error_code": code,
        "exception_type": type(exception).__name__,
        "message": str(exception).strip() or type(exception).__name__,
    }

    if _is_debug_traceback_enabled():
        tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
        full_tb = "".join(tb_lines)
        # Truncate to a reasonable size for structured output
        max_len = 4000
        if len(full_tb) > max_len:
            full_tb = full_tb[:max_len] + "\n... (truncated)"
        envelope["traceback_truncated"] = full_tb

    if extra:
        envelope.update(extra)

    return envelope


# ---------------------------------------------------------------------------
# Rule capability manifest — per-rule-family language + provider requirements
# ---------------------------------------------------------------------------

RULE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "structural": {
        "language": ["any"],
        "requires": [],
    },
    "filesystem": {
        "language": ["any"],
        "requires": ["filesystem"],
    },
    "advisory_ast": {
        "language": ["python"],
        "requires": ["ast"],
    },
    "semantic": {
        "language": ["python"],
        "requires": ["ast", "semantic"],
    },
    "semantic_serena": {
        "language": ["python"],
        "requires": ["ast", "semantic", "serena"],
    },
}


def detect_project_language(project_root: Path) -> str:
    """Detect the primary project language from manifest files.

    Returns ``"python"`` when ``pyproject.toml`` or ``setup.py`` is found,
    ``"javascript"`` when ``package.json`` is found, or ``"unknown"`` otherwise.
    When both Python and JS markers are present, Python wins (monorepo heuristic).
    """
    has_python = (
        (project_root / "pyproject.toml").is_file()
        or (project_root / "setup.py").is_file()
        or (project_root / "setup.cfg").is_file()
    )
    has_js = (project_root / "package.json").is_file()
    if has_python:
        return "python"
    if has_js:
        return "javascript"
    return "unknown"


def _providers_available(
    *,
    has_semantic: bool = False,
    has_serena: bool = False,
) -> Dict[str, bool]:
    """Build a map of provider availability flags."""
    return {
        "filesystem": True,  # always available
        "ast": True,  # always available (stdlib)
        "semantic": has_semantic,
        "serena": has_serena,
    }


def compute_capability_manifest(
    *,
    project_root: Path,
    has_semantic: bool = False,
    has_serena: bool = False,
) -> Dict[str, Any]:
    """Compute active/skipped analyzers based on project language and provider availability.

    Returns a dict with:
    - ``active_analyzers``: list of rule family names that will run
    - ``skipped_analyzers``: list of ``{"name": str, "reason": str}`` for each skipped family
    - ``project_language``: detected language
    """
    language = detect_project_language(project_root)
    providers = _providers_available(has_semantic=has_semantic, has_serena=has_serena)

    active: List[str] = []
    skipped: List[Dict[str, str]] = []

    for family_name, spec in RULE_REGISTRY.items():
        langs = spec["language"]
        reqs = spec["requires"]

        # Language check: skip if family requires a specific language
        # that doesn't match the detected project language
        if "any" not in langs and language not in langs:
            skipped.append({
                "name": family_name,
                "reason": f"project language '{language}' not in {langs}",
            })
            continue

        # Provider check: skip if any required provider is unavailable
        missing_providers = [r for r in reqs if not providers.get(r, False)]
        if missing_providers:
            skipped.append({
                "name": family_name,
                "reason": f"missing provider(s): {', '.join(missing_providers)}",
            })
            continue

        active.append(family_name)

    return {
        "active_analyzers": active,
        "skipped_analyzers": skipped,
        "project_language": language,
    }


# ---------------------------------------------------------------------------
# W8a: Rule version registry — rule code → version int for provenance
# ---------------------------------------------------------------------------

RULE_VERSION_REGISTRY: Dict[str, int] = {
    # Structural rules
    "E_DUPLICATE_TASK_ID": 1,
    "E_DEP_UNKNOWN": 1,
    "E_DEP_SELF": 1,
    "E_DEP_CYCLE": 1,
    "W_DISCONNECTED_COMPONENTS": 1,
    "W_ISOLATED_TASK": 1,
    "E_COVERS_UNKNOWN_TASK": 1,
    "E_COVERS_WITHOUT_DEP_ORDER": 1,
    "E_MISSING_CLAIMED_PATHS": 1,
    "E_MISSING_VERIFICATION": 1,
    "W_EMPTY_ACCEPTANCE": 1,
    "W_GLOBAL_WRITE_CLAIM": 1,
    "E_NO_CROSS_TASK_VERIFICATION": 1,
    "W_WEAK_VERIFICATION_ONLY": 1,
    "W_VERIFICATION_DUPLICATE_COMMAND": 1,
    "E_CONSUMER_WITHOUT_PROVIDER": 1,
    "E_CONSUMER_FROM_UNKNOWN": 1,
    "W_CONTRACT_SCHEMA_MISMATCH": 1,
    "W_PROVIDER_UNUSED": 1,
    "W_INTEGRATION_INTERFACE_MISMATCH": 1,
    "W_CONSUME_WITHOUT_DEP": 1,
    "W_DEP_WITHOUT_CONSUME": 1,
    "E_CRITICAL_ENTRYPOINT_UNOWNED": 1,
    "E_CRITICAL_FLOW_UNCOVERED": 1,
    "E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED": 1,
    "W_FLOW_SEGMENT_UNOWNED": 1,
    "W_FLOW_OWNER_NO_VERIFICATION": 1,
    "E_CRITICAL_FLOW_LEVEL_TOO_WEAK": 1,
    "E_UNCOVERED_REQUIRED_ISSUE": 1,
    "W_VERIFICATION_BEHAVIOR_MISMATCH": 1,
    "W_COVERS_CLAIM_UNVERIFIABLE": 1,
    "E_FORBIDDEN_FLOW_UNCOVERED": 1,
    "E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK": 1,
    "W_IMPLICIT_SERIALIZATION": 1,
    "W_SHARED_FILE_PARTIAL_VERIFICATION": 1,
    "W_CROSS_BOUNDARY_WITHOUT_GLUE": 1,
    "E_MISSING_INTEGRATION_SPINE": 1,
    "W_INTEGRATION_ROLE_WEAK_VERIFICATION": 1,
    "W_VERIFICATION_ROLE_NO_COVERS": 1,
    "W_VERIFICATION_ROLE_CLAIMS_SOURCE": 1,
    "W_LEAF_ROLE_IS_INTEGRATOR": 1,
    "W_NO_EARLY_INTEGRATION_CHECKPOINT": 1,
    # Completeness rules
    "E_COVERS_UNKNOWN_FLOW": 1,
    "W_STATE_UNKNOWN_TASK_REF": 1,
    "E_DUPLICATE_FLOW_ID": 1,
    "E_DUPLICATE_FORBIDDEN_FLOW_ID": 1,
    "E_DUPLICATE_INVARIANT_NAME": 1,
    "W_CRITICAL_FLOW_NO_ENTRYPOINTS": 1,
    "H_SUPPRESS_UNUSED": 1,
    "W_PLAN_SCOPE_UNUSED": 1,
    # Filesystem rules
    "W_REGISTERED_PLAN_STALE": 1,
    "W_TEST_COVERAGE_GAP": 1,
    # Semantic rules
    "W_SEMANTIC_DEP_HINT": 1,
    # Suppress-lease rules (W8b)
    "W_SUPPRESS_EXPIRED": 1,
    "W_ORPHANED_SUPPRESSION": 1,
    "E_SUPPRESS_LEASE_INCOMPLETE": 1,
}


def compute_ruleset_digest(*, semantic_mode: str = "off") -> str:
    """SHA-256 of RULE_VERSION_REGISTRY versions + semantic_mode.

    This digest changes whenever a rule version is bumped or the semantic
    mode changes, allowing consumers to detect when the ruleset evolves.
    """
    payload = {
        "rule_versions": {k: v for k, v in sorted(RULE_VERSION_REGISTRY.items())},
        "semantic_mode": semantic_mode,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_ralph_version() -> str:
    """Return the installed Ralph/CCCC package version, or 'dev' as fallback."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        for dist_name in ("cccc-pair", "cccc"):
            try:
                return version(dist_name)
            except PackageNotFoundError:
                continue
    except Exception:
        pass
    return "dev"
