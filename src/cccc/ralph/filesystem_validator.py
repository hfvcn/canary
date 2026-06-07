"""Filesystem-aware validation for verification commands."""

from __future__ import annotations

import ast
import shlex
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .covers_paths_validator import check_covers_paths_unverified
from .graph_utils import transitive_deps
from .models import Plan, TaskSpec, ValidationIssue
from .workspace_index import WorkspaceIndex


# ---------------------------------------------------------------------------
# Daemon-friendly file content cache keyed by (path, st_size, st_mtime_ns)
# ---------------------------------------------------------------------------

_issue_file_map_cache: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
_issue_file_map_path_to_key: Dict[str, Tuple[str, int, int]] = {}


def _stat_key(path: Path) -> Tuple[str, int, int]:
    """Return a cache key tuple ``(str(path), st_size, st_mtime_ns)``."""
    st = path.stat()
    return (str(path), st.st_size, st.st_mtime_ns)


def _load_issue_file_map_cached(path: Path) -> Dict[str, Any]:
    """Load and cache a file's parsed content, invalidating on size/mtime change."""
    try:
        key = _stat_key(path)
    except (OSError, ValueError):
        return {}
    path_str = str(path)
    cached = _issue_file_map_cache.get(key)
    if cached is not None:
        return cached
    old_key = _issue_file_map_path_to_key.get(path_str)
    if old_key is not None and old_key != key:
        _issue_file_map_cache.pop(old_key, None)
    try:
        source = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, IsADirectoryError):
        return {}
    result: Dict[str, Any] = {"_raw": source}
    _issue_file_map_cache[key] = result
    _issue_file_map_path_to_key[path_str] = key
    return result


def clear_issue_file_map_cache() -> None:
    """Reset the module-level issue file map cache (useful in tests)."""
    _issue_file_map_cache.clear()
    _issue_file_map_path_to_key.clear()


_TRIVIAL_COMMANDS = {"true", ":", "echo", "printf"}
_SPLITTABLE_SHELL_OPERATORS = ("&&", ";")
_UNSPLITTABLE_SHELL_OPERATORS = ("2>>", "2>", "||", ">>", "|", ">", "<", "&")
_ALL_SHELL_OPERATORS = _SPLITTABLE_SHELL_OPERATORS + _UNSPLITTABLE_SHELL_OPERATORS
_SHELL_PUNCTUATION_CHARS = "();|&<>"
_SIMPLE_SHELL_LAUNCHERS = frozenset({"bash", "sh"})
_SIMPLE_SHELL_FLAG_CHARS = frozenset({"c", "i", "l"})
_COMPLEX_SHELL_START_TOKENS = frozenset({"if", "for", "while", "until", "case"})
_COMPLEX_SHELL_BLOCK_TOKENS = frozenset({"then", "fi", "elif", "else", "do", "done", "esac"})
_MIN_SUBSHELL_TOKENS = 3
_INDIRECT_IMPORT_FOLD_SAMPLE_COUNT = 5
_INDIRECT_IMPORT_FOLD_THRESHOLD = 10
_PYTEST_FLAGS_WITH_VALUE = {
    "-c",
    "-k",
    "-m",
    "--basetemp",
    "--confcutdir",
    "--deselect",
    "--ignore",
    "--import-mode",
    "--maxfail",
    "--rootdir",
}


def validate_filesystem(
    plan: Plan,
    *,
    project_root: Path,
    workspace: WorkspaceIndex,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    # RV-17: collect all plan-level claimed paths for broader -k downgrade
    all_plan_claimed: Set[str] = set()
    for t in plan.tasks:
        all_plan_claimed.update(t.claimed_paths)

    task_map = {task.id: task for task in plan.tasks}
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        issues.extend(check_covers_paths_unverified(task, task_map))
        projected = workspace.projected_paths(plan, task.id)
        # RV-24: upstream-only projected for self-verification detection
        upstream_projected = workspace.projected_paths(
            plan, task.id, include_self=False,
        )
        commands: list[str] = []
        if verification.command.strip():
            commands.append(verification.command.strip())
        for check in verification.checks:
            command = check.command.strip()
            if command and command not in commands:
                commands.append(command)
        for command in commands:
            issues.extend(
                _check_verification_command(
                    command,
                    task.id,
                    projected,
                    workspace,
                    task.claimed_paths,
                    all_plan_claimed,
                    upstream_projected=upstream_projected,
                )
            )
    issues.extend(_check_test_coverage_gaps(plan, project_root, workspace))
    issues.extend(_check_registration_invariants(plan, project_root, workspace))
    issues.extend(_check_unclaimed_tests_for_source(plan, project_root, workspace))
    return issues


def _iter_shell_operators(cmd: str) -> Iterable[Tuple[int, str]]:
    in_single = False
    in_double = False
    escaped = False
    index = 0
    while index < len(cmd):
        char = cmd[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and not in_single:
            escaped = True
            index += 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            index += 1
            continue
        if in_single or in_double:
            index += 1
            continue
        operator = next(
            (candidate for candidate in _ALL_SHELL_OPERATORS if cmd.startswith(candidate, index)),
            None,
        )
        if operator is None:
            index += 1
            continue
        yield index, operator
        index += len(operator)


def _split_shell_command(cmd: str) -> Optional[List[str]]:
    parts: List[str] = []
    start = 0
    found_split = False
    for index, operator in _iter_shell_operators(cmd):
        if operator not in _SPLITTABLE_SHELL_OPERATORS:
            continue
        parts.append(cmd[start:index].strip())
        start = index + len(operator)
        found_split = True
    if not found_split:
        return None
    parts.append(cmd[start:].strip())
    return parts


def _has_unsplittable_shell_operator(cmd: str) -> bool:
    return any(
        operator in _UNSPLITTABLE_SHELL_OPERATORS
        for _, operator in _iter_shell_operators(cmd)
    )


def _normalize_unquoted_newlines(command: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    normalized: List[str] = []
    for char in command:
        if escaped:
            normalized.append(char)
            escaped = False
            continue
        if char == "\\" and not in_single:
            normalized.append(char)
            escaped = True
            continue
        if char == "'" and not in_double:
            normalized.append(char)
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            normalized.append(char)
            in_double = not in_double
            continue
        if char == "\n" and not in_single and not in_double:
            normalized.append(" ; ")
            continue
        normalized.append(char)
    return "".join(normalized)


def _shell_command_tokens(command: str) -> Optional[List[str]]:
    lexer = shlex.shlex(
        _normalize_unquoted_newlines(command),
        posix=True,
        punctuation_chars=_SHELL_PUNCTUATION_CHARS,
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def _strip_command_wrappers(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens):
        base = _command_base(tokens[index])
        if base == "env":
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if "=" in token and not token.startswith("-"):
                    index += 1
                    continue
                if token in ("-u", "--unset", "-S", "--split-string") and index + 1 < len(tokens):
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                break
            continue
        if base in {"timeout", "gtimeout"}:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                if tokens[index] in ("-s", "--signal", "-k", "--kill-after") and index + 1 < len(tokens):
                    index += 2
                    continue
                index += 1
            if index < len(tokens) and not tokens[index].startswith("-"):
                index += 1
            continue
        if base in {"uv", "poetry", "pipenv"} and index + 1 < len(tokens) and tokens[index + 1] == "run":
            index += 2
            continue
        break
    return tokens[index:]


def _strip_outer_subshell_tokens(tokens: list[str]) -> Optional[list[str]]:
    if len(tokens) < _MIN_SUBSHELL_TOKENS:
        return None
    first_token = tokens[0]
    last_token = tokens[-1]
    if not first_token.startswith("(") or not last_token.endswith(")"):
        return None
    inner_tokens: List[str] = []
    leading = first_token[1:]
    trailing = last_token[:-1]
    if leading:
        inner_tokens.append(leading)
    inner_tokens.extend(tokens[1:-1])
    if trailing:
        inner_tokens.append(trailing)
    return inner_tokens or None


def _simple_shell_script_index(tokens: list[str]) -> Optional[int]:
    if not tokens or _command_base(tokens[0]) not in _SIMPLE_SHELL_LAUNCHERS:
        return None
    index = 1
    has_command_flag = False
    while index < len(tokens):
        token = tokens[index]
        if token == "-c":
            has_command_flag = True
            index += 1
            break
        if not token.startswith("-") or token == "-":
            return None
        flag_chars = token[1:]
        if any(char not in _SIMPLE_SHELL_FLAG_CHARS for char in flag_chars):
            return None
        if "c" in flag_chars:
            has_command_flag = True
            index += 1
            break
        index += 1
    if not has_command_flag or index >= len(tokens):
        return None
    return index


def _has_complex_shell_syntax(script: str) -> bool:
    if "$(" in script or "`" in script or "<<" in script:
        return True
    if _has_unsplittable_shell_operator(script):
        return True
    tokens = _shell_command_tokens(script)
    if not tokens:
        return True
    if tokens[0] in _COMPLEX_SHELL_START_TOKENS:
        return True
    return any(token in _COMPLEX_SHELL_BLOCK_TOKENS for token in tokens)


def _unwrap_simple_shell_launcher(tokens: list[str]) -> Optional[list[str]]:
    script_index = _simple_shell_script_index(tokens)
    if script_index is None or script_index != len(tokens) - 1:
        return None
    script = tokens[script_index]
    if _has_complex_shell_syntax(script):
        return None
    return _shell_command_tokens(script)


def _check_test_coverage_gaps(
    plan: Plan,
    project_root: Path,
    workspace: WorkspaceIndex,
) -> List[ValidationIssue]:
    tests_root = project_root / "tests"
    if not tests_root.is_dir():
        return []

    commands = [
        task.verification.command
        for task in plan.tasks
        if task.verification and task.verification.command.strip()
    ]
    issues: List[ValidationIssue] = []

    direct_gaps: dict[tuple[str, str], list[str]] = {}
    indirect_gaps: dict[tuple[str, str], list[str]] = {}
    dynamic_hints: list[ValidationIssue] = []

    conftest_gaps: dict[tuple[str, str], list[str]] = {}

    for task in plan.tasks:
        for source_path in _claimed_source_paths(task.claimed_paths):
            module_names = _module_names_for_path(source_path)
            if not module_names:
                continue
            for test_path in _grep_test_candidates(tests_root, project_root, source_path, module_names):
                issue = _coverage_gap_issue(task.id, source_path, test_path, module_names, commands, workspace)
                if issue is None:
                    continue
                if issue.code == "W_DYNAMIC_TEST_IMPORT_OPAQUE":
                    dynamic_hints.append(issue)
                    continue
                key = (task.id, source_path)
                # Conftest files are a separate category regardless of name match
                if Path(test_path).name == "conftest.py":
                    if test_path not in conftest_gaps.setdefault(key, []):
                        conftest_gaps[key].append(test_path)
                else:
                    gaps = direct_gaps if _is_direct_test_file(test_path, source_path) else indirect_gaps
                    if test_path not in gaps.setdefault(key, []):
                        gaps[key].append(test_path)

    # Conftest gaps — always warning
    for (task_id, source_path), test_paths in conftest_gaps.items():
        count = len(test_paths)
        issues.append(_issue(
            code="W_CONFTEST_COVERAGE_GAP",
            severity="warning",
            task_id=task_id,
            message=f"task '{task_id}' source '{source_path}' has {count} related conftest(s) not covered by any verification",
            evidence={"source_path": source_path, "uncovered_tests": test_paths},
        ))

    for (task_id, source_path), test_paths in direct_gaps.items():
        code = "W_TEST_COVERAGE_GAP"
        count = len(test_paths)
        issues.append(_issue(
            code=code,
            severity="warning",
            task_id=task_id,
            message=f"task '{task_id}' source '{source_path}' has {count} related test(s) not covered by any verification",
            evidence={"source_path": source_path, "uncovered_tests": test_paths},
        ))
    issues.extend(_build_indirect_gap_issues(indirect_gaps))

    issues.extend(dynamic_hints)
    return issues


def _check_registration_invariants(
    plan: Plan,
    project_root: Path,
    workspace: WorkspaceIndex,
) -> List[ValidationIssue]:
    if not plan.registration_invariants:
        return []

    task_map: Dict[str, TaskSpec] = {t.id: t for t in plan.tasks}

    # Build set of all claimed paths per task (including transitive deps)
    def _all_claimed_paths(task_id: str) -> Set[str]:
        paths: Set[str] = set()
        if task_id in task_map:
            paths.update(task_map[task_id].claimed_paths)
        for dep_id in transitive_deps(task_id, task_map):
            if dep_id in task_map:
                paths.update(task_map[dep_id].claimed_paths)
        return paths

    # Collect every claimed path across all tasks (flat)
    all_claimed: Set[str] = set()
    for task in plan.tasks:
        all_claimed.update(task.claimed_paths)

    issues: List[ValidationIssue] = []

    for inv in plan.registration_invariants:
        registry = inv.registry_file

        # Check if ANY task (directly or via transitive deps) covers the registry file
        covered = False
        for task in plan.tasks:
            if registry in _all_claimed_paths(task.id):
                covered = True
                break
        if covered:
            continue

        # Registry file not claimed — check if any task claims a file in the same directory
        registry_dir = str(PurePosixPath(registry).parent)
        nearby_task_ids: list[str] = []
        for task in plan.tasks:
            for cp in task.claimed_paths:
                cp_dir = str(PurePosixPath(cp).parent)
                if cp_dir == registry_dir:
                    if task.id not in nearby_task_ids:
                        nearby_task_ids.append(task.id)
                    break

        if not nearby_task_ids:
            # No tasks touch that directory — plan doesn't affect this subsystem
            continue

        for task_id in nearby_task_ids:
            issues.append(_issue(
                code="W_REGISTRATION_INVARIANT_UNCOVERED",
                severity="warning",
                task_id=task_id,
                message=f"registration invariant '{inv.name}' registry file '{inv.registry_file}' is not claimed by any task",
                evidence={
                    "invariant": inv.name,
                    "registry": inv.registry_file,
                    "nearby_claims_by": nearby_task_ids,
                },
            ))

    return issues


def _check_unclaimed_tests_for_source(
    plan: Plan,
    project_root: Path,
    workspace: WorkspaceIndex,
) -> List[ValidationIssue]:
    tests_root = project_root / "tests"
    if not tests_root.is_dir():
        return []

    all_claimed = {path for task in plan.tasks for path in task.claimed_paths}
    commands = [
        task.verification.command
        for task in plan.tasks
        if task.verification and task.verification.command.strip()
    ]
    issues: List[ValidationIssue] = []

    for task in plan.tasks:
        for source_path in _claimed_source_paths(task.claimed_paths):
            module_names = _module_names_for_path(source_path)
            if not module_names:
                continue
            for test_path in _grep_test_candidates(tests_root, project_root, source_path, module_names):
                if test_path in all_claimed or any(test_path in command for command in commands):
                    continue
                if _classify_test_import(test_path, source_path, module_names, workspace) is None:
                    continue
                severity = "warning" if _is_direct_test_file(test_path, source_path) else "hint"
                issues.append(_issue(
                    code="W_UNCLAIMED_TEST_FOR_SOURCE",
                    severity=severity,
                    task_id=task.id,
                    message=f"task '{task.id}' source '{source_path}' has related test '{test_path}' claimed by no task",
                    evidence={"source_path": source_path, "test_path": test_path, "task_id": task.id},
                ))

    return issues


def _claimed_source_paths(claimed_paths: list[str]) -> list[str]:
    return [
        rel_path
        for rel_path in claimed_paths
        if rel_path.endswith(".py") and not rel_path.startswith("tests/")
    ]


def _is_direct_test_file(test_path: str, source_path: str) -> bool:
    source_stem = Path(source_path).stem
    test_stem = Path(test_path).stem
    return source_stem in test_stem


def _module_names_for_path(rel_path: str) -> list[str]:
    path = Path(rel_path)
    parts = list(path.parts)
    if not parts:
        return []
    if parts[0] == "src":
        parts = parts[1:]
    if path.name == "__init__.py":
        parts = parts[:-1]
    elif path.suffix == ".py":
        parts[-1] = path.stem
    if not parts:
        return []
    return [".".join(parts)]


def _grep_test_candidates(
    tests_root: Path,
    project_root: Path,
    source_path: str,
    module_names: list[str],
) -> list[str]:
    needles = set(module_names)
    needles.add(Path(source_path).stem)
    return [
        test_file.relative_to(project_root).as_posix()
        for test_file in sorted(tests_root.rglob("*.py"))
        if _file_contains_any(test_file, needles)
    ]


def _file_contains_any(path: Path, needles: set[str]) -> bool:
    cached = _load_issue_file_map_cached(path)
    source = cached.get("_raw")
    if source is None:
        return False
    return any(needle in source for needle in needles)


def _coverage_gap_issue(
    task_id: str,
    source_path: str,
    test_path: str,
    module_names: list[str],
    commands: list[str],
    workspace: WorkspaceIndex,
) -> Optional[ValidationIssue]:
    import_kind = _classify_test_import(test_path, source_path, module_names, workspace)
    if import_kind is None:
        return None
    if import_kind == "dynamic":
        return _issue(
            code="W_DYNAMIC_TEST_IMPORT_OPAQUE",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' source '{source_path}' is dynamically imported by '{test_path}'",
            evidence={"source_path": source_path, "test_path": test_path},
        )
    if any(test_path in command for command in commands):
        return None
    code = "W_CONFTEST_COVERAGE_GAP" if Path(test_path).name == "conftest.py" else "W_TEST_COVERAGE_GAP"
    return _issue(
        code=code,
        severity="warning",
        task_id=task_id,
        message=f"task '{task_id}' source '{source_path}' is imported by '{test_path}' but no verification command executes that test file",
        evidence={"source_path": source_path, "test_path": test_path},
    )


def _build_indirect_gap_issues(
    indirect_gaps: dict[tuple[str, str], list[str]],
) -> list[ValidationIssue]:
    grouped_by_task: dict[str, list[tuple[str, list[str]]]] = {}
    for (task_id, source_path), test_paths in indirect_gaps.items():
        grouped_by_task.setdefault(task_id, []).append((source_path, test_paths))

    issues: list[ValidationIssue] = []
    for task_id, entries in grouped_by_task.items():
        sorted_entries = sorted(entries, key=lambda item: item[0])
        if len(sorted_entries) < _INDIRECT_IMPORT_FOLD_THRESHOLD:
            issues.extend(
                _indirect_gap_issue(task_id, source_path, test_paths)
                for source_path, test_paths in sorted_entries
            )
            continue
        issues.append(_folded_indirect_gap_issue(task_id, sorted_entries))
    return issues


def _indirect_gap_issue(
    task_id: str,
    source_path: str,
    test_paths: list[str],
) -> ValidationIssue:
    count = len(test_paths)
    return _issue(
        code="W_INDIRECT_TEST_IMPORT",
        severity="hint",
        task_id=task_id,
        message=f"task '{task_id}' source '{source_path}' has {count} related test(s) not covered by any verification",
        evidence={"source_path": source_path, "uncovered_tests": test_paths},
    )


def _folded_indirect_gap_issue(
    task_id: str,
    entries: list[tuple[str, list[str]]],
) -> ValidationIssue:
    samples = [
        {"source_path": source_path, "uncovered_tests": test_paths}
        for source_path, test_paths in entries[:_INDIRECT_IMPORT_FOLD_SAMPLE_COUNT]
    ]
    return _issue(
        code="W_INDIRECT_TEST_IMPORT",
        severity="hint",
        task_id=task_id,
        message=(
            f"task '{task_id}' has {len(entries)} indirect test import hint(s) "
            f"not covered by any verification; showing first {len(samples)} sample(s)"
        ),
        evidence={"total_hints": len(entries), "samples": samples},
    )


def _classify_test_import(
    test_path: str,
    source_path: str,
    module_names: list[str],
    workspace: WorkspaceIndex,
) -> Optional[str]:
    module_ast = workspace.ast_parse(test_path)
    if module_ast is None:
        return None
    if _has_direct_test_import(module_ast, source_path, module_names):
        return "direct"
    if _has_dynamic_test_import(module_ast, module_names):
        return "dynamic"
    return None


def _has_direct_test_import(module_ast: ast.Module, source_path: str, module_names: list[str]) -> bool:
    parent_modules = {name.rsplit(".", 1)[0] for name in module_names if "." in name}
    source_symbol = Path(source_path).stem

    for node in ast.walk(module_ast):
        if isinstance(node, ast.Import):
            if any(alias.name in module_names for alias in node.names):
                return True
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or node.module is None:
            continue
        if node.module in module_names:
            return True
        if source_symbol == "__init__":
            continue
        if node.module in parent_modules and any(alias.name == source_symbol for alias in node.names):
            return True
    return False


def _has_dynamic_test_import(module_ast: ast.Module, module_names: list[str]) -> bool:
    for node in ast.walk(module_ast):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not _is_dynamic_import_call(node.func):
            continue
        module_name = _literal_string(node.args[0])
        if module_name and any(module_name == name for name in module_names):
            return True
    return False


def _is_dynamic_import_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in {"__import__", "import_module"}
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == "importlib" and func.attr == "import_module"
    return False


def _literal_string(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _check_verification_command(
    cmd: str,
    task_id: str,
    projected: set[str],
    workspace: WorkspaceIndex,
    claimed_paths: Iterable[str] = (),
    all_plan_claimed: Set[str] = frozenset(),
    *,
    upstream_projected: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    # RV-24: upstream_projected defaults to projected for backwards compat
    up_proj = upstream_projected if upstream_projected is not None else projected

    split_commands = _split_shell_command(cmd)
    if split_commands is not None:
        issues: List[ValidationIssue] = []
        for sub_command in split_commands:
            issues.extend(
                _check_verification_command(
                    sub_command,
                    task_id,
                    projected,
                    workspace,
                    claimed_paths,
                    all_plan_claimed,
                    upstream_projected=up_proj,
                )
            )
        return issues

    if _has_unsplittable_shell_operator(cmd):
        return [_issue(
            code="W_VERIFICATION_COMPLEX_SHELL_SKIPPED",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' verification contains shell operators and was skipped",
        )]

    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return [_issue(
            code="W_VERIFICATION_SHAPE_UNKNOWN",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' verification command could not be parsed",
        )]

    if not tokens:
        return []

    tokens = _unwrap_command(tokens)
    if not tokens:
        return [_issue(
            code="W_VERIFICATION_SHAPE_UNKNOWN",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' verification command empty after unwrap",
        )]

    base = _command_base(tokens[0])
    if base in _TRIVIAL_COMMANDS:
        return [_issue(
            code="W_VERIFICATION_TRIVIAL_COMMAND",
            severity="warning",
            task_id=task_id,
            message=f"task '{task_id}' verification is trivial command '{base}'",
        )]

    if _is_python_pycompile(tokens):
        return _check_pycompile(tokens, task_id, projected, workspace, up_proj=up_proj)
    if _is_python_c(tokens):
        return _check_python_c(tokens, task_id, projected, workspace, up_proj=up_proj)
    if _is_pytest(tokens):
        return _check_pytest(
            tokens, task_id, projected, workspace, claimed_paths, all_plan_claimed,
            up_proj=up_proj,
        )

    return [_issue(
        code="W_VERIFICATION_SHAPE_UNKNOWN",
        severity="hint",
        task_id=task_id,
        message=f"task '{task_id}' verification shape not recognized for static precheck",
    )]


def _unwrap_command(tokens: list[str]) -> list[str]:
    """Strip simple wrappers and launcher shells when the inner command is safe to resolve."""
    current = list(tokens)
    while current:
        stripped = _strip_command_wrappers(current)
        if stripped != current:
            current = stripped
            continue
        subshell_tokens = _strip_outer_subshell_tokens(current)
        if subshell_tokens is not None:
            current = subshell_tokens
            continue
        shell_tokens = _unwrap_simple_shell_launcher(current)
        if shell_tokens is not None and shell_tokens != current:
            current = shell_tokens
            continue
        return current
    return current


def _is_python_pycompile(tokens: list[str]) -> bool:
    return len(tokens) >= 4 and _is_python_executable(tokens[0]) and tokens[1:3] == ["-m", "py_compile"]


def _check_pycompile(
    tokens: list[str],
    task_id: str,
    projected: set[str],
    workspace: WorkspaceIndex,
    *,
    up_proj: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    target = tokens[3]
    issues = [_issue(
        code="W_VERIFICATION_REDUNDANT_PYCOMPILE",
        severity="warning",
        task_id=task_id,
        message=f"task '{task_id}' verification uses redundant py_compile on '{target}'",
        evidence={"target": target},
    )]
    issues.extend(_check_path_target(
        target, task_id, projected, workspace,
        upstream_projected=up_proj,
    ))
    return issues


def _is_python_c(tokens: list[str]) -> bool:
    return len(tokens) >= 3 and _is_python_executable(tokens[0]) and tokens[1] == "-c"


def _check_python_c(
    tokens: list[str],
    task_id: str,
    projected: set[str],
    workspace: WorkspaceIndex,
    *,
    up_proj: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    snippet = tokens[2]
    try:
        module = ast.parse(snippet)
    except SyntaxError:
        return [_issue(
            code="W_VERIFICATION_PYTHON_SNIPPET_INVALID",
            severity="warning",
            task_id=task_id,
            message=f"task '{task_id}' python -c snippet is not valid Python",
        )]

    if len(module.body) == 1 and isinstance(module.body[0], ast.ImportFrom):
        return _check_import_from(module.body[0], task_id, projected, workspace, up_proj=up_proj)

    if any(isinstance(node, (ast.Call, ast.Attribute)) for node in ast.walk(module)):
        return [_issue(
            code="W_VERIFICATION_PYTHON_IMPORT_OPAQUE",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' python -c snippet is opaque to static import checks",
        )]

    return [_issue(
        code="W_VERIFICATION_SHAPE_UNKNOWN",
        severity="hint",
        task_id=task_id,
        message=f"task '{task_id}' python -c snippet shape not recognized",
    )]


def _check_import_from(
    node: ast.ImportFrom,
    task_id: str,
    projected: set[str],
    workspace: WorkspaceIndex,
    *,
    up_proj: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    if node.level != 0 or node.module is None:
        return [_issue(
            code="W_VERIFICATION_PYTHON_IMPORT_OPAQUE",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' python -c uses relative or opaque imports",
        )]

    module_name = node.module
    module_path = workspace.resolve_module(module_name)
    if module_path is None:
        # RV-24: check upstream first, then full projected
        upstream = up_proj if up_proj is not None else projected
        upstream_candidate = _projected_module_candidate(module_name, upstream, workspace)
        if upstream_candidate is not None:
            return [_missing_module_issue(module_name, task_id, upstream_candidate)]
        # Check if self-only projected covers it (self-verification paradox)
        full_candidate = _projected_module_candidate(module_name, projected, workspace)
        if full_candidate is not None:
            return [_missing_module_issue(
                module_name, task_id, full_candidate, self_only=True,
            )]
        if workspace.is_stdlib_or_thirdparty(module_name):
            return []
        return [_missing_module_issue(module_name, task_id, None)]

    rel_module_path = module_path.relative_to(workspace.project_root).as_posix()
    module_ast = workspace.ast_parse(rel_module_path)
    if module_ast is None:
        return [_issue(
            code="W_VERIFICATION_PYTHON_IMPORT_OPAQUE",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' import target '{module_name}' could not be parsed statically",
            evidence={"module": module_name},
        )]

    issues: List[ValidationIssue] = []
    for alias in node.names:
        if alias.name == "*":
            issues.append(_issue(
                code="W_VERIFICATION_PYTHON_IMPORT_OPAQUE",
                severity="hint",
                task_id=task_id,
                message=f"task '{task_id}' uses wildcard import from '{module_name}'",
                evidence={"module": module_name},
            ))
            continue
        if _module_defines_symbol(module_ast, alias.name):
            continue
        issues.append(_issue(
            code="W_VERIFICATION_IMPORT_SYMBOL_MISSING",
            severity="warning",
            task_id=task_id,
            message=f"task '{task_id}' imports missing symbol '{alias.name}' from '{module_name}'",
            evidence={"module": module_name, "symbol": alias.name},
        ))
    return issues


def _is_pytest(tokens: list[str]) -> bool:
    base = _command_base(tokens[0])
    if base in {"pytest", "py.test"}:
        return True
    return len(tokens) >= 3 and _is_python_executable(tokens[0]) and tokens[1:3] == ["-m", "pytest"]


def _check_pytest(
    tokens: list[str],
    task_id: str,
    projected: set[str],
    workspace: WorkspaceIndex,
    claimed_paths: Iterable[str] = (),
    all_plan_claimed: Set[str] = frozenset(),
    *,
    up_proj: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    target = _first_pytest_target(tokens)
    if target is None:
        return [_issue(
            code="W_VERIFICATION_SHAPE_UNKNOWN",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' pytest command has no static target",
        )]

    file_path, _, node_part = target.partition("::")
    if Path(workspace.project_root / file_path).is_dir():
        return []
    claims_target = any(
        file_path == cp or file_path.startswith(cp.rstrip("/") + "/") or cp == file_path
        for cp in claimed_paths
    )
    # RV-17: also check if ANY task in the plan claims this test file
    plan_claims_target = not claims_target and any(
        file_path == cp or file_path.startswith(cp.rstrip("/") + "/") or cp == file_path
        for cp in all_plan_claimed
    )
    path_issues = _check_path_target(
        file_path, task_id, projected, workspace,
        emit_missing_file_error=True,
        upstream_projected=up_proj,
    )
    if path_issues:
        return path_issues
    if not node_part:
        return _check_pytest_k(tokens, task_id, file_path, workspace, claims_target, plan_claims_target)

    module_ast = workspace.ast_parse(file_path)
    if module_ast is None:
        return [_issue(
            code="W_VERIFICATION_SHAPE_UNKNOWN",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' pytest target '{target}' could not be parsed statically",
        )]

    if _pytest_node_exists(module_ast, node_part):
        return []
    return [_issue(
        code="W_VERIFICATION_PYTEST_NODE_MISSING",
        severity="warning",
        task_id=task_id,
        message=f"task '{task_id}' pytest target node '{node_part}' was not found in '{file_path}'",
        evidence={"target": target},
    )]


def _check_pytest_k(
    tokens: list[str],
    task_id: str,
    file_path: str,
    workspace: WorkspaceIndex,
    claims_target: bool = False,
    plan_claims_target: bool = False,
) -> List[ValidationIssue]:
    pattern = _pytest_option_value(tokens, "-k")
    if not pattern:
        return []

    module_ast = workspace.ast_parse(file_path)
    if module_ast is None:
        return [_issue(
            code="W_VERIFICATION_SHAPE_UNKNOWN",
            severity="hint",
            task_id=task_id,
            message=f"task '{task_id}' pytest target '{file_path}' could not be parsed statically",
        )]

    test_names = _collect_pytest_k_names(module_ast)
    if any(pattern in name for name in test_names):
        return []

    # RV-12: downgrade if current task claims the test file
    # RV-17: also downgrade if any other task in the plan claims the test file
    should_downgrade = claims_target or plan_claims_target
    severity = "hint" if should_downgrade else "warning"
    message = f"task '{task_id}' pytest -k pattern '{pattern}' matched no test names in '{file_path}'"
    if claims_target:
        message += " (task claims this test file)"
    elif plan_claims_target:
        message += " (another task in the plan claims this test file)"
    return [_issue(
        code="W_VERIFICATION_PYTEST_K_NO_MATCH",
        severity=severity,
        task_id=task_id,
        message=message,
        evidence={"target": file_path, "pattern": pattern, "test_names": sorted(test_names)},
    )]


def _check_path_target(
    rel_path: str,
    task_id: str,
    projected: set[str],
    workspace: WorkspaceIndex,
    *,
    emit_missing_file_error: bool = False,
    upstream_projected: Optional[Set[str]] = None,
) -> List[ValidationIssue]:
    if workspace.path_exists(rel_path):
        return []

    # RV-24: distinguish upstream-projected from self-only-projected
    up_proj = upstream_projected if upstream_projected is not None else projected
    covered_by_upstream = workspace.is_covered_by_projected(rel_path, up_proj)
    covered_by_any = workspace.is_covered_by_projected(rel_path, projected)

    legacy_issue: ValidationIssue
    if covered_by_upstream:
        severity = "hint"
        message = f"task '{task_id}' references projected path '{rel_path}' that is not on disk yet"
    elif covered_by_any:
        # Self-verification paradox: task verifies using files it creates
        severity = "warning"
        message = (
            f"task '{task_id}' verification references '{rel_path}' "
            f"which only the task itself claims (self-verification)"
        )
    else:
        severity = "warning"
        message = f"task '{task_id}' references missing path '{rel_path}'"

    legacy_issue = _issue(
        code="W_VERIFICATION_TARGET_MISSING",
        severity=severity,
        task_id=task_id,
        message=message,
        evidence={"target": rel_path},
    )
    if (
        not emit_missing_file_error
        or covered_by_upstream
        or covered_by_any
        or _path_looks_related_to_projected(rel_path, projected)
    ):
        return [legacy_issue]
    if any(ch in rel_path for ch in "*?[]"):
        return [legacy_issue]
    return [
        legacy_issue,
        _issue(
            code="E_VERIFICATION_TARGET_MISSING_FILE",
            severity="error",
            task_id=task_id,
            message=f"task '{task_id}' references missing file '{rel_path}'",
            evidence={"missing_path": rel_path},
        ),
    ]


def _path_looks_related_to_projected(rel_path: str, projected: set[str]) -> bool:
    rel_name = PurePosixPath(rel_path).stem.removeprefix("test_")
    for candidate in projected:
        if PurePosixPath(candidate).stem.removeprefix("test_") == rel_name:
            return True
    return False


def _missing_module_issue(
    module_name: str,
    task_id: str,
    projected_candidate: Optional[str],
    *,
    self_only: bool = False,
) -> ValidationIssue:
    if self_only and projected_candidate:
        # RV-24: self-verification paradox for module imports
        return _issue(
            code="W_VERIFICATION_IMPORT_MODULE_MISSING",
            severity="warning",
            task_id=task_id,
            message=(
                f"task '{task_id}' imports module '{module_name}' "
                f"which only the task itself claims (self-verification)"
            ),
            evidence={"module": module_name, "projected_target": projected_candidate},
        )
    severity = "hint" if projected_candidate else "warning"
    message = f"task '{task_id}' imports missing module '{module_name}'"
    evidence: Dict[str, Any] = {"module": module_name}
    if projected_candidate:
        message = f"task '{task_id}' imports projected module '{module_name}' not yet present on disk"
        evidence["projected_target"] = projected_candidate
    return _issue(
        code="W_VERIFICATION_IMPORT_MODULE_MISSING",
        severity=severity,
        task_id=task_id,
        message=message,
        evidence=evidence,
    )


def _projected_module_candidate(
    module_name: str,
    projected: set[str],
    workspace: WorkspaceIndex,
) -> Optional[str]:
    for candidate in _module_candidate_paths(module_name, workspace):
        if workspace.is_covered_by_projected(candidate, projected):
            return candidate
    return None


def _module_candidate_paths(module_name: str, workspace: WorkspaceIndex) -> list[str]:
    parts = module_name.split(".")
    candidates: list[str] = []
    bases = [workspace.project_root / "src", workspace.project_root]
    for base in bases:
        module_path = base.joinpath(*parts)
        for candidate in (module_path.with_suffix(".py"), module_path / "__init__.py"):
            try:
                rel_path = candidate.relative_to(workspace.project_root).as_posix()
            except ValueError:
                continue
            if rel_path not in candidates:
                candidates.append(rel_path)
    return candidates


def _first_pytest_target(tokens: list[str]) -> Optional[str]:
    args = tokens[1:]
    if _is_python_executable(tokens[0]) and tokens[1:3] == ["-m", "pytest"]:
        args = tokens[3:]

    skip_value = False
    for token in args:
        if skip_value:
            skip_value = False
            continue
        if token in _PYTEST_FLAGS_WITH_VALUE:
            skip_value = True
            continue
        if token.startswith("-"):
            continue
        return token
    return None


def _pytest_option_value(tokens: list[str], option: str) -> Optional[str]:
    args = tokens[1:]
    if _is_python_executable(tokens[0]) and tokens[1:3] == ["-m", "pytest"]:
        args = tokens[3:]

    for index, token in enumerate(args):
        if token == option and index + 1 < len(args):
            return args[index + 1]
        if token.startswith(f"{option}="):
            return token.split("=", 1)[1]
    return None


def _collect_pytest_k_names(module: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            names.add(node.name)
            continue
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            names.add(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    names.add(child.name)
    return names


def _pytest_node_exists(module: ast.Module, node_part: str) -> bool:
    parts = node_part.split("::")
    if len(parts) == 1:
        return _module_has_named_node(module.body, parts[0])
    if len(parts) == 2:
        class_node = _find_class(module.body, parts[0])
        if class_node is None:
            return False
        return _module_has_named_node(class_node.body, parts[1])
    return False


def _module_has_named_node(nodes: Iterable[ast.stmt], name: str) -> bool:
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
    return False


def _find_class(nodes: Iterable[ast.stmt], name: str) -> Optional[ast.ClassDef]:
    for node in nodes:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _module_defines_symbol(module: ast.Module, symbol: str) -> bool:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if any(alias.asname == symbol or alias.name == symbol for alias in node.names):
                return True
        if isinstance(node, ast.Assign):
            if symbol in _assigned_names(node.targets):
                return True
        if isinstance(node, ast.AnnAssign) and symbol in _assigned_names([node.target]):
            return True
    return False


def _assigned_names(targets: Iterable[ast.expr]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        if isinstance(target, (ast.Tuple, ast.List)):
            names.update(_assigned_names(target.elts))
    return names


def _is_python_executable(token: str) -> bool:
    return _command_base(token).startswith("python")


def _command_base(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _issue(
    *,
    code: str,
    severity: str,
    task_id: str,
    message: str,
    evidence: Optional[dict] = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        task_ids=[task_id],
        evidence=evidence or {},
    )
