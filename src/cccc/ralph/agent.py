"""Shared error-envelope definitions for the Ralph subsystem.

Provides a single source of truth for:
- Processing stages (RALPH_STAGES)
- Internal error codes (RULE_ERROR_REGISTRY)
- Structured error envelope builder (build_error_envelope)
- Rule capability manifest (RULE_REGISTRY)

Used by the CLI, daemon IPC, and orchestrator surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

import yaml

from .models import Plan, ValidationIssue

log = logging.getLogger(__name__)

GEMINI_PROVIDER = "gemini-cli"
STUB_PROVIDER = "stub"
GEMINI_FLASH_MODEL = "flash"
GEMINI_TIMEOUT_SECONDS = 120
GEMINI_WARMUP_TIMEOUT_SECONDS = 60
GEMINI_JSON_RETRY_ATTEMPTS = 2
GEMINI_JSON_RETRY_DELAY_SECONDS = 2
GEMINI_WARMUP_PROMPT = 'Return exactly this JSON: {"ok": true}'
ALLOWED_CONFIDENCE = frozenset({"low", "medium", "high"})
ADVISORY_NOTICE = "Agent suggestions are advisory only and have no decision authority."
SECURITY_CHECKLIST_HEADER = "## Security Checklist"
SECURITY_CHECKLIST_ITEMS = (
    (
        (
            "input-validation",
            "input validation",
            "fts",
            "sql",
            "xss",
            "injection",
        ),
        (
            "Verify: Are all user inputs validated? Can FTS5/SQL operators be injected? "
            "Are there resource limits (pagination, body size)?"
        ),
    ),
    (
        ("ssrf",),
        (
            "Verify: Does URL validation handle encoded IPs, DNS rebinding, "
            "redirects?"
        ),
    ),
    (
        ("auth", "token", "key"),
        (
            "Verify: Is token comparison timing-safe? Are secrets hardcoded?"
        ),
    ),
    (
        ("token type", "type confusion", "token-type"),
        (
            "Verify: Does token validation check the type field? Can a refresh "
            "token be used as an access token? Are different token types "
            "handled distinctly?"
        ),
    ),
    (
        ("toctou", "temporal", "store-then-use", "store_then_use"),
        (
            "Verify: Is data revalidated after retrieval? Can backing state "
            "change between store and use? Are concurrent mutations handled "
            "safely?"
        ),
    ),
    (
        ("race condition", "race-condition", "concurrent write"),
        (
            "Verify: Are critical sections protected? Do concurrent operations "
            "use barrier-based synchronization for true concurrency testing?"
        ),
    ),
)
CRITICAL_FLOW_NAME_FIELDS = (
    "id",
    "name",
    "title",
    "description",
    "surface_type",
    "temporal_pattern",
)
T = TypeVar("T")


@dataclass(frozen=True)
class AgentConfig:
    provider: str = "stub"
    enabled: bool = True
    api_key_env: str = ""
    command: tuple[str, ...] = ("gemini",)
    model: str = GEMINI_FLASH_MODEL
    timeout_seconds: int = GEMINI_TIMEOUT_SECONDS
    warmup_enabled: bool = True
    warmup_timeout_seconds: int = GEMINI_WARMUP_TIMEOUT_SECONDS


class GeminiResponseError(RuntimeError):
    """Gemini CLI returned output that cannot be converted to suggestions."""


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
    """Advisory agent wrapper for beyond-scope Ralph validation findings.

    Gemini CLI is the production provider. The stub provider is only used when
    explicitly configured by tests or a caller that asks for static suggestions.
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
        self._warmed_up = False
        self._resume_warmed_session = False
        self._checklist: List[Dict[str, Any]] = []
        if checklist_path is not None:
            self._checklist = _load_checklist(checklist_path)

    def _is_available(self) -> bool:
        if not self.config.enabled:
            return False
        if self.config.provider in {STUB_PROVIDER, GEMINI_PROVIDER}:
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

    def warm_up(self) -> None:
        """Run a minimal provider call so the first real review is not cold."""
        if self._warmed_up or not self.available:
            return
        if not self.config.warmup_enabled:
            return
        if self.config.provider == STUB_PROVIDER:
            self._warmed_up = True
            return
        if self.config.provider != GEMINI_PROVIDER:
            raise RuntimeError(f"Unsupported Ralph Agent provider: {self.config.provider}")
        subprocess.run(
            self._gemini_command(GEMINI_WARMUP_PROMPT, resume_warmed_session=False),
            capture_output=True,
            check=True,
            text=True,
            timeout=self.config.warmup_timeout_seconds,
        )
        self._warmed_up = True
        self._resume_warmed_session = True

    def review_beyond_scope(self, issues: list[ValidationIssue]) -> list[AgentSuggestion]:
        """Review beyond-scope issues and return advisory suggestions.

        Gemini CLI Flash is used for semantic suggestions. Provider failures are
        raised to the caller so validation cannot silently degrade.
        """
        if not self.available:
            return []

        beyond = [i for i in issues if i.beyond_scope]
        if not beyond:
            return []

        if self.config.provider == GEMINI_PROVIDER:
            return self._review_with_gemini(beyond)
        if self.config.provider == STUB_PROVIDER:
            return self._stub_suggestions(beyond)

        raise RuntimeError(f"Unsupported Ralph Agent provider: {self.config.provider}")

    def verify_task_completion(
        self,
        task: Any,
        *,
        changed_files: list[str],
        project_root: Path,
        source_context: Dict[str, str] | None = None,
        git_diff: str = "",
        verification_output: Dict[str, Any] | None = None,
        critical_flows: list[Any] | None = None,
    ) -> Dict[str, Any]:
        """Run Ralph Agent verification for Foreman-preset simulation cases."""
        if not self.available:
            raise RuntimeError("Ralph Agent verification is disabled")
        if self.config.provider != GEMINI_PROVIDER:
            raise RuntimeError("Ralph Agent verification requires Gemini provider")
        prompt = self._build_verification_prompt(
            task=task,
            changed_files=changed_files,
            project_root=project_root,
            source_context=source_context,
            git_diff=git_diff,
            verification_output=verification_output,
            critical_flows=critical_flows,
        )
        task_id = str(task.id)
        return self._run_gemini_json_retry(
            prompt,
            parser=lambda stdout: _parse_agent_verification_payload(stdout, task_id),
            operation=f"verification for task {task_id}",
            fallback=lambda: _degraded_agent_verification_result(task_id),
        )

    def _build_verification_prompt(
        self,
        *,
        task: Any,
        changed_files: list[str],
        project_root: Path,
        source_context: Dict[str, str] | None = None,
        git_diff: str = "",
        verification_output: Dict[str, Any] | None = None,
        critical_flows: list[Any] | None = None,
    ) -> str:
        task_context = self._agent_verification_task_context(task)
        if critical_flows:
            task_context["critical_flows"] = [
                _critical_flow_context(flow) for flow in critical_flows
            ]
        payload: Dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "project_root": str(project_root),
            "changed_files": list(changed_files),
            "task": task_context,
            "response_schema": {
                "passed": "boolean",
                "summary": "short explanation",
                "checks": [
                    {
                        "name": "simulation case name",
                        "outcome": "passed|failed",
                        "message": "why this case passed or failed",
                    }
                ],
            },
        }
        if source_context:
            payload["source_code"] = source_context
        if git_diff:
            payload["git_diff"] = git_diff
        if verification_output:
            payload["verification_output"] = verification_output
        context = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        base_prompt = (
            "Run Ralph Agent verification for a completed task.\n\n"
            "## Rules\n"
            "1. Base your analysis ONLY on the evidence provided below: "
            "source_code, git_diff, and verification_output.\n"
            "2. If source_code shows a function/class referenced in "
            "goal_behavior does NOT exist, report it as failed.\n"
            "3. If git_diff is empty and the task goal is to CREATE or "
            "MODIFY code (add, fix, change, implement, refactor, delete), "
            "report failed — nothing was changed. However, if the goal is "
            "to VERIFY, ENSURE, CHECK, AUDIT, or REVIEW existing code, "
            "an empty diff is expected — judge based on source_code and "
            "verification_output instead.\n"
            "3b. If git_diff states 'project has no prior commits' and the "
            "task creates new files, this is expected — judge based on "
            "source_code and verification_output, not the diff.\n"
            "4. If verification_output.status is 'passed' (all compile/test "
            "checks succeeded), do NOT fabricate failures. Only fail the "
            "task if you find a concrete gap between goal_behavior and the "
            "actual source_code.\n"
            "5. NEVER claim a function exists, is called, or works correctly "
            "unless you can see it in source_code. If source_code is "
            "truncated, state what you CAN verify and what you CANNOT.\n"
            "6. Do not use tools, shell commands, file reads, MCP, or "
            "workspace inspection.\n"
            "7. Return only JSON matching response_schema. No prose.\n"
            "8. Validate goal_behavior logic: Check that any set construction, "
            "loops, conditions, or variable transformations described in "
            "goal_behavior are internally consistent. If the described logic "
            "would produce wrong results (e.g., collecting from 'all tasks' "
            "without excluding self, iterating without boundary), mark as "
            "failed with specific explanation.\n"
            "9. Validate goal_behavior assumptions: Check that goal_behavior "
            "assumptions about pre-conditions, existing helper functions, data "
            "structure state, and runtime behavior match what source_code "
            "actually shows. If goal_behavior says 'function X only does Y' "
            "but source_code shows X already does Z, flag the contradiction.\n\n"
            f"{context}"
        )
        return _append_security_checklist(base_prompt, critical_flows)

    def _agent_verification_task_context(self, task: Any) -> Dict[str, Any]:
        verification = task.verification.model_dump() if task.verification else None
        return {
            "id": task.id,
            "title": task.title,
            "role": task.role,
            "type": task.type,
            "goal_behavior": task.goal_behavior,
            "acceptance_criteria": task.acceptance_criteria,
            "claimed_paths": list(task.claimed_paths),
            "verification_mode": task.verification_mode,
            "foreman_preset_simulation_cases": verification,
        }

    def _review_with_gemini(self, issues: list[ValidationIssue]) -> list[AgentSuggestion]:
        prompt = self._build_gemini_prompt(issues)
        return self._run_gemini_json_retry(
            prompt,
            parser=lambda stdout: self._parse_gemini_output(stdout, issues),
            operation="review",
        )

    def _run_gemini_prompt(self, prompt: str) -> str:
        result = subprocess.run(
            self._gemini_command(prompt),
            capture_output=True,
            check=True,
            text=True,
            timeout=self.config.timeout_seconds,
        )
        return result.stdout

    def _run_gemini_json_retry(
        self,
        prompt: str,
        *,
        parser: Callable[[str], T],
        operation: str,
        fallback: Callable[[], T] | None = None,
    ) -> T:
        first_error: GeminiResponseError | None = None
        for attempt in range(1, GEMINI_JSON_RETRY_ATTEMPTS + 1):
            try:
                return parser(self._run_gemini_prompt(prompt))
            except GeminiResponseError as exc:
                if first_error is None:
                    first_error = exc
                if attempt == GEMINI_JSON_RETRY_ATTEMPTS:
                    return self._raise_or_fallback(first_error, fallback)
                log.warning(
                    "Gemini %s returned invalid JSON on attempt %d/%d: %s",
                    operation,
                    attempt,
                    GEMINI_JSON_RETRY_ATTEMPTS,
                    exc,
                )
                time.sleep(GEMINI_JSON_RETRY_DELAY_SECONDS)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if first_error is not None:
                    return self._raise_or_fallback(first_error, fallback)
                raise
        raise AssertionError("Gemini retry loop exited without a result")

    def _raise_or_fallback(
        self,
        exc: GeminiResponseError,
        fallback: Callable[[], T] | None,
    ) -> T:
        if fallback is not None:
            return fallback()
        raise exc

    def _gemini_command(
        self,
        prompt: str,
        *,
        resume_warmed_session: bool = True,
    ) -> list[str]:
        command = [
            *self.config.command,
            "--model",
            self.config.model,
            "--output-format",
            "json",
            "--skip-trust",
        ]
        if resume_warmed_session and self._resume_warmed_session:
            command.extend(["--resume", "latest"])
        command.extend(["--prompt", prompt])
        return command

    def _build_gemini_prompt(self, issues: list[ValidationIssue]) -> str:
        payload = {
            "workflow_id": self.workflow_id,
            "advisory_notice": ADVISORY_NOTICE,
            "plan_context": self._plan_context(issues),
            "issues": [self._issue_context(issue) for issue in issues],
            "response_schema": {
                "suggestions": [{
                    "issue_id": "ValidationIssue.issue_instance_id or code",
                    "checklist_item_id": "matching beyond_scope_checklist item id",
                    "suggestion": "short advisory suggestion",
                    "confidence": "low|medium|high",
                }],
            },
        }
        context = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        return (
            "Review Ralph beyond-scope validation issues.\n"
            f"{ADVISORY_NOTICE}\n"
            "Do not use tools, shell commands, file reads, MCP, or workspace inspection.\n"
            "Use only the JSON payload below.\n"
            "Return only JSON matching response_schema. Do not include prose.\n\n"
            f"{context}"
        )

    def _plan_context(self, issues: list[ValidationIssue]) -> Dict[str, Any]:
        if self.plan is None:
            return {"available": False, "reason": "plan not provided"}
        task_ids = {tid for issue in issues for tid in issue.task_ids}
        tasks = [task for task in self.plan.tasks if not task_ids or task.id in task_ids]
        return {
            "available": True,
            "schema_version": self.plan.schema_version,
            "task_count": len(self.plan.tasks),
            "relevant_tasks": [self._task_context(task) for task in tasks],
        }

    def _task_context(self, task: Any) -> Dict[str, Any]:
        verification = task.verification.model_dump() if task.verification else None
        return {
            "id": task.id,
            "title": task.title,
            "role": task.role,
            "type": task.type,
            "depends_on": list(task.depends_on),
            "claimed_paths": list(task.claimed_paths),
            "goal_behavior": task.goal_behavior,
            "acceptance_criteria": task.acceptance_criteria,
            "verification_mode": task.verification_mode,
            "verification": verification,
        }

    def _issue_context(self, issue: ValidationIssue) -> Dict[str, Any]:
        matched_item = self._match_checklist(issue)
        return {
            "issue_id": issue.issue_instance_id or issue.code,
            "code": issue.code,
            "severity": issue.severity,
            "message": issue.message,
            "task_ids": list(issue.task_ids),
            "evidence": dict(issue.evidence),
            "checklist_item": matched_item or {"id": "unknown"},
        }

    def _parse_gemini_output(
        self,
        stdout: str,
        issues: list[ValidationIssue],
    ) -> list[AgentSuggestion]:
        payload = _parse_gemini_payload(stdout)
        raw_suggestions = payload.get("suggestions")
        if not isinstance(raw_suggestions, list):
            raise GeminiResponseError("Gemini response missing suggestions list")
        valid_issue_ids = {issue.issue_instance_id or issue.code for issue in issues}
        suggestions: list[AgentSuggestion] = []
        for item in raw_suggestions:
            suggestions.append(_suggestion_from_payload(item, valid_issue_ids))
        if not suggestions:
            raise GeminiResponseError("Gemini response returned no suggestions")
        return suggestions

    def _stub_suggestions(self, issues: list[ValidationIssue]) -> list[AgentSuggestion]:
        return [_stub_suggestion(issue, self._match_checklist(issue)) for issue in issues]

    def _match_checklist(self, issue: ValidationIssue) -> Dict[str, Any] | None:
        """Find the best matching checklist item for an issue.

        Priority: field_content > code_prefix > manual.
        field_content is checked first because it matches on the specific
        issue message, making it more targeted than a broad code prefix.
        """
        field_match: Dict[str, Any] | None = None
        prefix_match: Dict[str, Any] | None = None
        for item in self._checklist:
            match_type = item.get("match_type", "")
            pattern = item.get("pattern", "")
            if match_type == "field_content" and pattern in issue.message:
                if field_match is None:
                    field_match = item
            elif match_type == "code_prefix" and issue.code.startswith(pattern.rstrip("*")):
                if prefix_match is None:
                    prefix_match = item
        if field_match is not None:
            return field_match
        if prefix_match is not None:
            return prefix_match
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


def _stub_suggestion(
    issue: ValidationIssue,
    matched_item: Dict[str, Any] | None,
) -> AgentSuggestion:
    item_id = matched_item.get("id", "unknown") if matched_item else "unknown"
    description = matched_item.get("description", issue.message) if matched_item else issue.message
    return AgentSuggestion(
        issue_id=issue.issue_instance_id or issue.code,
        checklist_item_id=item_id,
        suggestion=f"Requires manual review: {description}",
        confidence="low",
        advisory=True,
    )


def _parse_gemini_payload(stdout: str) -> Dict[str, Any]:
    response_text = _extract_gemini_response(stdout)
    try:
        payload = json.loads(_strip_json_fence(response_text))
    except json.JSONDecodeError as exc:
        raise GeminiResponseError("Gemini response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise GeminiResponseError("Gemini response JSON must be an object")
    return payload


def _extract_gemini_response(stdout: str) -> str:
    raw = str(stdout or "").strip()
    if not raw:
        raise GeminiResponseError("Gemini CLI produced empty output")
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(outer, dict) and isinstance(outer.get("response"), str):
        return outer["response"]
    if isinstance(outer, dict) and any(
        key in outer for key in ("suggestions", "passed", "outcome")
    ):
        return raw
    raise GeminiResponseError("Gemini CLI JSON output missing response")


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    body = lines[1:] if lines else []
    if body and body[-1].strip() == "```":
        body = body[:-1]
    return "\n".join(body).strip()


def _suggestion_from_payload(
    item: object,
    valid_issue_ids: set[str],
) -> AgentSuggestion:
    if not isinstance(item, dict):
        raise GeminiResponseError("Gemini suggestion must be an object")
    issue_id = str(item.get("issue_id", "")).strip()
    suggestion = str(item.get("suggestion", "")).strip()
    if issue_id not in valid_issue_ids or not suggestion:
        raise GeminiResponseError("Gemini suggestion had invalid issue_id or text")
    confidence = str(item.get("confidence", "low")).strip().lower()
    if confidence not in ALLOWED_CONFIDENCE:
        raise GeminiResponseError("Gemini suggestion had invalid confidence")
    return AgentSuggestion(
        issue_id=issue_id,
        checklist_item_id=str(item.get("checklist_item_id", "unknown")).strip() or "unknown",
        suggestion=suggestion,
        confidence=confidence,
        advisory=True,
    )


def _append_security_checklist(
    base_prompt: str,
    critical_flows: list[Any] | None,
) -> str:
    items = _security_checklist_items(critical_flows)
    if not items:
        return base_prompt
    checklist = "\n".join([SECURITY_CHECKLIST_HEADER, *[f"- {item}" for item in items]])
    return f"{base_prompt}\n\n{checklist}"


def _security_checklist_items(critical_flows: list[Any] | None) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for flow in critical_flows or []:
        flow_text = _critical_flow_name_text(flow)
        for keywords, item in SECURITY_CHECKLIST_ITEMS:
            if item in seen:
                continue
            if any(keyword in flow_text for keyword in keywords):
                items.append(item)
                seen.add(item)
    return items


def _critical_flow_name_text(flow: Any) -> str:
    context = _critical_flow_context(flow)
    parts = [str(context.get(field) or "") for field in CRITICAL_FLOW_NAME_FIELDS]
    return " ".join(parts).lower().replace("_", "-")


def _critical_flow_context(flow: Any) -> Dict[str, Any]:
    if isinstance(flow, str):
        return {"id": flow}
    if isinstance(flow, dict):
        return dict(flow)
    model_dump = getattr(flow, "model_dump", None)
    if callable(model_dump):
        data = model_dump()
        if isinstance(data, dict):
            return data
    return {
        "id": str(getattr(flow, "id", "") or ""),
        "name": str(getattr(flow, "name", "") or ""),
        "title": str(getattr(flow, "title", "") or ""),
        "surface_type": str(getattr(flow, "surface_type", "") or ""),
        "temporal_pattern": str(getattr(flow, "temporal_pattern", "") or ""),
    }


def _parse_agent_verification_payload(stdout: str, task_id: str) -> Dict[str, Any]:
    payload = _parse_gemini_payload(stdout)
    outcome = _agent_verification_outcome(payload)
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        raise GeminiResponseError("Ralph Agent verification missing summary")
    checks = _agent_verification_checks(payload.get("checks", []))
    outcome = _consistency_check(outcome, checks, summary)
    return {
        "task_id": task_id,
        "outcome": outcome,
        "reason": summary,
        "checks": checks,
    }


def _consistency_check(
    outcome: str,
    checks: list[Dict[str, Any]],
    summary: str,
) -> str:
    """Override outcome when it contradicts the individual checks."""
    if outcome != "passed" or not checks:
        return outcome
    failed_count = sum(1 for c in checks if c["outcome"] == "failed")
    if failed_count > 0 and failed_count >= len(checks) // 2:
        log.warning(
            "Agent claimed passed but %d/%d checks failed — overriding to failed",
            failed_count,
            len(checks),
        )
        return "failed"
    return outcome


def _agent_verification_outcome(payload: Dict[str, Any]) -> str:
    if "passed" in payload:
        passed = payload["passed"]
        if not isinstance(passed, bool):
            raise GeminiResponseError("Ralph Agent verification passed must be boolean")
        return "passed" if passed else "failed"
    outcome = str(payload.get("outcome", "")).strip().lower()
    if outcome not in {"passed", "failed"}:
        raise GeminiResponseError("Ralph Agent verification outcome must be passed or failed")
    return outcome


def _agent_verification_checks(raw_checks: object) -> list[Dict[str, Any]]:
    if not isinstance(raw_checks, list):
        raise GeminiResponseError("Ralph Agent verification checks must be a list")
    checks: list[Dict[str, Any]] = []
    for item in raw_checks:
        checks.append(_agent_verification_check(item))
    return checks


def _agent_verification_check(item: object) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise GeminiResponseError("Ralph Agent verification check must be an object")
    outcome = str(item.get("outcome", "")).strip().lower()
    if outcome not in {"passed", "failed"}:
        raise GeminiResponseError("Ralph Agent verification check outcome invalid")
    return {
        "name": str(item.get("name", "")).strip() or "agent_simulation",
        "outcome": outcome,
        "message": str(item.get("message", "")).strip(),
    }


def _degraded_agent_verification_result(task_id: str) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "outcome": "failed",
        "reason": "Verification blocked: Gemini response unparseable after retry — "
                  "cannot confirm task correctness; treat as failed",
        "checks": [],
        "degraded": True,
    }


def create_agent(
    checklist_path: Path,
    *,
    workflow_id: str = "",
    plan: Plan | None = None,
    config: AgentConfig | None = None,
) -> RalphAgent:
    """Factory: create a RalphAgent backed by a beyond-scope checklist.

    If *checklist_path* does not exist the agent is still usable — it will
    produce generic suggestions without checklist metadata.
    """
    return RalphAgent(
        workflow_id=workflow_id,
        plan=plan,
        checklist_path=checklist_path,
        config=config,
    )


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
    "E_AEGIS_PLACEHOLDER_CONTENT": _RuleDoc(
        description=(
            "A task title, goal_behavior, or acceptance_criteria contains "
            "placeholder wording such as TODO, TBD, or implement later."
        ),
        why_it_matters=(
            "Placeholder task text gives workers an underspecified target and "
            "turns validation into a false signal because the plan has not "
            "committed to concrete behavior."
        ),
        fix_template=(
            "Replace placeholder wording with the exact behavior and acceptance "
            "condition:\n"
            "  goal_behavior: |\n"
            "    The validator emits E_X when condition Y occurs.\n"
            "  acceptance_criteria: |\n"
            "    pytest tests/test_validator.py::test_condition_y passes"
        ),
        suppress_hint=(
            "Add 'E_AEGIS_PLACEHOLDER_CONTENT' to suppress_codes or pass "
            "--suppress E_AEGIS_PLACEHOLDER_CONTENT on the CLI."
        ),
    ),
    "E_AEGIS_RETIREMENT_TRACK_MISSING": _RuleDoc(
        description=(
            "A refactor task with fallback, adapter, guard, compat, legacy, "
            "or similar patch-shape risk has no aegis.retirement_track."
        ),
        why_it_matters=(
            "Risky refactors often leave the old path alive. Without an explicit "
            "retirement track, compatibility code can become permanent hidden debt."
        ),
        fix_template=(
            "Add retirement metadata to the task:\n"
            "  aegis:\n"
            "    intent: refactor\n"
            "    retirement_track:\n"
            "      old_owner: src/legacy/path.py\n"
            "      deletion_trigger: after migration validation passes\n"
            "      retained: true\n"
            "      retention_reason: compatibility window"
        ),
        suppress_hint=(
            "Add 'E_AEGIS_RETIREMENT_TRACK_MISSING' to suppress_codes or pass "
            "--suppress E_AEGIS_RETIREMENT_TRACK_MISSING on the CLI."
        ),
    ),
    "W_AEGIS_FIX_NO_REPAIR_TRACK": _RuleDoc(
        description="A fix task has no aegis.repair_track metadata.",
        why_it_matters=(
            "Fix work should record the root cause, owner, minimal change, and "
            "verification method so the repair is traceable instead of a patch "
            "with unclear causality."
        ),
        fix_template=(
            "Add repair metadata to the task:\n"
            "  aegis:\n"
            "    intent: fix\n"
            "    repair_track:\n"
            "      root_cause: missing validation branch\n"
            "      canonical_owner: src/service.py\n"
            "      minimal_change: add explicit branch\n"
            "      verification_method: pytest tests/test_service.py -v"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_FIX_NO_REPAIR_TRACK' to suppress_codes or pass "
            "--suppress W_AEGIS_FIX_NO_REPAIR_TRACK on the CLI."
        ),
    ),
    "W_AEGIS_TDD_NO_TEST_PATH": _RuleDoc(
        description=(
            "A fix or feature task does not claim any test path containing "
            "test_, _test, or tests/."
        ),
        why_it_matters=(
            "Fixes and features should name the test surface they change or add. "
            "Without a claimed test path, the plan can drift away from TDD-style "
            "verification."
        ),
        fix_template=(
            "Add a relevant test file or directory to claimed_paths:\n"
            "  claimed_paths:\n"
            "    - src/package/module.py\n"
            "    - tests/test_module.py"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_TDD_NO_TEST_PATH' to suppress_codes or pass "
            "--suppress W_AEGIS_TDD_NO_TEST_PATH on the CLI."
        ),
    ),
    "W_AEGIS_COMPLEX_MISSING_BASELINE": _RuleDoc(
        description=(
            "A complex task has no aegis.baseline_refs even though it has "
            "three or more dependencies, provides or consumes contracts, or "
            "uses role=integration."
        ),
        why_it_matters=(
            "Complex tasks need a named baseline so reviewers and workers can "
            "see what existing behavior, contract, or prior task the change is "
            "anchored to."
        ),
        fix_template=(
            "Add one or more baseline references:\n"
            "  aegis:\n"
            "    baseline_refs:\n"
            "      - plan.yaml#T2\n"
            "      - docs/current-behavior.md#section"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_COMPLEX_MISSING_BASELINE' to suppress_codes or pass "
            "--suppress W_AEGIS_COMPLEX_MISSING_BASELINE on the CLI."
        ),
    ),
    "W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING": _RuleDoc(
        description=(
            "A task goal mentions fallback, adapter, or guard patch-shape work "
            "but does not declare aegis.patch_shape_triage."
        ),
        why_it_matters=(
            "Patch-shape work can create hidden alternate execution paths. "
            "Triage metadata makes the intended shape and risk review explicit."
        ),
        fix_template=(
            "Add patch-shape triage metadata:\n"
            "  aegis:\n"
            "    patch_shape_triage: guard is temporary and covered by tests"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING' to suppress_codes or pass "
            "--suppress W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING on the CLI."
        ),
    ),
    "W_AEGIS_RIPPLE_TRIAGE_MISSING": _RuleDoc(
        description=(
            "A task changes shared, core, or multiply claimed paths without "
            "downstream awareness_paths for affected dependents."
        ),
        why_it_matters=(
            "Shared-path changes can break downstream modules even when the "
            "local task verifies itself. Awareness paths expose the ripple area."
        ),
        fix_template=(
            "Add downstream paths to awareness_paths:\n"
            "  awareness_paths:\n"
            "    - src/app/feature/cache_consumer.py"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_RIPPLE_TRIAGE_MISSING' to suppress_codes or pass "
            "--suppress W_AEGIS_RIPPLE_TRIAGE_MISSING on the CLI."
        ),
    ),
    "W_AEGIS_DECISION_HYGIENE_MISSING": _RuleDoc(
        description=(
            "A task goal introduces new-owner or duplicate-owner risk without "
            "aegis.decision_review metadata."
        ),
        why_it_matters=(
            "Ownership changes should record the review basis so duplicate "
            "routing or competing owners do not become permanent ambiguity."
        ),
        fix_template=(
            "Add decision review metadata:\n"
            "  aegis:\n"
            "    decision_review: owner selection reviewed against current router"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_DECISION_HYGIENE_MISSING' to suppress_codes or pass "
            "--suppress W_AEGIS_DECISION_HYGIENE_MISSING on the CLI."
        ),
    ),
    "W_AEGIS_DRIFT_CHECK_MISSING": _RuleDoc(
        description=(
            "A task decomposes into three or more modules without declaring "
            "aegis.drift_check metadata."
        ),
        why_it_matters=(
            "Multi-module work can drift between subtasks. A drift check names "
            "the comparison or invariant used to keep the pieces aligned."
        ),
        fix_template=(
            "Add drift-check metadata:\n"
            "  aegis:\n"
            "    drift_check: compare module outputs against shared contract"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_DRIFT_CHECK_MISSING' to suppress_codes or pass "
            "--suppress W_AEGIS_DRIFT_CHECK_MISSING on the CLI."
        ),
    ),
    "W_AEGIS_PLAN_NO_COMPAT_BOUNDARY": _RuleDoc(
        description=(
            "A plan has cross-task dependencies but no task declares an "
            "aegis.compat_boundary."
        ),
        why_it_matters=(
            "Dependent tasks need a named compatibility boundary so interface "
            "expectations are explicit during staged execution."
        ),
        fix_template=(
            "Declare the boundary on the owning task:\n"
            "  aegis:\n"
            "    compat_boundary: public cache API remains stable"
        ),
        suppress_hint=(
            "Add 'W_AEGIS_PLAN_NO_COMPAT_BOUNDARY' to suppress_codes or pass "
            "--suppress W_AEGIS_PLAN_NO_COMPAT_BOUNDARY on the CLI."
        ),
    ),
    "E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW": _RuleDoc(
        description=(
            "A task modifies contract, shared, or core paths but its "
            "verification only covers the task itself."
        ),
        why_it_matters=(
            "Ripple-prone paths need cross-scope verification. Self-only "
            "coverage can miss downstream contract or shared-module breakage."
        ),
        fix_template=(
            "Expand verification coverage:\n"
            "  verification:\n"
            "    covers:\n"
            "      tasks: [T1, T2]\n"
            "      paths: [src/cccc/contracts/v1/ralph_ipc.py]"
        ),
        suppress_hint=(
            "Add 'E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW' to suppress_codes or "
            "pass --suppress E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW on the CLI."
        ),
    ),
    "E_AEGIS_SECURITY_CHAIN_MISSING": _RuleDoc(
        description=(
            "A feature task declares a security critical flow but has no "
            "security-related verification check in verification.checks."
        ),
        why_it_matters=(
            "Feature plans that declare security concern need explicit tests. "
            "Generic validation can miss auth, token, injection, XSS, SSRF, or "
            "input-validation regressions."
        ),
        fix_template=(
            "Add a security-related structured check:\n"
            "  verification:\n"
            "    checks:\n"
            "      - name: ssrf behavior test\n"
            "        command: python -m pytest tests/test_security.py -v"
        ),
        suppress_hint=(
            "Add 'E_AEGIS_SECURITY_CHAIN_MISSING' to suppress_codes or pass "
            "--suppress E_AEGIS_SECURITY_CHAIN_MISSING on the CLI."
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
    "E_VERIFICATION_SHALLOW_CRITICAL": 1,
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
    "W_SHARED_PATH_NO_DEPENDENCY": 1,
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
    # Aegis discipline rules
    "E_AEGIS_PLACEHOLDER_CONTENT": 1,
    "E_AEGIS_RETIREMENT_TRACK_MISSING": 1,
    "W_AEGIS_FIX_NO_REPAIR_TRACK": 1,
    "W_AEGIS_TDD_NO_TEST_PATH": 1,
    "W_AEGIS_COMPLEX_MISSING_BASELINE": 1,
    "W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING": 1,
    "W_AEGIS_RIPPLE_TRIAGE_MISSING": 1,
    "W_AEGIS_DECISION_HYGIENE_MISSING": 1,
    "W_AEGIS_DRIFT_CHECK_MISSING": 1,
    "W_AEGIS_PLAN_NO_COMPAT_BOUNDARY": 1,
    "E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW": 1,
    "E_AEGIS_SECURITY_CHAIN_MISSING": 1,
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
