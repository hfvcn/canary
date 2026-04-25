"""Validation for literal verification paths that are outside declared coverage."""

from __future__ import annotations

import shlex
from typing import Iterable, List, Sequence

from .models import TaskSpec, ValidationIssue

_LITERAL_EXTENSIONS = (".py", ".ts", ".tsx", ".js")
_WRAPPER_BASES = {"make", "tox", "bash", "sh"}
_SHELL_OPERATORS = {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>", "&"}


def check_covers_paths_unverified(task: TaskSpec) -> List[ValidationIssue]:
    """Warn when compile/unit verification commands reference uncovered literal paths."""
    verification = task.verification
    if verification is None or verification.level not in {"compile", "unit"}:
        return []

    allowed_paths = list(task.claimed_paths) + list(verification.covers.paths)
    issues: List[ValidationIssue] = []

    issues.extend(
        _check_command(
            task.id,
            verification.command,
            "command",
            allowed_paths,
        )
    )
    for check in verification.checks:
        issues.extend(
            _check_command(
                task.id,
                check.command,
                f"check:{check.name}",
                allowed_paths,
            )
        )
    return issues


def _check_command(
    task_id: str,
    command: str,
    command_source: str,
    allowed_paths: Sequence[str],
) -> List[ValidationIssue]:
    command = command.strip()
    if not command or _should_skip_command(command):
        return []

    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    extracted_paths = _extract_literal_paths(tokens)
    issues: List[ValidationIssue] = []
    for path in extracted_paths:
        if _is_covered_path(path, allowed_paths):
            continue
        issues.append(ValidationIssue(
            code="W_COVERS_PATHS_UNVERIFIED",
            severity="warning",
            message=(
                f"task '{task_id}' verification {command_source} references "
                f"'{path}' outside claimed_paths and verification.covers.paths"
            ),
            task_ids=[task_id],
            evidence={
                "path": path,
                "command_source": command_source,
                "command": command,
                "allowed_paths": list(allowed_paths),
            },
        ))
    return issues


def _should_skip_command(command: str) -> bool:
    if any(operator in command for operator in _SHELL_OPERATORS):
        return True
    try:
        tokens = shlex.split(command)
    except ValueError:
        return True
    if not tokens:
        return True
    base = _command_base(tokens[0])
    if base in _WRAPPER_BASES:
        return True
    if base == "npm" and len(tokens) >= 2 and tokens[1] == "run":
        return True
    if base in {"pytest", "py.test"}:
        return _pytest_filter_without_explicit_target(tokens[1:])
    if _is_python_pytest(tokens):
        return _pytest_filter_without_explicit_target(tokens[3:])
    return False


def _extract_literal_paths(tokens: Sequence[str]) -> List[str]:
    paths: List[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in {"-m", "-k", "-c", "--rootdir", "--maxfail", "--ignore"}:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        path = _normalize_token_path(token)
        if not path:
            continue
        if path not in paths:
            paths.append(path)
    return paths


def _normalize_token_path(token: str) -> str:
    cleaned = token.strip("'\"")
    cleaned = cleaned.split("::", 1)[0]
    cleaned = cleaned.rstrip(",")
    if not cleaned:
        return ""
    if cleaned.endswith(_LITERAL_EXTENSIONS) or "/" in cleaned:
        return cleaned
    return ""


def _is_covered_path(path: str, allowed_paths: Iterable[str]) -> bool:
    for allowed in allowed_paths:
        normalized = allowed.rstrip("/")
        if not normalized:
            continue
        if path == normalized or path.startswith(normalized + "/"):
            return True
    return False


def _pytest_filter_without_explicit_target(args: Sequence[str]) -> bool:
    has_k = False
    has_m = False
    for token in args:
        if token == "-k" or token.startswith("-k="):
            has_k = True
            continue
        if token == "-m" or token.startswith("-m="):
            has_m = True
            continue
        if token.startswith("-"):
            continue
        return False
    return has_k or has_m


def _is_python_pytest(tokens: Sequence[str]) -> bool:
    return len(tokens) >= 3 and _command_base(tokens[0]).startswith("python") and tokens[1:3] == ["-m", "pytest"]


def _command_base(token: str) -> str:
    token = token.replace("\\", "/")
    return token.rsplit("/", 1)[-1]
