"""Prompt budget and assembly for worker task prompts (W3-10).

Extracted from workflow_orchestrator.py as a pure refactor (RO-31).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# PromptBudget — W3-10
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_TOKEN_BUDGET = 12_000
PROMPT_BUDGET_ENV_VAR = "CCCC_PROMPT_TOKEN_BUDGET"
MANDATORY_RATIO_LIMIT = 0.40
CONTEXT_DEGRADED_MARKER = "[CONTEXT DEGRADED]"


class PromptMinimaOverflow(ValueError):
    """Raised when mandatory sections exceed 40% of the budget (E_PROMPT_MINIMA_OVERFLOW)."""

    code = "E_PROMPT_MINIMA_OVERFLOW"


def _estimate_tokens(text: str) -> int:
    """Approximate token count (len / 4 fallback)."""
    return max(1, len(text) // 4) if text else 0


@dataclass
class _PromptSection:
    """A named section of the task prompt with its text."""
    name: str
    text: str
    mandatory: bool = False
    priority: int = 99  # Lower = higher priority


@dataclass
class _OmissionEntry:
    """Record of what happened to a section during budgeting."""
    section: str
    original_tokens: int
    included_tokens: int
    strategy: str  # "kept", "condensed", "truncated", "omitted"


@dataclass
class PromptBudgetResult:
    """Result of applying PromptBudget to a set of sections."""
    text: str
    omission_manifest: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = 0


class PromptBudget:
    """Token-budget-aware prompt assembler.

    Mandatory sections (Task ID, Title, Goal Behavior, Acceptance Criteria,
    Verification Command, Do-Not-Ignore Issues, Recommended Tests, Forbidden
    Actions) are never truncated.  If they exceed 40% of the budget the class
    raises ``PromptMinimaOverflow`` (code ``E_PROMPT_MINIMA_OVERFLOW``).

    Remaining sections are included in priority order:
        contract > blockers > verification_command > recommended_tests
        > condensed_semantic_focus > raw_semantic_context > context_store

    When a section does not fit it is first condensed (symbol signatures only),
    then truncated with a ``[CONTEXT DEGRADED]`` marker.
    """

    # Priority mapping — lower = higher priority
    PRIORITY_MAP: Dict[str, int] = {
        "contract": 10,
        "blockers": 20,
        "verification_command": 30,
        "recommended_tests": 40,
        "condensed_semantic_focus": 50,
        "raw_semantic_context": 60,
        "context_store": 70,
    }

    # Sections that are mandatory (never truncated)
    MANDATORY_SECTIONS = frozenset({
        "task_id",
        "title",
        "goal_behavior",
        "acceptance_criteria",
        "verification_command",
        "do_not_ignore_issues",
        "recommended_tests",
        "forbidden_actions",
    })

    def __init__(self, budget: Optional[int] = None):
        raw = budget
        if raw is None:
            env_val = os.environ.get(PROMPT_BUDGET_ENV_VAR, "")
            if env_val.strip().isdigit():
                raw = int(env_val.strip())
        self.budget = raw if raw is not None else DEFAULT_PROMPT_TOKEN_BUDGET

    @staticmethod
    def condense(text: str) -> str:
        """Condense text to symbol signatures only (first line of each def/class)."""
        lines = text.splitlines()
        condensed: List[str] = []
        for line in lines:
            stripped = line.strip()
            if (
                stripped.startswith("def ")
                or stripped.startswith("class ")
                or stripped.startswith("async def ")
                or stripped.startswith("# ")
                or stripped.startswith("## ")
            ):
                condensed.append(line)
        if not condensed:
            # Fallback: take first 3 lines
            condensed = lines[:3]
        return "\n".join(condensed)

    def apply(self, sections: List[_PromptSection]) -> PromptBudgetResult:
        """Assemble prompt text respecting the token budget.

        Returns a ``PromptBudgetResult`` with the final text, omission manifest,
        and budget accounting.
        """
        manifest: List[_OmissionEntry] = []
        budget = self.budget

        # --- Phase 1: mandatory sections ---
        mandatory = [s for s in sections if s.mandatory]
        optional = sorted(
            [s for s in sections if not s.mandatory],
            key=lambda s: s.priority,
        )

        mandatory_tokens = sum(_estimate_tokens(s.text) for s in mandatory)
        if mandatory_tokens > int(budget * MANDATORY_RATIO_LIMIT):
            raise PromptMinimaOverflow(
                f"Mandatory sections use {mandatory_tokens} tokens "
                f"(>{int(budget * MANDATORY_RATIO_LIMIT)} = 40% of {budget}). "
                f"Reduce mandatory content or increase CCCC_PROMPT_TOKEN_BUDGET."
            )

        # All mandatory sections are included verbatim
        included_parts: List[str] = []
        used_tokens = 0
        for s in mandatory:
            tok = _estimate_tokens(s.text)
            included_parts.append(s.text)
            used_tokens += tok
            manifest.append(_OmissionEntry(
                section=s.name,
                original_tokens=tok,
                included_tokens=tok,
                strategy="kept",
            ))

        # --- Phase 2: optional sections in priority order ---
        remaining = budget - used_tokens
        for s in optional:
            orig_tokens = _estimate_tokens(s.text)
            if orig_tokens <= remaining:
                # Fits entirely
                included_parts.append(s.text)
                used_tokens += orig_tokens
                remaining -= orig_tokens
                manifest.append(_OmissionEntry(
                    section=s.name,
                    original_tokens=orig_tokens,
                    included_tokens=orig_tokens,
                    strategy="kept",
                ))
            elif remaining > 0:
                # Try condensing first
                condensed = self.condense(s.text)
                condensed_tokens = _estimate_tokens(condensed)
                if condensed_tokens <= remaining:
                    included_parts.append(condensed)
                    used_tokens += condensed_tokens
                    remaining -= condensed_tokens
                    manifest.append(_OmissionEntry(
                        section=s.name,
                        original_tokens=orig_tokens,
                        included_tokens=condensed_tokens,
                        strategy="condensed",
                    ))
                else:
                    # Truncate to remaining budget
                    char_limit = remaining * 4  # inverse of token estimate
                    truncated = s.text[:char_limit]
                    trunc_tokens = _estimate_tokens(truncated)
                    included_parts.append(truncated + f"\n{CONTEXT_DEGRADED_MARKER}")
                    used_tokens += trunc_tokens
                    remaining -= trunc_tokens
                    manifest.append(_OmissionEntry(
                        section=s.name,
                        original_tokens=orig_tokens,
                        included_tokens=trunc_tokens,
                        strategy="truncated",
                    ))
            else:
                # No budget left — omit entirely
                manifest.append(_OmissionEntry(
                    section=s.name,
                    original_tokens=orig_tokens,
                    included_tokens=0,
                    strategy="omitted",
                ))

        text = "\n\n".join(part for part in included_parts if part)
        manifest_dicts = [
            {
                "section": m.section,
                "original_tokens": m.original_tokens,
                "included_tokens": m.included_tokens,
                "strategy": m.strategy,
            }
            for m in manifest
        ]
        return PromptBudgetResult(
            text=text,
            omission_manifest=manifest_dicts,
            total_tokens=used_tokens,
            budget=budget,
        )


# ---------------------------------------------------------------------------
# Issue digest builder
# ---------------------------------------------------------------------------

def build_issue_digest(issues: "List[Any]") -> str:
    """Build a compact issue digest for worker prompt injection.

    Filters issues to action_owner in {worker, shared} and selects up to
    1 blocking + 1 execution_risk + 1 verification_risk entry.  Each entry
    is a single-line action verb + brief evidence.
    """
    filtered = [
        i for i in issues
        if getattr(i, "action_owner", "unknown") in ("worker", "shared")
    ]
    if not filtered:
        return ""

    # Bucket by worker_relevance — keep first match per bucket
    buckets: Dict[str, Any] = {}
    for relevance in ("blocking", "execution_risk", "verification_risk"):
        for issue in filtered:
            if getattr(issue, "worker_relevance", "none") == relevance:
                buckets[relevance] = issue
                break

    if not buckets:
        return ""

    lines: List[str] = []
    for relevance, issue in buckets.items():
        code = str(getattr(issue, "code", ""))
        msg = str(getattr(issue, "message", "")).strip()
        evidence = getattr(issue, "evidence", {})
        evidence_brief = ""
        if isinstance(evidence, dict):
            for key in ("path", "summary", "detail", "message"):
                val = str(evidence.get(key, "")).strip()
                if val:
                    evidence_brief = val
                    break
        line = f"[{relevance.upper()}] {code}: {msg}"
        if evidence_brief:
            line += f" ({evidence_brief})"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runtime adapter hint
# ---------------------------------------------------------------------------

_RUNTIME_HINTS = {
    "claude": "Write code directly. Use `cccc send --to @foreman --text \"...\"` for progress/help; report completion via `cccc task complete <task_id> --changed-file <path> --evidence \"summary\"`.",
    "codex": "Use your internal workflow. Use `cccc send --to @foreman --text \"...\"` for progress/help; report completion via `cccc task complete <task_id> --changed-file <path> --evidence \"summary\"`.",
    "gemini": "Execute the task. Use `cccc send --to @foreman --text \"...\"` for progress/help; report completion via `cccc task complete <task_id> --changed-file <path> --evidence \"summary\"`.",
}


def build_runtime_adapter_hint(runtime: str) -> str:
    """Return a runtime-specific hint string, or empty string if unknown."""
    return _RUNTIME_HINTS.get(str(runtime or "").strip().lower(), "")


# ---------------------------------------------------------------------------
# Task prompt assembly
# ---------------------------------------------------------------------------

def build_task_prompt(
    task: Any,
    *,
    worker_prompt: str = "",
    runtime: str = "",
    issues: Optional[List[Any]] = None,
    recommended_tests: Optional[List[str]] = None,
    forbidden_flows: Optional[List[Any]] = None,
    context_text: str = "",
) -> str:
    """Build the task prompt to send to an agent.

    Wraps all content through :class:`PromptBudget` so the resulting text
    stays within the configured token budget.  Mandatory sections (task ID,
    title, goal, acceptance criteria, verification command, forbidden
    actions) are never truncated.  Lower-priority context is condensed or
    omitted when space is limited.

    Args:
        task: TaskRef object with id, type, title, goal_behavior, etc.
        worker_prompt: Persisted worker prompt text.
        runtime: Runtime identifier (claude/codex/gemini).
        issues: Optional list of ValidationIssue objects for this task.
        recommended_tests: Optional list of test selector strings.
        forbidden_flows: Optional list of ForbiddenFlow objects.
        context_text: Pre-rendered context store text for this task.
    """
    sections: List[_PromptSection] = []

    # --- Mandatory sections (never truncated) ---
    sections.append(_PromptSection(
        name="task_id",
        text=f"[Foreman Assignment]\nTask ID: {task.id}\nType: {task.type}",
        mandatory=True,
    ))
    sections.append(_PromptSection(
        name="title",
        text=f"Title: {task.title}",
        mandatory=True,
    ))
    if task.goal_behavior:
        sections.append(_PromptSection(
            name="goal_behavior",
            text=f"Goal: {task.goal_behavior}",
            mandatory=True,
        ))
    if task.acceptance_criteria:
        sections.append(_PromptSection(
            name="acceptance_criteria",
            text=f"Acceptance Criteria: {task.acceptance_criteria}",
            mandatory=True,
        ))
    if task.verification and task.verification.command:
        sections.append(_PromptSection(
            name="verification_command",
            text=f"Verification Command: {task.verification.command}",
            mandatory=True,
            priority=PromptBudget.PRIORITY_MAP.get("verification_command", 30),
        ))
    # Do-not-ignore issues — from task attribute or computed from issues list
    do_not_ignore = getattr(task, "do_not_ignore_issues", None)
    if not do_not_ignore and issues:
        do_not_ignore = build_issue_digest(issues)
    if do_not_ignore:
        sections.append(_PromptSection(
            name="do_not_ignore_issues",
            text=f"Do-Not-Ignore Issues:\n{do_not_ignore}",
            mandatory=True,
        ))
    # Recommended tests — from parameter or task attribute
    rec_tests_text = ""
    if recommended_tests:
        rec_tests_text = "\n".join(recommended_tests)
    elif getattr(task, "recommended_tests", None):
        rec_tests_text = str(task.recommended_tests)  # type: ignore[union-attr]
    if rec_tests_text:
        sections.append(_PromptSection(
            name="recommended_tests",
            text=f"Recommended Tests:\n{rec_tests_text}",
            mandatory=True,
            priority=PromptBudget.PRIORITY_MAP.get("recommended_tests", 40),
        ))
    # Forbidden actions — base text + project forbidden_flows
    forbidden_lines = [
        "Assigned by Foreman inside the Ralph workflow.",
        "Execute this task only.",
        "Do not contact the user to renegotiate scope.",
    ]
    if forbidden_flows:
        for flow in forbidden_flows:
            flow_id = str(getattr(flow, "id", "")).strip()
            flow_desc = str(getattr(flow, "description", "")).strip()
            if flow_id:
                forbidden_lines.append(f"[FORBIDDEN] {flow_id}: {flow_desc}")
    forbidden_text = "\n".join(forbidden_lines)
    sections.append(_PromptSection(
        name="forbidden_actions",
        text=forbidden_text,
        mandatory=True,
    ))

    # --- Optional sections (subject to budget) ---
    if task.claimed_paths:
        sections.append(_PromptSection(
            name="contract",
            text=f"Scope (claimed files): {', '.join(task.claimed_paths)}",
            priority=PromptBudget.PRIORITY_MAP.get("contract", 10),
        ))

    worker_prompt_text = str(worker_prompt or "").strip()
    if worker_prompt_text:
        sections.append(_PromptSection(
            name="blockers",
            text=f"Worker Assignment:\n{worker_prompt_text}",
            priority=PromptBudget.PRIORITY_MAP.get("blockers", 20),
        ))

    adapter_hint = build_runtime_adapter_hint(runtime)
    if adapter_hint:
        sections.append(_PromptSection(
            name="raw_semantic_context",
            text=f"Runtime Adapter:\n{adapter_hint}",
            priority=PromptBudget.PRIORITY_MAP.get("raw_semantic_context", 60),
        ))

    progress_reporting = (
        f"PROGRESS REPORTING:\n"
        f"While working on long tasks, periodically report progress with:\n"
        f'  cccc task heartbeat {task.id} --progress <0-100> --message "what you\'re doing"\n'
        f"Send at least every 2-3 minutes for tasks expected to take >5 minutes.\n"
        f"This prevents stall detection from flagging task {task.id} as stuck."
    )
    sections.append(_PromptSection(
        name="progress_reporting",
        text=progress_reporting,
        mandatory=True,
    ))

    completion_protocol = (
        f"COMPLETION PROTOCOL (REQUIRED):\n"
        f"After finishing ALL code changes for this task, you MUST run:\n"
        f'  cccc task complete {task.id} --changed-file <path> --evidence "summary of changes"\n'
        f"This triggers the verification gate. Do NOT use cccc send for completion.\n"
        f'Only use `cccc send --to @foreman --text "..."` for progress updates or blockers.'
    )
    sections.append(_PromptSection(
        name="completion_protocol",
        text=completion_protocol,
        mandatory=True,
    ))

    report_section = (
        f"Report back to Foreman with:\n"
        f"- progress delta or blockers\n"
        f"- changed files or evidence\n"
        f"- anything still unverified"
    )
    sections.append(_PromptSection(
        name="condensed_semantic_focus",
        text=report_section,
        priority=PromptBudget.PRIORITY_MAP.get("condensed_semantic_focus", 50),
    ))

    # Context store (lowest priority optional)
    if context_text:
        sections.append(_PromptSection(
            name="context_store",
            text=context_text,
            priority=PromptBudget.PRIORITY_MAP.get("context_store", 70),
        ))

    budgeter = PromptBudget()
    result = budgeter.apply(sections)
    return result.text.rstrip() + "\n"


# ---------------------------------------------------------------------------
# Verification summary formatting
# ---------------------------------------------------------------------------

def serialize_validation_issue(issue: Any) -> Dict[str, Any]:
    """Serialize a ValidationIssue to a dict suitable for IPC transmission."""
    return {
        "code": issue.code,
        "severity": issue.severity,
        "message": issue.message,
        "task_ids": list(issue.task_ids),
        "evidence": dict(issue.evidence),
        "confidence": issue.confidence,
        "source": issue.source,
        "action_owner": issue.action_owner,
        "worker_relevance": issue.worker_relevance,
    }


def serialize_validation_report(
    report: Any,
    *,
    semantic_summary: Any = None,
) -> Dict[str, Any]:
    """Serialize a ValidationReport to a dict suitable for IPC transmission."""
    from ...contracts.v1.ralph_ipc import SemanticSummary

    result: Dict[str, Any] = {
        "valid": report.valid,
        "errors": [serialize_validation_issue(i) for i in report.errors],
        "warnings": [serialize_validation_issue(i) for i in report.warnings],
        "hints": [serialize_validation_issue(i) for i in report.hints],
    }
    if semantic_summary is not None:
        if isinstance(semantic_summary, SemanticSummary):
            result["semantic_summary"] = semantic_summary.model_dump()
        elif isinstance(semantic_summary, dict):
            result["semantic_summary"] = semantic_summary
        else:
            result["semantic_summary"] = semantic_summary
    return result


def build_completion_summary(
    *,
    agent_id: str,
    duration_seconds: int,
    changed_files: List[str],
    verification: Optional[Any] = None,
) -> str:
    """Build a human-readable summary for a completed task."""
    files_text = ", ".join(str(path).strip() for path in changed_files if str(path).strip())
    summary = f"agent={str(agent_id or '').strip() or 'unknown'}, duration={int(duration_seconds)}s"
    if files_text:
        summary += f", changed_files={files_text}"
    return append_verification_checks(summary, verification)


def build_failure_summary(
    *,
    agent_name: str,
    error_message: str,
    suggestion: str,
    verification: Optional[Any] = None,
) -> str:
    """Build a human-readable summary for a failed task."""
    summary = f"agent={str(agent_name or '').strip() or 'unknown'}, error={str(error_message or '').strip() or '(none)'}"
    hint = str(suggestion or "").strip()
    if hint:
        summary += f", suggestion={hint}"
    return append_verification_checks(summary, verification)


def append_verification_checks(
    summary: str,
    verification: Optional[Any],
) -> str:
    """Append formatted verification checks to a summary string."""
    checks_text = format_verification_checks(verification)
    if not checks_text:
        return summary
    return f"{summary}\n{checks_text}"


def format_verification_checks(verification: Optional[Any]) -> str:
    """Format verification checks into a multi-line string."""
    if verification is None or not verification.checks:
        return ""
    lines = ["Verification checks:"]
    for check in verification.checks:
        lines.append(f"  {format_verification_check(check)}")
    return "\n".join(lines)


def format_verification_check(check: Any) -> str:
    """Format a single verification check into a string."""
    name = str(getattr(check, "name", "") or "").strip() or "unknown"
    outcome = str(getattr(check, "outcome", "") or "").strip() or "unknown"
    line = f"{name}: {outcome}"

    duration_ms = int(getattr(check, "duration_ms", 0) or 0)
    if duration_ms > 0:
        line += f" ({duration_ms}ms)"

    message = str(getattr(check, "message", "") or "").strip()
    if message:
        line += f" - {message}"
    return line


def build_stalled_summary(
    *,
    agent_id: str,
    threshold_seconds: int,
    idle_seconds: int,
    progress_pct: Optional[int],
) -> str:
    """Build a human-readable summary for a stalled task."""
    summary = (
        f"agent={str(agent_id or '').strip() or 'unknown'}, "
        f"idle_for={int(idle_seconds)}s, threshold={int(threshold_seconds)}s"
    )
    if progress_pct is not None:
        summary += f", progress={int(progress_pct)}%"
    return summary


def extract_evidence_summary(payload: Dict[str, Any]) -> str:
    """Extract a human-readable evidence summary from an event payload."""
    summary = str(payload.get("evidence_summary") or "").strip()
    if summary:
        return summary

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return ""

    for key in ("summary", "text", "message"):
        value = str(evidence.get(key) or "").strip()
        if value:
            return value
    return ""
