"""Sign-off structure checks for security-sensitive review tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List

from ..models import Plan, ValidationIssue


SIGNOFF_CHECK_NAME_TOKENS = ("signoff", "sign-off")
SIGNOFF_REFERENCE_TOKENS = (
    "review",
    "sign-off",
    "signoff",
    "审查",
    "签核",
    ".review",
    "review-results",
)
REVIEWER_FIELD_TOKEN = "reviewer"
COMMIT_OR_TIMESTAMP_TOKENS = ("commit", "timestamp")
NO_SIGNOFF_CHECK_REASON = "no-signoff-check"
WEAK_CHECK_REASON = "weak-check"
SIGNOFF_CHECK_NO_PATH_REASON = "signoff-check-no-path-reference"
GREP_COMMANDS = ("grep", "egrep", "fgrep")
SIGNOFF_PATH_EXTENSIONS = (".md", ".json", ".yaml", ".yml", ".txt")
PATH_TOKEN_STRIP_CHARS = "\"'`.,;:()[]{}<>"


@dataclass(frozen=True)
class SignoffStructureDeps:
    flow_requires_verification: Callable[[object], bool]
    covering_tasks_for_flow: Callable[[Plan, Any], list[Any]]
    task_has_independent_review_semantics: Callable[[Any], bool]
    task_has_signoff_reference: Callable[[Any], bool]


def check_signoff_structure(
    plan: Plan,
    deps: SignoffStructureDeps,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not deps.flow_requires_verification(flow):
            continue
        for task in _review_tasks_with_signoff(plan, flow, deps):
            signoff_paths = _signoff_paths_from_task(task)
            issue = _signoff_structure_issue(flow, task, signoff_paths)
            if issue is not None:
                issues.append(issue)
    return issues


def _review_tasks_with_signoff(
    plan: Plan,
    flow: Any,
    deps: SignoffStructureDeps,
) -> list[Any]:
    return [
        task
        for task in deps.covering_tasks_for_flow(plan, flow)
        if deps.task_has_independent_review_semantics(task)
        and deps.task_has_signoff_reference(task)
    ]


def _signoff_structure_issue(
    flow: Any,
    task: Any,
    signoff_paths: list[str],
) -> ValidationIssue | None:
    signoff_checks = _signoff_checks(task)
    if not signoff_checks:
        return _issue(flow, task, reason=NO_SIGNOFF_CHECK_REASON, check_names=[])
    structured = [c for c in signoff_checks if _has_structured_signoff_fields(c)]
    if not structured:
        return _issue(
            flow, task, reason=WEAK_CHECK_REASON,
            check_names=[c.name for c in signoff_checks],
        )
    if any(_check_references_signoff_path(c, signoff_paths) for c in structured):
        return None
    return _issue(
        flow, task, reason=SIGNOFF_CHECK_NO_PATH_REASON,
        check_names=[c.name for c in structured],
    )


def _signoff_checks(task: Any) -> list[Any]:
    verification = getattr(task, "verification", None)
    if verification is None:
        return []
    return [
        check
        for check in verification.checks
        if _is_signoff_check_name(getattr(check, "name", ""))
    ]


def task_has_signoff_reference(task: Any) -> bool:
    claimed_paths = getattr(task, "claimed_paths", []) or []
    if any(_text_has_any_token(path, SIGNOFF_REFERENCE_TOKENS) for path in claimed_paths):
        return True
    verification = getattr(task, "verification", None)
    if verification is None:
        return False
    if _text_has_any_token(verification.command, SIGNOFF_REFERENCE_TOKENS):
        return True
    return any(
        _text_has_any_token(f"{check.name} {check.command}", SIGNOFF_REFERENCE_TOKENS)
        for check in verification.checks
    )


def _is_signoff_check_name(name: str) -> bool:
    return _text_has_any_token(name, SIGNOFF_CHECK_NAME_TOKENS)


def _has_structured_signoff_fields(check: Any) -> bool:
    if not getattr(check, "required", True):
        return False
    command = str(getattr(check, "command", "") or "").casefold()
    if _is_grep_command(command):
        return False
    return REVIEWER_FIELD_TOKEN in command and any(
        token in command for token in COMMIT_OR_TIMESTAMP_TOKENS
    )


def _is_grep_command(command: str) -> bool:
    parts = command.strip().split()
    return bool(parts) and parts[0].casefold() in GREP_COMMANDS


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1] if "/" in path else path


def _signoff_paths_from_task(task: Any) -> list[str]:
    paths: list[str] = []
    for path in getattr(task, "claimed_paths", []) or []:
        signoff_path = str(path)
        if not _text_has_any_token(signoff_path, SIGNOFF_REFERENCE_TOKENS):
            continue
        if signoff_path not in paths:
            paths.append(signoff_path)
    verification = getattr(task, "verification", None)
    if verification is not None:
        for path in _file_like_tokens(getattr(verification, "command", "")):
            if not _text_has_any_token(path, SIGNOFF_REFERENCE_TOKENS):
                continue
            if path not in paths:
                paths.append(path)
    return paths


def _file_like_tokens(command: str) -> list[str]:
    tokens: list[str] = []
    for token in str(command or "").split():
        path = token.strip(PATH_TOKEN_STRIP_CHARS)
        if path and _is_file_like_token(path):
            tokens.append(path)
    return tokens


def _is_file_like_token(token: str) -> bool:
    lowered = token.casefold()
    return "/" in token or any(
        lowered.endswith(extension) for extension in SIGNOFF_PATH_EXTENSIONS
    )


def _check_references_signoff_path(check: Any, signoff_paths: list[str]) -> bool:
    command = str(getattr(check, "command", "") or "")
    for path in signoff_paths:
        if path and path in command:
            return True
        base = _basename(path)
        if base and base in command:
            return True
    return False


def _text_has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(token.casefold() in lowered for token in tokens)


def _issue(
    flow: Any,
    task: Any,
    *,
    reason: str,
    check_names: list[str],
) -> ValidationIssue:
    return ValidationIssue(
        code="W_SIGNOFF_STRUCTURE_WEAK",
        severity="warning",
        message=(
            f"security-sensitive flow '{flow.id}' has an auditable sign-off "
            f"reference with weak structure in review task '{task.id}'"
        ),
        task_ids=[task.id],
        evidence={
            "flow_id": flow.id,
            "task_id": task.id,
            "reason": reason,
            "check_names": check_names,
        },
    )
