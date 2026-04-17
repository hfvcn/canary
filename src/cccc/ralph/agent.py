"""Shared error-envelope definitions for the Ralph subsystem.

Provides a single source of truth for:
- Processing stages (RALPH_STAGES)
- Internal error codes (RULE_ERROR_REGISTRY)
- Structured error envelope builder (build_error_envelope)

Used by the CLI, daemon IPC, and orchestrator surfaces.
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Optional


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
