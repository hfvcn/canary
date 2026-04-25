"""Advisory rules added 2026-04-08 from phase4-remediation Codex review findings.

See todo/问题清单-v5-ralph.md §一 RVCMD-1/RVCMD-2/RFILE-1/RAPI-1/RCONTRACT-1
for rationale.
"""

from __future__ import annotations

import ast
import io
import re
import shlex
import tokenize
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .graph_utils import transitive_deps
from .models import Plan, ValidationIssue
from .workspace_index import WorkspaceIndex

__all__ = [
    "check_verification_command_syntax",
    "check_inline_assertions",
    "check_verification_script_ownership",
    "check_addresses_file_alignment",
    "check_api_signature_consistency",
    "check_new_return_structure_ownership",
    "check_goal_hardcoded_awareness",
]

_PYTHON_C_FLAG = "-c"
_INLINE_ASSERTIONS_COMMAND_RE = re.compile(r"""python\s+-c\s+(["']).*assert.*\1""", re.IGNORECASE)
_SCRIPT_PATH_RE = re.compile(r"(scripts|bin|tools)/[\w/.-]+\.(py|sh|bash)")
_METHOD_CALL_RE = re.compile(r"([\w.]+)\.(\w+)\(([^)]*)\)")
_ASSERT_ATTR_RE = re.compile(
    r"assert\s+(not\s+)?hasattr\([^,]+,\s*['\"]([^'\"]+)['\"]\)",
    re.IGNORECASE,
)
_GOAL_ATTR_RE = re.compile(r"MUST\s+(NOT\s+)?have\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_MODEL_MUTATION_RE = (
    r"\badd\b.{{0,40}}\bto\b.{{0,10}}\b{model}\b"
    r"|\bextend\b.{{0,10}}\b{model}\b"
)
_GOAL_HEX_LITERAL_RE = re.compile(r"\b0x[0-9A-Fa-f]{2,}\b")
_GOAL_BYTE_ARRAY_RE = re.compile(r"\[\s*0x[0-9A-Fa-f]{2,}(?:\s*,\s*0x[0-9A-Fa-f]{2,})+\s*\]")
_STDLIB_METHODS = frozenset(
    {"append", "extend", "join", "model_dump", "model_validate", "split", "startswith", "endswith", "strip"}
)
_RETURN_FIELD_INDICATORS = [
    re.compile(r"\bin result\b", re.IGNORECASE),
    re.compile(r"\bin response\b", re.IGNORECASE),
    re.compile(r"\bin workflow_data\b", re.IGNORECASE),
    re.compile(r"返回.{0,20}字段", re.IGNORECASE),
    re.compile(r"\bnew field\b", re.IGNORECASE),
    re.compile(r"\bextend\b.{0,40}\bwith\b", re.IGNORECASE),
    re.compile(r"\bVerificationResult\b.{0,40}\bfield\b", re.IGNORECASE),
    re.compile(r"\bDaemonResponse\b.{0,40}\bfield\b", re.IGNORECASE),
]


def check_verification_command_syntax(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        constraints = _goal_attr_constraints(task.goal_behavior)
        for source, command in _iter_verification_commands(task):
            payload = _extract_python_c_payload(command)
            if payload is not None and _contains_literal_backslash_n(payload):
                issues.append(_issue(
                    "W_VERIFICATION_COMMAND_INVALID_SYNTAX",
                    "warning",
                    task.id,
                    f"task '{task.id}' {source} contains literal \\n outside a string in python -c payload",
                    {"command_source": source, "command": command},
                ))
            if payload is not None:
                issues.extend(_python_payload_syntax_issues(task.id, source, command, payload))
            issues.extend(_intent_mismatch_issues(task.id, task.goal_behavior, source, command, constraints))
    return issues


def check_inline_assertions(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        for check in verification.checks:
            if not _uses_inline_assertions(check.command):
                continue
            issues.append(_issue(
                "H_INLINE_ASSERTIONS",
                "hint",
                task.id,
                f"task '{task.id}' check '{check.name}' uses inline python -c assertions — consider moving to a test file under tests/ for better visibility to coverage and AST tools",
                {"check_name": check.name, "command": check.command},
            ))
    return issues


def check_verification_script_ownership(
    plan: Plan,
    workspace: WorkspaceIndex | None = None,
) -> List[ValidationIssue]:
    if workspace is None:
        return []
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}
    all_claimed = {path for task in plan.tasks for path in task.claimed_paths}
    for task in plan.tasks:
        allowed = set(task.claimed_paths) | set(task.awareness_paths)
        for dep_id in transitive_deps(task.id, task_map):
            allowed.update(task_map[dep_id].claimed_paths)
        for source, command in _iter_verification_commands(task):
            for script_path in _extract_script_paths(command):
                if not workspace.path_exists(script_path):
                    if not _path_is_covered(script_path, all_claimed):
                        issues.append(_issue(
                            "E_VERIFICATION_SCRIPT_MISSING",
                            "error",
                            task.id,
                            f"task '{task.id}' {source} references missing script '{script_path}'",
                            {"command_source": source, "script_path": script_path},
                        ))
                    continue
                if not _path_is_covered(script_path, allowed):
                    issues.append(_issue(
                        "W_VERIFICATION_SCRIPT_UNOWNED",
                        "warning",
                        task.id,
                        f"task '{task.id}' {source} references script '{script_path}' outside owned context",
                        {"command_source": source, "script_path": script_path},
                    ))
    return issues


def check_addresses_file_alignment(
    plan: Plan,
    issue_file_map: Dict[str, Set[str]] | None = None,
) -> List[ValidationIssue]:
    if not issue_file_map:
        return []
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        covered = set(task.claimed_paths) | set(task.awareness_paths)
        for issue_id in task.addresses:
            hot_files = issue_file_map.get(issue_id, set())
            if hot_files and not any(_path_is_covered(path, covered) for path in hot_files):
                issues.append(_issue(
                    "W_ADDRESSES_HOT_FILE_GAP",
                    "warning",
                    task.id,
                    f"task '{task.id}' addresses '{issue_id}' but does not cover any hot file",
                    {"issue_id": issue_id, "hot_files": sorted(hot_files), "covered_paths": sorted(covered)},
                ))
    return issues


def check_api_signature_consistency(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    method_hosts: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    host_methods: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for location, text in _iter_api_texts(plan):
        for host, method, arg_count in _extract_method_call_tuples(text):
            if method in _STDLIB_METHODS:
                continue
            method_hosts[method].append((host, location, arg_count))
            host_methods[(host, method)].append((location, arg_count))
    issues.extend(_api_host_drift_issues(method_hosts))
    issues.extend(_api_args_drift_issues(host_methods))
    return issues


def check_new_return_structure_ownership(
    plan: Plan,
    extra_forbid_models: Dict[str, str] | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if task.role == "verification":
            continue
        combined = f"{task.goal_behavior}\n{task.acceptance_criteria}"
        if _mentions_new_return_field(combined) and not _has_contract_claim(task.claimed_paths):
            issues.append(_issue(
                "W_NEW_RETURN_FIELD_NOT_IN_CONTRACT",
                "warning",
                task.id,
                f"task '{task.id}' introduces return fields without claiming a contract/model file",
                {"claimed_paths": task.claimed_paths},
            ))
        for model_name, model_path in (extra_forbid_models or {}).items():
            if _mentions_model_field_extension(combined, model_name) and not _path_is_covered(model_path, task.claimed_paths):
                issues.append(_issue(
                    "E_EXTRA_FORBID_MODEL_EXTENSION_UNCLAIMED",
                    "error",
                    task.id,
                    f"task '{task.id}' extends extra=forbid model '{model_name}' without claiming '{model_path}'",
                    {"model": model_name, "model_path": model_path},
                ))
    return issues


def check_goal_hardcoded_awareness(
    plan: Plan,
    workspace: WorkspaceIndex | None = None,
) -> List[ValidationIssue]:
    if workspace is None:
        return []
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if not task.awareness_paths:
            continue
        hardcoded_values = _extract_goal_hardcoded_values(task.goal_behavior)
        if not hardcoded_values:
            continue
        awareness_texts = _read_workspace_files(task.awareness_paths, workspace)
        claimed_texts = _read_workspace_files(task.claimed_paths, workspace)
        for value in hardcoded_values:
            if _value_in_texts(value, claimed_texts):
                continue
            if _value_in_texts(value, awareness_texts):
                continue
            issues.append(_issue(
                "W_GOAL_HARDCODED_WITHOUT_AWARENESS",
                "warning",
                task.id,
                f"task '{task.id}' goal_behavior contains hardcoded value '{value}' not found in awareness_paths files — consider adding the source file to awareness_paths",
                {"value": value, "awareness_paths": list(task.awareness_paths)},
            ))
    return issues


def _extract_python_c_payload(cmd: str) -> Optional[str]:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None
    if not tokens or "python" not in tokens[0]:
        return None
    for idx, token in enumerate(tokens[:-1]):
        if token == _PYTHON_C_FLAG:
            return tokens[idx + 1]
    return None


def _uses_inline_assertions(command: str) -> bool:
    if not _INLINE_ASSERTIONS_COMMAND_RE.search(command):
        return False
    payload = _extract_python_c_payload(command)
    return payload is not None and "assert" in payload.lower()


def _extract_method_call_tuples(text: str) -> List[Tuple[str, str, int]]:
    calls: List[Tuple[str, str, int]] = []
    for host, method, args in _METHOD_CALL_RE.findall(text):
        arg_count = len([part for part in (arg.strip() for arg in args.split(",")) if part])
        calls.append((host, method, arg_count))
    return calls


def _iter_verification_commands(task: object) -> Iterable[tuple[str, str]]:
    verification = getattr(task, "verification", None)
    if verification is None:
        return
    if verification.command.strip():
        yield "verification.command", verification.command
    for index, check in enumerate(verification.checks):
        if check.command.strip():
            yield f"verification.checks[{index}].command", check.command


def _python_payload_syntax_issues(task_id: str, source: str, command: str, payload: str) -> List[ValidationIssue]:
    try:
        ast.parse(payload)
    except SyntaxError as exc:
        return [_issue(
            "W_VERIFICATION_COMMAND_INVALID_SYNTAX",
            "warning",
            task_id,
            f"task '{task_id}' {source} has invalid python -c payload: {exc.msg}",
            {"command_source": source, "command": command, "syntax_error": exc.msg},
        )]
    return []


def _intent_mismatch_issues(
    task_id: str,
    goal_behavior: str,
    source: str,
    command: str,
    constraints: Dict[str, bool],
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for negated, attr_name in _ASSERT_ATTR_RE.findall(command):
        expected = constraints.get(attr_name.lower())
        if expected is None:
            continue
        asserted_has_attr = not bool(negated.strip())
        if asserted_has_attr != expected:
            issues.append(_issue(
                "W_VERIFICATION_INTENT_MISMATCH",
                "hint",
                task_id,
                f"task '{task_id}' {source} assert direction conflicts with goal for '{attr_name}'",
                {"command_source": source, "attribute": attr_name, "goal_behavior": goal_behavior},
            ))
    return issues


def _contains_literal_backslash_n(payload: str) -> bool:
    masked = list(payload)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(payload).readline)
        for token_info in tokens:
            if token_info.type != tokenize.STRING:
                continue
            start = _offset_for(payload, token_info.start)
            end = _offset_for(payload, token_info.end)
            masked[start:end] = " " * max(0, end - start)
    except tokenize.TokenError:
        pass
    return "\\n" in "".join(masked)


def _goal_attr_constraints(goal_behavior: str) -> Dict[str, bool]:
    return {attr.lower(): not bool(negated.strip()) for negated, attr in _GOAL_ATTR_RE.findall(goal_behavior)}


def _extract_script_paths(command: str) -> Set[str]:
    return {match.group(0) for match in _SCRIPT_PATH_RE.finditer(command)}


def _extract_goal_hardcoded_values(goal_behavior: str) -> List[str]:
    matches: List[tuple[int, str]] = []
    matches.extend((match.start(), match.group(0)) for match in _GOAL_BYTE_ARRAY_RE.finditer(goal_behavior))
    matches.extend((match.start(), match.group(0)) for match in _GOAL_HEX_LITERAL_RE.finditer(goal_behavior))
    matches.sort(key=lambda item: item[0])
    ordered: List[str] = []
    seen: Set[str] = set()
    for _, value in matches:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _iter_api_texts(plan: Plan) -> Iterable[tuple[str, str]]:
    for task in plan.tasks:
        yield f"{task.id}.goal_behavior", task.goal_behavior
        yield f"{task.id}.acceptance_criteria", task.acceptance_criteria
        verification = task.verification
        if verification is None:
            continue
        if verification.command.strip():
            yield f"{task.id}.verification.command", verification.command
        for index, check in enumerate(verification.checks):
            yield f"{task.id}.verification.checks[{index}].command", check.command
    for flow in plan.forbidden_flows:
        yield f"forbidden_flows.{flow.id}.description", flow.description


def _api_host_drift_issues(method_hosts: dict[str, list[tuple[str, str, int]]]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for method, records in method_hosts.items():
        hosts = {host for host, _, _ in records}
        if len(hosts) < 2:
            continue
        evidence = [{"host": host, "location": location, "arg_count": arg_count} for host, location, arg_count in records]
        issues.append(_issue("W_API_HOST_DRIFT", "warning", "", f"method '{method}' appears with multiple hosts", {"method": method, "occurrences": evidence}))
    return issues


def _api_args_drift_issues(host_methods: dict[tuple[str, str], list[tuple[str, int]]]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for (host, method), records in host_methods.items():
        arg_counts = {arg_count for _, arg_count in records}
        if len(arg_counts) < 2:
            continue
        evidence = [{"location": location, "arg_count": arg_count} for location, arg_count in records]
        issues.append(_issue("W_API_ARGS_DRIFT", "warning", "", f"method '{host}.{method}' appears with multiple argument counts", {"host": host, "method": method, "occurrences": evidence}))
    return issues


def _mentions_new_return_field(text: str) -> bool:
    return any(pattern.search(text) for pattern in _RETURN_FIELD_INDICATORS)


def _mentions_model_field_extension(text: str, model_name: str) -> bool:
    pattern = re.compile(_MODEL_MUTATION_RE.format(model=re.escape(model_name)), re.IGNORECASE | re.DOTALL)
    return bool(pattern.search(text))


def _has_contract_claim(claimed_paths: List[str]) -> bool:
    for path in claimed_paths:
        if path.startswith("src/cccc/contracts/v1/") and path.endswith(".py"):
            return True
        if path.endswith("/models.py") or path.endswith("_types.py") or path.endswith("/ipc.py"):
            return True
    return False


def _path_is_covered(path: str, covered_paths: Iterable[str]) -> bool:
    return any(path == covered or path.startswith(f"{covered.rstrip('/')}/") for covered in covered_paths)


def _read_workspace_files(paths: Iterable[str], workspace: WorkspaceIndex) -> List[str]:
    texts: List[str] = []
    for rel_path in paths:
        if not workspace.path_exists(rel_path):
            continue
        try:
            text = (workspace.project_root / rel_path).read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, OSError, UnicodeDecodeError):
            continue
        texts.append(text)
    return texts


def _value_in_texts(value: str, texts: Iterable[str]) -> bool:
    return any(value in text for text in texts)


def _offset_for(source: str, position: tuple[int, int]) -> int:
    row, col = position
    lines = source.splitlines(keepends=True)
    return sum(len(line) for line in lines[: row - 1]) + col


def _issue(
    code: str,
    severity: str,
    task_id: str,
    message: str,
    evidence: Optional[dict] = None,
) -> ValidationIssue:
    task_ids = [task_id] if task_id else []
    return ValidationIssue(code=code, severity=severity, message=message, task_ids=task_ids, evidence=evidence or {})
