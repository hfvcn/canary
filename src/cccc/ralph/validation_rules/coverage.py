"""Coverage validation rules — verification strength, flow coverage, and completeness checks.

Extracted from validator.py as a pure refactor (RO-31).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from cccc.kernel.claimed_paths import normalize_write_set as _normalize_write_set, paths_overlap as _paths_overlap
from ..filesystem_validator import _shell_command_tokens, _unwrap_command
from ..graph_utils import transitive_deps
from ..models import (
    CheckSpec,
    Plan,
    TaskSpec,
    Verification,
    ValidationIssue,
)
from ..shallow_check_classifier import is_shallow_check
from ..task_typing import SECURITY_REVIEW_TOKENS


# Ordered levels for comparison
_LEVEL_ORDER: Dict[str, int] = {
    "compile": 0,
    "unit": 1,
    "api": 2,
    "integration": 3,
    "e2e": 4,
}

_BEHAVIORAL_CHECK_NAME_TOKENS = ("test", "pytest", "behavior", "assert")
_ACCEPTANCE_RISK_KEYWORDS = (
    "concurrency",
    "error handling",
    "persistence",
    "race condition",
    "lock",
    "atomic",
)
_SHELL_OPERATORS = {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>", "&"}

# Keywords in goal_behavior that imply runtime/integration behavior
_RUNTIME_KEYWORDS = {
    "trigger", "state advance", "state transition", "end-to-end", "verify gate",
    "initialize", "instantiate", "daemon", "startup", "cold start", "lazy-init",
    "event chain", "ipc", "reachable", "connected",
}

_COMMAND_SKIP_TOKENS = frozenset({
    "python", "python3", "pytest", "npm", "npx", "make", "node", "bash", "sh",
    "ruby", "cargo", "go", "java", "javac", "gcc", "g++", "clang", "rustc",
    "pip", "poetry", "uv", "ruff", "mypy", "flake8", "black", "isort",
    "tox", "nox", "yarn", "pnpm", "bun", "deno", "jest", "vitest", "mocha",
    "echo", "cat", "grep", "sed", "awk", "cd", "ls", "rm", "cp", "mv",
    "mkdir", "touch", "true", "false", "test", "set", "export", "env",
})

_PATH_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp",
    ".h", ".yml", ".yaml", ".json", ".toml", ".cfg", ".ini", ".sh", ".sql",
})
_TRACKER_SECTION_PREFIX = "#### "
_TRACKER_ISSUE_RE = re.compile(r"\b[A-Z]{1,4}-\d+[A-Za-z]?\b")
_ACCEPTANCE_HEADER_RE = re.compile(r"(验收标准|acceptance(?:\s+criteria)?)", re.IGNORECASE)
_ACCEPTANCE_INLINE_RE = re.compile(
    r"(?:验收标准|acceptance(?:\s+criteria)?)(?:\*\*|__)?\s*[：:]\s*(.*)",
    re.IGNORECASE,
)
_STATUS_CODE_RE = re.compile(
    r"(?:返回|return|status|HTTP|→)\s*(\d{3})",
    re.IGNORECASE,
)
_STATUS_CODE_LITERAL_RE = re.compile(r"\b[1-5]\d{2}\b")
_CLIENT_ERROR_STATUS_RE = re.compile(r"\b4\d{2}\b|\b4xx\b", re.IGNORECASE)
_ACCEPTANCE_FIELD_BREAK_RE = re.compile(r"^(?:[-*>]\s*)?\*\*[^*]+\*\*[:：]")
_ASCII_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_ACCEPTANCE_COVERAGE_THRESHOLD = 0.5
_ACCEPTANCE_STOPWORDS = frozenset({
    "acceptance", "criteria", "issue", "plan", "task", "tasks", "code",
    "must", "should", "when", "then", "with", "from", "into", "only",
    "without", "after", "before", "under", "this", "that", "have",
})
_INDEPENDENT_REVIEW_MODES = frozenset({"challenge", "agent"})
_INDEPENDENT_REVIEW_ROLES = frozenset({"integration", "verification"})
_INDEPENDENT_REVIEW_TEXT_TOKENS = (
    "reviewer",
    "审查",
    "审计",
    "auditor",
    "security-reviewer",
)
_TEST_BASENAME_PREFIX = "test_"
_TEST_BASENAME_SUFFIX = "_test.py"
_PYTHON_TEST_SUFFIX = ".py"
_OVERRIDE_SIGNAL_TOKENS = ("xfail", "importorskip", "pytest.skip", "--deselect")
_INTEGRATION_TASK_KEYWORDS = ("integration", "集成")
_REGISTRATION_CALL_PREFIXES = ("register_", "add_")
_REGISTRATION_CALL_NAMES = frozenset({"register", "add_hook", "append"})
_CALLABLE_USAGE_WRAPPER_NAMES = frozenset({"include_router"})
_FORBIDDEN_FLOW_ASSERTION_WINDOW = 5
_FORBIDDEN_FLOW_NEGATIVE_ASSERTION_TOKENS = (
    "forbidden",
    "denied",
    "deny",
    "reject",
    "rejected",
    "rejection",
    "error",
    "unauthorized",
)
_FORBIDDEN_FLOW_MALFORMED_INPUT_TOKENS = (
    "malformed-input",
    "malformed input",
    "malformed",
    "invalid",
    "bad request",
)
W_SECURITY_REVIEW_NOT_INDEPENDENT = "W_SECURITY_REVIEW_NOT_INDEPENDENT"
W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING = "W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING"
W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE = "W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE"
W_INTEGRATION_IMPORT_ONLY_NO_CALL = "W_INTEGRATION_IMPORT_ONLY_NO_CALL"
W_INTEGRATION_DORMANT_PATH = "W_INTEGRATION_DORMANT_PATH"
W_SILENT_FALLBACK = "W_SILENT_FALLBACK"
W_GUARD_AFTER_SIDE_EFFECT = "W_GUARD_AFTER_SIDE_EFFECT"
W_VERIFICATION_NO_MAIN_PATH_COMMAND = "W_VERIFICATION_NO_MAIN_PATH_COMMAND"
_MAIN_PATH_CLI_PROGRAMS = frozenset({"cccc", "ralph"})
_LOG_GREP_PROGRAMS = frozenset({"grep", "rg", "egrep", "fgrep", "zgrep"})
_OBSERVABLE_FALLBACK_SIGNAL_CHAINS = frozenset({
    "logger.warning",
    "logger.error",
    "logger.exception",
    "logger.critical",
    "logging.warning",
    "logging.error",
    "logging.exception",
    "logging.critical",
})
_OBSERVABLE_FALLBACK_SIGNAL_NAMES = frozenset({"append_event", "publish_event"})
SIDE_EFFECT_GUARDS: Dict[str, Set[str]] = {
    "emit_workflow_terminal": {
        "workflow_evaluation_empty_sections",
        "_check_section_substantive",
    },
    "on_workflow_completed": {
        "workflow_evaluation_empty_sections",
        "_check_section_substantive",
    },
}


# ---------------------------------------------------------------------------
# 4. Verification strength
# ---------------------------------------------------------------------------

def _check_verification_strength(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    # Collect all verifications that cover multiple tasks
    has_cross_task = False
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        if v.level in ("integration", "e2e") and len(v.covers.tasks) >= 2:
            has_cross_task = True
            break

    if not has_cross_task:
        issues.append(ValidationIssue(
            code="E_NO_CROSS_TASK_VERIFICATION",
            severity="error",
            message=f"plan has {len(plan.tasks)} tasks but no integration/e2e verification covers multiple tasks",
            task_ids=[t.id for t in plan.tasks],
        ))

    # Check for compile-only plans
    levels = set()
    for t in plan.tasks:
        if t.verification:
            levels.add(t.verification.level)

    if levels and levels <= {"compile"}:
        issues.append(ValidationIssue(
            code="W_WEAK_VERIFICATION_ONLY",
            severity="warning",
            message="all verifications are compile-level only — no behavioral testing",
        ))

    return issues


def _check_verification_no_checks(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        if v.command.strip() and not v.checks:
            issues.append(ValidationIssue(
                code="W_VERIFICATION_NO_CHECKS",
                severity="warning",
                message=(
                    f"task '{t.id}' has a verification command but no structured checks — "
                    "consider splitting into at least a compile check and a behavior test check"
                ),
                task_ids=[t.id],
            ))
    return issues


def _check_verification_non_gating(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        has_required = any(check.required for check in verification.checks)
        top_command_empty = not verification.command.strip()
        if not verification.checks and not top_command_empty:
            continue
        if verification.checks and has_required:
            continue
        issues.append(ValidationIssue(
            code="E_VERIFICATION_NON_GATING",
            severity="error",
            message=f"task '{task.id}' verification cannot gate completion at runtime",
            task_ids=[task.id],
            evidence={
                "checks_count": len(verification.checks),
                "has_required": has_required,
                "top_command_empty": top_command_empty,
            },
        ))
    return issues


def _check_verification_shallow_checks(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    critical_flow_ids = {flow.id for flow in plan.critical_flows}
    for task in plan.tasks:
        verification = task.verification
        if verification is None or not verification.checks:
            continue
        if any(_is_behavioral_check(check) for check in verification.checks):
            continue
        if not all(_is_shallow_check(check) for check in verification.checks):
            continue
        evidence: Dict[str, Any] = {"check_names": [check.name for check in verification.checks]}
        risk_keywords = _acceptance_risk_keywords(task.acceptance_criteria)
        if risk_keywords:
            evidence["acceptance_risk_keywords"] = risk_keywords
        covered_critical_flows = sorted(set(verification.covers.flows) & critical_flow_ids)
        if covered_critical_flows:
            evidence["critical_flows"] = covered_critical_flows
        code = (
            "E_VERIFICATION_SHALLOW_CRITICAL"
            if covered_critical_flows
            else "W_VERIFICATION_SHALLOW_CHECKS"
        )
        severity = "error" if covered_critical_flows else "warning"
        issues.append(ValidationIssue(
            code=code,
            severity=severity,
            message=(
                f"task '{task.id}' verification checks are all shallow "
                "(compile/import/help) — consider adding at least one behavioral test check"
            ),
            task_ids=[task.id],
            evidence=evidence,
        ))
    return issues


_SAFE_SHELL_SEPARATORS = frozenset({"&&", ";"})
_UNSAFE_SHELL_OPERATORS = frozenset({"||", "|", ">", ">>", "<", "<<", "&"})


def _split_shell_subcommands(command: str) -> List[List[str]]:
    tokens = _shell_command_tokens(command)
    if not tokens:
        stripped = command.strip()
        return [[stripped]] if stripped else []
    tokens = _unwrap_command(tokens)
    if tokens and tokens[0] == "sudo":
        tokens = tokens[1:]
    if not tokens or any(token in _UNSAFE_SHELL_OPERATORS for token in tokens):
        return [tokens] if tokens else []
    subcommands: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in _SAFE_SHELL_SEPARATORS:
            if current:
                subcommands.append(current)
                current = []
            continue
        current.append(token)
    if current:
        subcommands.append(current)
    return subcommands or [tokens]


def _command_program(subcommand: List[str]) -> str:
    tokens = list(subcommand)
    if not tokens:
        return ""
    if tokens[0] == "sudo":
        tokens = tokens[1:]
    tokens = _unwrap_command(tokens)
    if tokens and tokens[0] == "sudo":
        tokens = tokens[1:]
    if not tokens:
        return ""
    return os.path.basename(tokens[0]).lower()


def _is_main_path_command(command: str) -> bool:
    for subcommand in _split_shell_subcommands(command):
        program = _command_program(subcommand)
        if program in _MAIN_PATH_CLI_PROGRAMS:
            return True
        if program in _LOG_GREP_PROGRAMS and any(".log" in token for token in subcommand[1:]):
            return True
    return False


def _task_is_runtime_behavior(
    task: TaskSpec,
    plan: Plan,
) -> Optional[List[str]]:
    verification = task.verification
    if verification is None:
        return None
    covered = sorted(
        flow.id
        for flow in plan.critical_flows
        if _task_covers_flow(task, flow.id, list(flow.entrypoints))
    )
    if task.role == "integration" or verification.level == "e2e" or covered:
        return covered
    return None


def _check_verification_main_path_command(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        covered_critical = _task_is_runtime_behavior(task, plan)
        if covered_critical is None:
            continue
        if verification.checks:
            candidates = [check.command for check in verification.checks if check.required]
        else:
            candidates = [verification.command]
        candidates = [command for command in candidates if command and command.strip()]
        if not candidates:
            continue
        if any(_is_main_path_command(command) for command in candidates):
            continue
        issues.append(ValidationIssue(
            code=W_VERIFICATION_NO_MAIN_PATH_COMMAND,
            severity="warning",
            message=(
                f"task '{task.id}' is a runtime-behavior task but its verification has no "
                "main-path command (only pytest/shallow commands) — add a real CLI invocation "
                "(cccc/ralph) or a runtime-log assertion (grep ... .log)"
            ),
            task_ids=[task.id],
            evidence={
                "task_id": task.id,
                "role": task.role,
                "level": verification.level,
                "covered_critical_flows": covered_critical,
                "commands": candidates,
            },
        ))
    return issues


def _check_integration_task_shallow_verification(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        if task.role != "integration" or verification is None or not verification.checks:
            continue
        if any(_is_behavioral_check(check) for check in verification.checks):
            continue
        if not all(_is_integration_shallow_check(check) for check in verification.checks):
            continue
        issues.append(ValidationIssue(
            code="W_INTEGRATION_TASK_SHALLOW_VERIFICATION",
            severity="warning",
            message=f"task '{task.id}' integration verification is shallow and lacks a behavioral check",
            task_ids=[task.id],
        ))
    return issues


def _check_integration_claim_evidence(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        covered_tasks = [
            t for t in (verification.covers.tasks if verification is not None else [])
            if t != task.id
        ]
        has_role_claim = task.role == "integration"
        has_covers_claim = bool(covered_tasks)
        if not has_role_claim and not has_covers_claim:
            continue
        if has_role_claim and not covered_tasks:
            issues.append(_integration_claim_evidence_issue(
                task.id,
                claim_type="role",
                missing_evidence="role='integration' but verification.covers.tasks is empty",
            ))
        if has_covers_claim and not _verification_level_at_least(verification, "integration"):
            issues.append(_integration_claim_evidence_issue(
                task.id,
                claim_type="covers",
                missing_evidence=(
                    f"covers.tasks is declared but verification.level='{_verification_level_name(verification)}' "
                    "is below 'integration'"
                ),
            ))
        if has_role_claim and _claimed_paths_all_tests(task.claimed_paths):
            issues.append(_integration_claim_evidence_issue(
                task.id,
                claim_type="role",
                missing_evidence="role='integration' but claimed_paths contain only test files",
            ))
    return issues


def _check_integration_call_evidence(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if project_root is None:
        return issues

    root = Path(project_root)
    production_modules = _production_python_modules(plan.plan_scope, root)
    if not production_modules:
        return issues

    for task in plan.tasks:
        if not _is_integration_evidence_task(task):
            continue
        claimed_paths = _claimed_python_module_paths(task.claimed_paths)
        if not claimed_paths:
            continue
        claimed_modules = _claimed_module_names(claimed_paths)
        if not claimed_modules:
            continue
        claimed_trees = [
            production_modules[path]
            for path in claimed_paths
            if path in production_modules
        ]
        if any(_has_registration_call(tree) for tree in claimed_trees):
            continue
        if any(_has_same_file_wiring(tree) for tree in claimed_trees):
            continue
        import_evidence = _production_import_evidence_map(
            production_modules,
            claimed_modules,
        )
        if _has_imported_callable_usage(import_evidence, root):
            continue
        if import_evidence:
            issues.append(ValidationIssue(
                code=W_INTEGRATION_IMPORT_ONLY_NO_CALL,
                severity="warning",
                message=(
                    f"task '{task.id}' integration claim has production import evidence only; "
                    "no callable usage found"
                ),
                task_ids=[task.id],
                evidence={
                    "task_id": task.id,
                    "claimed_paths": claimed_paths,
                    "claimed_modules": sorted(claimed_modules),
                    "production_import_files": sorted(import_evidence),
                    "production_imported_names": {
                        path: sorted(names)
                        for path, names in sorted(import_evidence.items())
                    },
                    "plan_scope": list(plan.plan_scope),
                },
            ))
            continue
        issues.append(ValidationIssue(
            code="W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE",
            severity="warning",
            message=f"task '{task.id}' integration claim lacks production call evidence",
            task_ids=[task.id],
            evidence={
                "task_id": task.id,
                "claimed_paths": claimed_paths,
                "claimed_modules": sorted(claimed_modules),
                "production_files_scanned": sorted(production_modules),
                "plan_scope": list(plan.plan_scope),
            },
        ))
    return issues


def _check_active_path_reachability(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if project_root is None:
        return issues
    root = Path(project_root)
    production_modules = _production_python_modules(plan.plan_scope, root)
    if not production_modules:
        return issues
    entrypoint_paths = list(plan.critical_entrypoints or [])
    for flow in plan.critical_flows or []:
        entrypoint_paths.extend(flow.entrypoints or [])
    seed_rel_paths: Set[str] = set()
    for ep in entrypoint_paths:
        if not _entrypoint_in_scope(ep, plan.plan_scope):
            continue
        ep_path = _normalize_entrypoint(ep).strip().replace("\\", "/").strip("/")
        if ep_path in production_modules:
            seed_rel_paths.add(ep_path)
    if not seed_rel_paths:
        return issues
    name_to_rel: Dict[str, str] = {}
    for rel_path in production_modules:
        name_to_rel.setdefault(_module_name_from_rel_path(rel_path), rel_path)
    root_str = str(root)

    def _module_has_self_wiring(rel_path: str) -> bool:
        tree = production_modules[rel_path]
        return _has_registration_call(tree) or _has_same_file_wiring(tree)

    adjacency: Dict[str, Set[str]] = {rel_path: set() for rel_path in production_modules}
    for a_rel, a_tree in production_modules.items():
        for b_name, b_rel in name_to_rel.items():
            if b_rel == a_rel or not b_name:
                continue
            imported = _imported_names_for_claimed_modules(a_rel, a_tree, {b_name})
            if not imported:
                continue
            if _has_callable_usage_evidence(a_rel, imported, root_str) or _module_has_self_wiring(b_rel):
                adjacency[a_rel].add(b_rel)
    reachable: Set[str] = set()
    stack = list(seed_rel_paths)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for nxt in adjacency.get(cur, ()):
            if nxt not in reachable:
                stack.append(nxt)
    for task in plan.tasks:
        if not _is_integration_evidence_task(task):
            continue
        for claimed_rel in _claimed_python_module_paths(task.claimed_paths):
            if claimed_rel not in production_modules:
                continue
            claimed_name = _module_name_from_rel_path(claimed_rel)
            if not claimed_name:
                continue
            # "wired into production" requires some OTHER production module to actually
            # import the claimed module; self-registration alone (a top-level register_*
            # call in a module nobody imports) means the module is never loaded, so it is
            # NOT wired (that is the never-wired case, out of this rule's scope). Self-wiring
            # only contributes when paired with a real import (the import-time activation case).
            wired = any(
                (imported := _imported_names_for_claimed_modules(other_rel, other_tree, {claimed_name}))
                and (
                    _has_callable_usage_evidence(other_rel, imported, root_str)
                    or _module_has_self_wiring(claimed_rel)
                )
                for other_rel, other_tree in production_modules.items()
                if other_rel != claimed_rel
            )
            if not wired or claimed_rel in reachable:
                continue
            issues.append(ValidationIssue(
                code=W_INTEGRATION_DORMANT_PATH,
                severity="warning",
                message=(
                    f"task '{task.id}' integration claim '{claimed_rel}' is wired into production "
                    "but unreachable from any declared entrypoint (dormant path)"
                ),
                task_ids=[task.id],
                evidence={
                    "task_id": task.id,
                    "claimed_module": claimed_rel,
                    "claimed_module_name": claimed_name,
                    "declared_entrypoints": sorted(seed_rel_paths),
                    "reachable_modules": sorted(reachable),
                },
            ))
    return issues


def _check_observable_fallback(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if project_root is None:
        return issues
    root = Path(project_root)
    production_modules = _production_python_modules(
        plan.plan_scope,
        root,
        extra_paths=_claimed_production_python_paths(plan.tasks),
    )
    if not production_modules:
        return issues
    for rel_path, module in production_modules.items():
        task_ids = _observable_fallback_task_ids(plan, rel_path)
        for func_name, handler in _observable_fallback_handlers(module):
            if not _is_silent_fallback_handler(handler):
                continue
            if _handler_has_observable_signal(handler):
                continue
            issues.append(ValidationIssue(
                code=W_SILENT_FALLBACK,
                severity="warning",
                message=(
                    f"except handler in '{rel_path}' function '{func_name}' "
                    "swallows an exception without an observable signal"
                ),
                task_ids=task_ids,
                evidence={"file": rel_path, "function": func_name, "lineno": handler.lineno},
            ))
    return issues


def _check_guard_ordering(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if project_root is None:
        return issues
    root = Path(project_root)
    production_modules = _production_python_modules(
        plan.plan_scope,
        root,
        extra_paths=_claimed_production_python_paths(plan.tasks),
    )
    if not production_modules:
        return issues
    for rel_path, module in production_modules.items():
        task_ids = _observable_fallback_task_ids(plan, rel_path)
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = _function_body_calls(node)
            for side_effect_name, guard_names in SIDE_EFFECT_GUARDS.items():
                guard_call = _first_guard_call(calls, guard_names)
                if guard_call is None:
                    continue
                for call_name, lineno in calls:
                    if call_name != side_effect_name or guard_call[1] <= lineno:
                        continue
                    issues.append(ValidationIssue(
                        code=W_GUARD_AFTER_SIDE_EFFECT,
                        severity="warning",
                        message=(
                            f"function '{node.name}' in '{rel_path}' calls "
                            f"'{side_effect_name}' before required guard '{guard_call[0]}'"
                        ),
                        task_ids=task_ids,
                        evidence={
                            "file": rel_path,
                            "function": node.name,
                            "side_effect_call": side_effect_name,
                            "side_effect_lineno": lineno,
                            "guard_call": guard_call[0],
                            "guard_lineno": guard_call[1],
                        },
                    ))
    return issues


def _observable_fallback_task_ids(plan: Plan, rel_path: str) -> List[str]:
    for task in plan.tasks:
        claimed_paths = _normalize_write_set(task.claimed_paths) if task.claimed_paths else []
        if any(_paths_overlap(rel_path, claimed_path) for claimed_path in claimed_paths):
            return [task.id]
    return []


def _observable_fallback_handlers(module: ast.Module) -> List[Tuple[str, ast.ExceptHandler]]:
    handlers: List[Tuple[str, ast.ExceptHandler]] = []
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for handler in _function_except_handlers(node.body):
            handlers.append((node.name, handler))
    return handlers


def _function_except_handlers(body: List[ast.stmt]) -> List[ast.ExceptHandler]:
    handlers: List[ast.ExceptHandler] = []
    for node in _walk_except_handler_body(body):
        if isinstance(node, ast.ExceptHandler):
            handlers.append(node)
    return handlers


def _is_silent_fallback_handler(handler: ast.ExceptHandler) -> bool:
    nodes = list(_walk_except_handler_body(handler.body))
    if any(isinstance(node, ast.Raise) for node in nodes):
        return False
    if _handler_is_noop_body(handler.body):
        return True
    return any(isinstance(node, (ast.Return, ast.Continue, ast.Break)) for node in nodes)


def _handler_is_noop_body(body: List[ast.stmt]) -> bool:
    return bool(body) and all(_is_noop_handler_stmt(stmt) for stmt in body)


def _is_noop_handler_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Constant):
        return False
    return isinstance(stmt.value.value, str) or stmt.value.value is Ellipsis


def _handler_has_observable_signal(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        if _expr_name_chain(node.func) in _OBSERVABLE_FALLBACK_SIGNAL_CHAINS:
            return True
        if _call_name(node.func) in _OBSERVABLE_FALLBACK_SIGNAL_NAMES:
            return True
    return False


def _function_body_calls(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> List[Tuple[str, int]]:
    calls: List[Tuple[str, int]] = []
    for child in _walk_function_body(node.body):
        if isinstance(child, ast.Call) and _call_name(child.func):
            calls.append((_call_name(child.func), child.lineno))
    return calls


def _first_guard_call(
    calls: List[Tuple[str, int]],
    guard_names: Set[str],
) -> Tuple[str, int] | None:
    guard_calls = [(name, lineno) for name, lineno in calls if name in guard_names]
    if not guard_calls:
        return None
    return min(guard_calls, key=lambda item: (item[1], item[0]))


def _walk_function_body(body: List[ast.stmt]) -> Iterator[ast.AST]:
    stack: List[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _walk_except_handler_body(body: List[ast.stmt]) -> Iterator[ast.AST]:
    stack: List[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _integration_claim_evidence_issue(
    task_id: str,
    *,
    claim_type: str,
    missing_evidence: str,
) -> ValidationIssue:
    return ValidationIssue(
        code="W_INTEGRATION_CLAIM_EVIDENCE_MISSING",
        severity="warning",
        message=f"task '{task_id}' integration claim lacks supporting evidence",
        task_ids=[task_id],
        evidence={
            "task_id": task_id,
            "claim_type": claim_type,
            "missing_evidence": missing_evidence,
        },
    )


def _verification_level_at_least(
    verification: Verification | None,
    required_level: str,
) -> bool:
    if verification is None:
        return False
    return _LEVEL_ORDER.get(verification.level, -1) >= _LEVEL_ORDER.get(required_level, -1)


def _verification_level_name(verification: Verification | None) -> str:
    if verification is None:
        return ""
    return verification.level


def _claimed_paths_all_tests(claimed_paths: List[str]) -> bool:
    normalized_paths = [
        path.strip().replace("\\", "/").strip("/")
        for path in claimed_paths
        if path.strip()
    ]
    return bool(normalized_paths) and all(_is_claimed_test_path(path) for path in normalized_paths)


def _is_integration_evidence_task(task: TaskSpec) -> bool:
    if task.role == "integration":
        return True
    text = f"{task.title} {task.goal_behavior}".casefold()
    return any(keyword in text for keyword in _INTEGRATION_TASK_KEYWORDS)


def _claimed_python_module_paths(claimed_paths: List[str]) -> List[str]:
    paths: List[str] = []
    seen: Set[str] = set()
    for claimed_path in claimed_paths:
        normalized = claimed_path.strip().replace("\\", "/").strip("/")
        if not normalized or not normalized.endswith(".py") or normalized in seen:
            continue
        paths.append(normalized)
        seen.add(normalized)
    return paths


def _claimed_production_python_paths(tasks: List[TaskSpec]) -> List[str]:
    production_paths: List[str] = []
    seen_paths: Set[str] = set()
    for task in tasks:
        for rel_path in _claimed_python_module_paths(task.claimed_paths):
            if not _is_production_python_path(rel_path) or rel_path in seen_paths:
                continue
            production_paths.append(rel_path)
            seen_paths.add(rel_path)
    return production_paths


def _claimed_module_names(claimed_paths: List[str]) -> Set[str]:
    module_names: Set[str] = set()
    for claimed_path in claimed_paths:
        dotted = _module_name_from_rel_path(claimed_path)
        if dotted:
            module_names.add(dotted)
    return module_names


def _production_python_modules(
    plan_scope: List[str],
    project_root: Path,
    *,
    extra_paths: List[str] | None = None,
) -> Dict[str, ast.Module]:
    modules: Dict[str, ast.Module] = {}
    for rel_path in _production_python_files(
        plan_scope,
        project_root,
        extra_paths=extra_paths,
    ):
        full_path = project_root / rel_path
        try:
            tree = ast.parse(full_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        modules[rel_path] = tree
    return modules


def _production_python_files(
    plan_scope: List[str],
    project_root: Path,
    *,
    extra_paths: List[str] | None = None,
) -> List[str]:
    files: List[str] = []
    seen: Set[str] = set()
    for scope in plan_scope:
        normalized = scope.strip().replace("\\", "/").strip("/")
        if not normalized:
            continue
        scope_path = (project_root / normalized).resolve()
        if not _is_within_root(scope_path, project_root):
            continue
        candidates = [scope_path] if scope_path.is_file() else list(scope_path.rglob("*.py"))
        for candidate in candidates:
            _append_production_python_file(files, seen, candidate, project_root)
    for rel_path in extra_paths or []:
        if not _is_production_python_path(rel_path):
            continue
        _append_production_python_file(files, seen, project_root / rel_path, project_root)
    return files


def _append_production_python_file(
    files: List[str],
    seen: Set[str],
    candidate: Path,
    project_root: Path,
) -> None:
    if not candidate.is_file() or not _is_within_root(candidate, project_root):
        return
    rel_path = candidate.resolve().relative_to(project_root.resolve()).as_posix()
    if _is_claimed_test_path(rel_path) or rel_path in seen:
        return
    files.append(rel_path)
    seen.add(rel_path)


def _is_production_python_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").strip("/")
    return normalized.startswith("src/") and normalized.endswith(".py") and not _is_claimed_test_path(normalized)


def _is_within_root(path: Path, project_root: Path) -> bool:
    try:
        path.relative_to(project_root.resolve())
    except ValueError:
        return False
    return True


def _has_production_import_evidence(
    production_modules: Dict[str, ast.Module],
    claimed_modules: Set[str],
) -> bool:
    return bool(_production_import_evidence_map(production_modules, claimed_modules))


def _production_import_evidence_map(
    production_modules: Dict[str, ast.Module],
    claimed_modules: Set[str],
) -> Dict[str, List[str]]:
    return {
        rel_path: imported_names
        for rel_path, tree in production_modules.items()
        if (imported_names := _imported_names_for_claimed_modules(rel_path, tree, claimed_modules))
    }


def _has_imported_callable_usage(
    import_evidence: Dict[str, List[str]],
    project_root: Path,
) -> bool:
    project_root_str = str(project_root)
    return any(
        _has_callable_usage_evidence(source_path, imported_names, project_root_str)
        for source_path, imported_names in import_evidence.items()
    )


def _imported_names_for_claimed_modules(
    rel_path: str,
    module: ast.Module,
    claimed_modules: Set[str],
) -> List[str]:
    current_module = _module_name_from_rel_path(rel_path)
    imported_names: List[str] = []
    seen: Set[str] = set()
    for node in ast.walk(module):
        for imported_name in _claimed_import_names(node, claimed_modules, current_module):
            if imported_name in seen or imported_name == "*":
                continue
            imported_names.append(imported_name)
            seen.add(imported_name)
    return imported_names


def _claimed_import_names(
    node: ast.AST,
    claimed_modules: Set[str],
    current_module: str,
) -> List[str]:
    if isinstance(node, ast.Import):
        return [
            alias.asname or alias.name
            for alias in node.names
            if alias.name in claimed_modules
        ]
    if not isinstance(node, ast.ImportFrom):
        return []
    module_name = _resolved_import_from_module_name(node, current_module)
    if module_name and module_name in claimed_modules:
        return [alias.asname or alias.name for alias in node.names]
    imported_names: List[str] = []
    for alias in node.names:
        candidate = f"{module_name}.{alias.name}" if module_name else alias.name
        if candidate in claimed_modules:
            imported_names.append(alias.asname or alias.name)
    return imported_names


def _resolved_import_from_module_name(node: ast.ImportFrom, current_module: str) -> str:
    module_name = node.module or ""
    if node.level > 0:
        package_parts = current_module.split(".")[:-1] if current_module else []
        keep = len(package_parts) - (node.level - 1)
        package_parts = package_parts[:max(keep, 0)]
        prefix = ".".join(part for part in package_parts if part)
        module_name = ".".join(part for part in (prefix, module_name) if part)
    return module_name


def _module_name_from_rel_path(rel_path: str) -> str:
    parts = Path(rel_path).with_suffix("").parts
    if not parts:
        return ""
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(part for part in parts if part)


def _has_registration_call(module: ast.Module) -> bool:
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and _is_registration_call(node.func):
            return True
    return False


def _is_registration_call(func: ast.expr) -> bool:
    name = _call_name(func)
    return bool(name) and (
        name in _REGISTRATION_CALL_NAMES
        or any(name.startswith(prefix) for prefix in _REGISTRATION_CALL_PREFIXES)
    )


def _has_same_file_wiring(module: ast.Module) -> bool:
    defined_names = _top_level_defined_names(module)
    if not defined_names:
        return False
    return any(
        _call_references_defined_names(call, defined_names)
        for call in _top_level_calls(module)
    )


def _top_level_defined_names(module: ast.Module) -> Set[str]:
    names: Set[str] = set()
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_assignment_target_names(target))
        if isinstance(node, ast.AnnAssign):
            names.update(_assignment_target_names(node.target))
    return names


def _assignment_target_names(target: ast.expr) -> Set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: Set[str] = set()
        for element in target.elts:
            names.update(_assignment_target_names(element))
        return names
    return set()


def _top_level_calls(module: ast.Module) -> List[ast.Call]:
    calls: List[ast.Call] = []
    for node in module.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)) else None
        if isinstance(value, ast.Call):
            calls.append(value)
    return calls


def _call_references_defined_names(call: ast.Call, defined_names: Set[str]) -> bool:
    for node in ast.walk(call):
        if isinstance(node, ast.Name) and node.id in defined_names:
            return True
    return False


def _has_callable_usage_evidence(
    source_path: str,
    imported_names: list[str],
    project_root: str,
) -> bool:
    if not source_path or not imported_names:
        return False
    source_file = Path(project_root) / source_path
    try:
        module = ast.parse(source_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    return any(
        _callable_usage_matches(call, imported_names)
        for call in (node for node in ast.walk(module) if isinstance(node, ast.Call))
    )


def _callable_usage_matches(call: ast.Call, imported_names: list[str]) -> bool:
    if _matches_imported_callable(call.func, imported_names):
        return True
    if not _is_callable_usage_wrapper(call.func):
        return False
    values = list(call.args) + [keyword.value for keyword in call.keywords]
    return any(_matches_imported_callable(value, imported_names) for value in values)


def _matches_imported_callable(expr: ast.expr, imported_names: list[str]) -> bool:
    chain = _expr_name_chain(expr)
    if not chain:
        return False
    return any(
        chain == imported_name or chain.startswith(f"{imported_name}.")
        for imported_name in imported_names
    )


def _expr_name_chain(expr: ast.expr) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _expr_name_chain(expr.value)
        return f"{base}.{expr.attr}" if base else ""
    return ""


def _is_callable_usage_wrapper(func: ast.expr) -> bool:
    return _is_registration_call(func) or _call_name(func) in _CALLABLE_USAGE_WRAPPER_NAMES


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _check_dead_verification_command(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        verification = task.verification
        if verification is None or not verification.checks:
            continue
        command = verification.command.strip()
        if not command or not any(operator in command for operator in _SHELL_OPERATORS):
            continue
        issues.append(ValidationIssue(
            code="H_VERIFICATION_COMMAND_DEAD",
            severity="hint",
            message=f"task '{task.id}' verification.command is ignored in favor of structured checks",
            task_ids=[task.id],
            evidence={"command": command},
        ))
    return issues


def _check_covers_not_exercised(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        commands = [verification.command] + [check.command for check in verification.checks]
        covered_paths, auto_expanded = _coverage_paths(verification, task_map)
        if not covered_paths or _commands_reference_paths(commands, covered_paths):
            continue
        for covered_id in verification.covers.tasks:
            if covered_id == task.id or covered_id not in task_map:
                continue
            issues.append(ValidationIssue(
                code="W_COVERS_NOT_EXERCISED",
                severity="hint" if auto_expanded else "warning",
                message=f"task '{task.id}' covers '{covered_id}' but its verification does not reference the covered paths",
                task_ids=[task.id, covered_id],
                evidence={
                    "covered_task_id": covered_id,
                    "covered_paths": covered_paths,
                    "auto_expanded_from_covers_tasks": auto_expanded,
                },
            ))
    return issues


def _coverage_paths(
    verification: Verification,
    task_map: Dict[str, TaskSpec],
) -> tuple[List[str], bool]:
    if verification.covers.paths:
        return _dedupe_paths(verification.covers.paths), False
    if not verification.covers.tasks:
        return [], False
    claimed_paths = [
        path
        for task_id in verification.covers.tasks
        for path in _claimed_paths_for(task_id, task_map)
    ]
    return _dedupe_paths(claimed_paths), True


def _claimed_paths_for(task_id: str, task_map: Dict[str, TaskSpec]) -> List[str]:
    task = task_map.get(task_id)
    return list(task.claimed_paths) if task is not None else []


def _dedupe_paths(paths: List[str]) -> List[str]:
    deduped: List[str] = []
    for path in paths:
        if path not in deduped:
            deduped.append(path)
    return deduped


def _check_failure_path(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    _TRIGGER_KEYWORDS = {"assignment", "actor", "worker", "agent", "external", "async"}
    _HANDLING_KEYWORDS = {"failure", "error", "fallback", "rollback", "blocked", "escalat"}
    for t in plan.tasks:
        goal = (t.goal_behavior or "").lower()
        # Only check tasks that involve assignment/actor/worker concepts, or role=integration
        if t.role != "integration" and not any(kw in goal for kw in _TRIGGER_KEYWORDS):
            continue
        # If failure_path field is set, skip
        if (t.failure_path or "").strip():
            continue
        # Check goal_behavior and acceptance_criteria for failure handling keywords
        text = goal + " " + (t.acceptance_criteria or "").lower()
        if any(kw in text for kw in _HANDLING_KEYWORDS):
            continue
        issues.append(ValidationIssue(
            code="W_NO_FAILURE_PATH",
            severity="warning",
            message=(
                f"task '{t.id}' involves assignment/actor operations but has no "
                "failure handling description or failure_path field"
            ),
            task_ids=[t.id],
        ))
    return issues


def _check_duplicate_verification_commands(plan: Plan) -> List[ValidationIssue]:
    command_to_tasks: Dict[str, List[TaskSpec]] = {}
    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue
        command = verification.command.strip()
        if not command:
            continue
        command_to_tasks.setdefault(command, []).append(task)

    issues: List[ValidationIssue] = []
    for command, tasks in command_to_tasks.items():
        if len(tasks) < 2 or _has_self_covering_leaf(tasks):
            continue
        task_ids = [task.id for task in tasks]
        issues.append(ValidationIssue(
            code="W_VERIFICATION_DUPLICATE_COMMAND",
            severity="hint",
            message=f"tasks {task_ids} share the same verification command",
            task_ids=task_ids,
            evidence={"command": command},
        ))
    return issues


def _check_verification_behavior_match(plan: Plan) -> List[ValidationIssue]:
    """Warn when goal implies runtime behavior but verification is static grep/compile."""
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        if v.level in ("integration", "e2e"):
            continue  # already strong enough level

        goal_lower = (t.goal_behavior + " " + t.acceptance_criteria).lower()
        has_runtime_keyword = any(kw in goal_lower for kw in _RUNTIME_KEYWORDS)

        if has_runtime_keyword:
            severity = "hint" if _covered_by_downstream_integration_task(t.id, task_map) else "warning"
            issues.append(ValidationIssue(
                code="W_VERIFICATION_BEHAVIOR_MISMATCH",
                severity=severity,
                message=f"task '{t.id}' goal implies runtime behavior but "
                        f"verification is only {v.level}-level",
                task_ids=[t.id],
                evidence={"verification_level": v.level},
            ))

    return issues


def _check_verification_cross_scope(plan: Plan) -> List[ValidationIssue]:
    """Warn when a task's verification command references paths owned by another task."""
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    # Build normalised claimed_paths per task
    task_claimed: Dict[str, List[str]] = {}
    for t in plan.tasks:
        task_claimed[t.id] = _normalize_write_set(t.claimed_paths) if t.claimed_paths else []

    for task in plan.tasks:
        v = task.verification
        if v is None:
            continue
        own_paths = task_claimed.get(task.id, [])

        # Check individual checks
        for check in v.checks:
            extracted = _extract_paths_from_command(check.command)
            for ref_path in extracted:
                # Skip if it falls within the task's own claimed_paths
                if any(_paths_overlap(ref_path, op) for op in own_paths):
                    continue
                # Check against other tasks' claimed_paths
                for other_id, other_paths in task_claimed.items():
                    if other_id == task.id:
                        continue
                    if any(_paths_overlap(ref_path, op) for op in other_paths):
                        issues.append(ValidationIssue(
                            code="W_VERIFICATION_CROSS_SCOPE",
                            severity="warning",
                            message=(
                                f"task '{task.id}' verification check '{check.name}' "
                                f"references path '{ref_path}' which belongs to task '{other_id}'"
                            ),
                            task_ids=[task.id],
                            evidence={
                                "check_name": check.name,
                                "referenced_path": ref_path,
                                "owning_task": other_id,
                            },
                        ))
                        break  # one warning per ref_path is enough

        # Also check the top-level verification command
        if v.command.strip():
            extracted = _extract_paths_from_command(v.command)
            for ref_path in extracted:
                if any(_paths_overlap(ref_path, op) for op in own_paths):
                    continue
                for other_id, other_paths in task_claimed.items():
                    if other_id == task.id:
                        continue
                    if any(_paths_overlap(ref_path, op) for op in other_paths):
                        issues.append(ValidationIssue(
                            code="W_VERIFICATION_CROSS_SCOPE",
                            severity="warning",
                            message=(
                                f"task '{task.id}' verification command references path "
                                f"'{ref_path}' which belongs to task '{other_id}'"
                            ),
                            task_ids=[task.id],
                            evidence={
                                "check_name": "__top_level__",
                                "referenced_path": ref_path,
                                "owning_task": other_id,
                            },
                        ))
                        break

    return issues


def _check_covers_verifiability(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue

        # integration/e2e tasks run broad tests — don't require per-path mention
        if verification.level in ("integration", "e2e"):
            continue

        for covered_id in verification.covers.tasks:
            if covered_id == task.id:
                continue
            covered_task = task_map.get(covered_id)
            if covered_task is None or not covered_task.claimed_paths:
                continue
            if _command_mentions_any_path(verification.command, covered_task.claimed_paths):
                continue
            issues.append(ValidationIssue(
                code="W_COVERS_CLAIM_UNVERIFIABLE",
                severity="warning",
                message=f"task '{task.id}' covers '{covered_id}' but its verification command "
                        f"does not reference any claimed_paths of '{covered_id}'",
                task_ids=[task.id, covered_id],
                evidence={
                    "verification_command": verification.command,
                    "covered_claimed_paths": covered_task.claimed_paths,
                },
            ))

    return issues


# ---------------------------------------------------------------------------
# 6. Critical entrypoints & flows coverage
# ---------------------------------------------------------------------------

def _normalize_entrypoint(ep: str) -> str:
    if "::" in ep:
        return ep.split("::", 1)[0]
    return ep


def _entrypoint_parent_dir(path: str) -> str:
    normalized = path.strip().replace("\\", "/").strip("/")
    if not normalized or "/" not in normalized:
        return "/"
    return f"{normalized.rsplit('/', 1)[0]}/"


def _plan_touches_subsystem(all_claimed: Set[str], parent_dir: str) -> bool:
    prefix = parent_dir.rstrip("/")
    return any(
        claimed == "/" or claimed == prefix or claimed.startswith(parent_dir)
        for claimed in all_claimed
    )


def _entrypoint_in_scope(ep: str, plan_scope: List[str]) -> bool:
    """Check if an entrypoint falls within the declared plan_scope."""
    if not plan_scope:
        return True
    ep_norm = _normalize_entrypoint(ep).strip().replace("\\", "/")
    return any(ep_norm.startswith(scope.rstrip("/")) for scope in plan_scope)


def _check_critical_coverage(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    owned_paths: Set[str] = set()
    write_paths: Set[str] = set()
    for t in plan.tasks:
        for p in _normalize_write_set(t.claimed_paths):
            owned_paths.add(p)
            write_paths.add(p)
        if t.awareness_paths:
            for p in _normalize_write_set(t.awareness_paths):
                owned_paths.add(p)

    # Check critical entrypoints are owned
    for ep in plan.critical_entrypoints:
        if not _entrypoint_in_scope(ep, plan.plan_scope):
            continue
        ep_norm = _normalize_entrypoint(ep).strip().replace("\\", "/")
        parent_dir = _entrypoint_parent_dir(ep_norm)
        owned = any(_paths_overlap(ep_norm, cp) for cp in owned_paths)
        if not owned:
            touches_subsystem = _plan_touches_subsystem(write_paths, parent_dir)
            severity = "error" if touches_subsystem else "hint"
            if touches_subsystem:
                message = f"critical entrypoint '{ep}' is not claimed by any task"
            else:
                message = (
                    f"critical entrypoint '{ep}' is not claimed by any task; "
                    f"plan does not appear to touch subsystem '{parent_dir}'"
                )
            issues.append(ValidationIssue(
                code="E_CRITICAL_ENTRYPOINT_UNOWNED",
                severity=severity,
                message=message,
                evidence={"path": ep, "subsystem": parent_dir},
            ))

    # Check critical flows
    all_covered_flows: Set[str] = set()
    for t in plan.tasks:
        if t.verification:
            all_covered_flows.update(t.verification.covers.flows)

    for flow in plan.critical_flows:
        if plan.plan_scope and flow.entrypoints:
            if not any(_entrypoint_in_scope(ep, plan.plan_scope) for ep in flow.entrypoints):
                continue
        if flow.id not in all_covered_flows:
            failed_tasks = _failed_test_creator_ids(
                flow.test_created_by,
                plan.state.failed_task_ids,
            )
            if failed_tasks:
                issues.append(ValidationIssue(
                    code="E_FLOW_TEST_CREATOR_FAILED",
                    severity="error",
                    message=(
                        f"critical flow '{flow.id}' is uncovered because its "
                        "test creator task already failed"
                    ),
                    evidence={
                        "flow_id": flow.id,
                        "namespace": "critical",
                        "failed_task_ids": failed_tasks,
                    },
                ))
                continue
            if flow.id in plan.suppress_flows:
                issues.append(ValidationIssue(
                    code="E_CRITICAL_FLOW_UNCOVERED",
                    severity="hint",
                    message=f"[suppress_flows] critical flow '{flow.id}' is not covered by any task's verification",
                    evidence={"flow_id": flow.id},
                ))
                continue
            pending_tasks = _pending_test_creator_ids(
                flow.test_created_by,
                plan.state.completed_task_ids,
                plan.state.failed_task_ids,
            )
            if pending_tasks:
                issues.append(ValidationIssue(
                    code="E_CRITICAL_FLOW_UNCOVERED",
                    severity="hint",
                    message=f"[deferred] critical flow '{flow.id}' is not covered by any task's verification",
                    evidence={
                        "flow_id": flow.id,
                        "test_created_by": list(flow.test_created_by),
                        "pending_task_ids": pending_tasks,
                    },
                ))
                issues.append(ValidationIssue(
                    code="W_FLOW_COVERAGE_DEFERRED",
                    severity="warning",
                    message="[deferred] flow coverage not yet satisfied (creator pending)",
                    evidence={
                        "flow_id": flow.id,
                        "namespace": "critical",
                        "test_created_by": list(flow.test_created_by),
                        "pending_task_ids": pending_tasks,
                    },
                ))
                continue
            issues.append(ValidationIssue(
                code="E_CRITICAL_FLOW_UNCOVERED",
                severity="error",
                message=f"critical flow '{flow.id}' is not covered by any task's verification",
                evidence={"flow_id": flow.id},
            ))

        # Check entrypoints of this flow are owned
        for ep in flow.entrypoints:
            ep_norm = _normalize_entrypoint(ep).strip().replace("\\", "/")
            parent_dir = _entrypoint_parent_dir(ep_norm)
            owned = any(_paths_overlap(ep_norm, cp) for cp in owned_paths)
            if not owned:
                touches_subsystem = _plan_touches_subsystem(write_paths, parent_dir)
                severity = "error" if touches_subsystem else "hint"
                if touches_subsystem:
                    message = (
                        f"entrypoint '{ep}' of critical flow '{flow.id}' is not "
                        "claimed by any task"
                    )
                else:
                    message = (
                        f"entrypoint '{ep}' of critical flow '{flow.id}' is not "
                        f"claimed by any task; plan does not appear to touch subsystem "
                        f"'{parent_dir}'"
                    )
                issues.append(ValidationIssue(
                    code="E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED",
                    severity=severity,
                    message=message,
                    evidence={"flow_id": flow.id, "path": ep, "subsystem": parent_dir},
                ))

    return issues


def _task_owned_paths(task: TaskSpec) -> Set[str]:
    owned_paths: Set[str] = set()
    if task.claimed_paths:
        owned_paths.update(_normalize_write_set(task.claimed_paths))
    if task.awareness_paths:
        owned_paths.update(_normalize_write_set(task.awareness_paths))
    return owned_paths


def _resolve_symbol_entrypoint(entrypoint: str, owned_paths: Set[str]) -> Optional[str]:
    """Resolve a Python symbol path (no '/') to a file path from owned_paths."""
    if "/" in entrypoint:
        return None
    module_name = entrypoint.split(".")[0]
    for path in owned_paths:
        if path.endswith(f"/{module_name}.py") or path == f"{module_name}.py":
            return path
    return None


def _claimed_flow_entrypoints(task: TaskSpec, entrypoints: List[str]) -> List[str]:
    owned_paths = _task_owned_paths(task)
    if not owned_paths:
        return []
    result: List[str] = []
    for entrypoint in entrypoints:
        normalized_entrypoint = _normalize_entrypoint(entrypoint).strip().replace("\\", "/")
        if any(_paths_overlap(normalized_entrypoint, path) for path in owned_paths):
            result.append(entrypoint)
            continue
        resolved = _resolve_symbol_entrypoint(normalized_entrypoint, owned_paths)
        if resolved is not None:
            result.append(entrypoint)
    return result


def _task_covers_critical_flow(task: TaskSpec, critical_flows: List[Any]) -> List[str]:
    covered_flow_ids: List[str] = []
    for flow in critical_flows:
        if _claimed_flow_entrypoints(task, list(flow.entrypoints)):
            covered_flow_ids.append(flow.id)
    return covered_flow_ids


def _covering_tasks_for_flow(plan: Plan, flow: Any) -> List[TaskSpec]:
    covering_tasks: List[TaskSpec] = []
    seen_task_ids: Set[str] = set()
    flow_entrypoints = list(getattr(flow, "entrypoints", []) or [])
    for task in plan.tasks:
        if not _task_covers_flow(task, flow.id, flow_entrypoints):
            continue
        if task.id in seen_task_ids:
            continue
        covering_tasks.append(task)
        seen_task_ids.add(task.id)
    return covering_tasks


def _task_covers_flow(
    task: TaskSpec,
    flow_id: str,
    flow_entrypoints: List[str],
) -> bool:
    verification = task.verification
    if verification and flow_id in verification.covers.flows:
        return True
    return bool(_claimed_flow_entrypoints(task, flow_entrypoints))


def _check_flow_segment_ownership(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for flow in plan.critical_flows:
        entrypoints = [
            _normalize_entrypoint(ep).strip().replace("\\", "/")
            for ep in flow.entrypoints
        ]
        if not entrypoints:
            continue

        covering_tasks = [
            task
            for task in plan.tasks
            if task.verification and flow.id in task.verification.covers.flows
        ]
        covering_ids = {task.id for task in covering_tasks}
        integration_or_verification_covering = {
            task.id for task in covering_tasks
            if task.role in ("integration", "verification")
        }
        covered_by_flow_verifiers = {
            tid
            for ct in covering_tasks
            if ct.verification and ct.verification.covers
            for tid in ct.verification.covers.tasks
            if tid != ct.id
        }
        covered_by_any_verifier = {
            tid
            for t in plan.tasks
            if t.role in ("integration", "verification") and t.verification and t.verification.covers
            for tid in t.verification.covers.tasks
            if tid != t.id
        }
        covered_by_flow_verifiers |= covered_by_any_verifier

        for task in covering_tasks:
            if _claimed_flow_entrypoints(task, entrypoints):
                continue
            issues.append(ValidationIssue(
                code="W_FLOW_SEGMENT_UNOWNED",
                severity="warning",
                message=f"task '{task.id}' covers flow '{flow.id}' but doesn't claim any of its entrypoints",
                task_ids=[task.id],
                evidence={"flow_id": flow.id, "entrypoints": list(flow.entrypoints)},
            ))

        for task in plan.tasks:
            if task.id in covering_ids:
                continue
            for entrypoint in _claimed_flow_entrypoints(task, entrypoints):
                severity = "warning"
                if task.role == "leaf" and integration_or_verification_covering:
                    severity = "hint"
                if task.id in covered_by_flow_verifiers:
                    severity = "hint"
                issues.append(ValidationIssue(
                    code="W_FLOW_OWNER_NO_VERIFICATION",
                    severity=severity,
                    message=f"task '{task.id}' claims entrypoint '{entrypoint}' of flow '{flow.id}' but doesn't verify the flow",
                    task_ids=[task.id],
                    evidence={"flow_id": flow.id, "path": entrypoint},
                ))

    return issues


# ---------------------------------------------------------------------------
# 8. Critical flow verification level check
# ---------------------------------------------------------------------------

def _check_critical_flow_levels(plan: Plan) -> List[ValidationIssue]:
    """Check that critical flows are covered at their required verification level."""
    issues: List[ValidationIssue] = []

    # Map flow_id -> best verification level that covers it
    flow_best_level: Dict[str, int] = {}
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        level_num = _LEVEL_ORDER.get(v.level, 0)
        for flow_id in v.covers.flows:
            if flow_id not in flow_best_level or level_num > flow_best_level[flow_id]:
                flow_best_level[flow_id] = level_num

    for flow in plan.critical_flows:
        if flow.id not in flow_best_level:
            continue  # already caught by E_CRITICAL_FLOW_UNCOVERED
        required = _LEVEL_ORDER.get(flow.required_verification_level, 0)
        actual = flow_best_level[flow.id]
        if actual < required:
            actual_name = [k for k, v in _LEVEL_ORDER.items() if v == actual][0]
            issues.append(ValidationIssue(
                code="E_CRITICAL_FLOW_LEVEL_TOO_WEAK",
                severity="error",
                message=f"critical flow '{flow.id}' requires {flow.required_verification_level} "
                        f"but best coverage is {actual_name}",
                evidence={
                    "flow_id": flow.id,
                    "required": flow.required_verification_level,
                    "actual": actual_name,
                },
            ))

    return issues


def _check_critical_flow_worker_only_verification(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if task.verification_mode in ("agent", "challenge"):
            continue
        covered_flow_ids = _task_covers_critical_flow(task, plan.critical_flows)
        if not covered_flow_ids:
            continue
        issues.append(ValidationIssue(
            code="W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION",
            severity="warning",
            message=(
                f"task '{task.id}' claims critical flow entrypoints but uses "
                f"verification_mode='{task.verification_mode}' instead of agent/challenge"
            ),
            task_ids=[task.id],
            evidence={
                "task_id": task.id,
                "verification_mode": task.verification_mode,
                "critical_flows": covered_flow_ids,
            },
        ))
    return issues


def _check_critical_flow_independent_review(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        covering_tasks = _covering_tasks_for_flow(plan, flow)
        if not covering_tasks or any(_task_has_independent_review_semantics(task) for task in covering_tasks):
            continue
        issues.append(ValidationIssue(
            code="W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW",
            severity="warning",
            message=f"critical flow '{flow.id}' has coverage but no independent review semantics",
            task_ids=[task.id for task in covering_tasks],
            evidence={"flow_id": flow.id},
        ))
    return issues


def _task_has_independent_review_semantics(task: TaskSpec) -> bool:
    if task.verification_mode in _INDEPENDENT_REVIEW_MODES:
        return True
    if task.role in _INDEPENDENT_REVIEW_ROLES:
        return True
    review_text = f"{task.title} {task.goal_behavior}".casefold()
    return any(token.casefold() in review_text for token in _INDEPENDENT_REVIEW_TEXT_TOKENS)


def _check_security_reviewer_assignment(plan, tasks, **kwargs) -> list[str]:
    candidate_tasks = list(tasks or getattr(plan, "tasks", []) or [])
    review_tasks = [task for task in candidate_tasks if _is_security_review_task(task)]
    if not review_tasks:
        return []
    execution_tasks = [
        task for task in candidate_tasks
        if not _is_security_review_task(task) and _task_claims_production_code(task)
    ]
    if not execution_tasks:
        return []
    if all(_task_is_independent_from_execution(review_task, execution_tasks) for review_task in review_tasks):
        return []
    return [W_SECURITY_REVIEW_NOT_INDEPENDENT]


def _check_security_reviewer_assignment_issues(plan: Plan) -> List[ValidationIssue]:
    if not _check_security_reviewer_assignment(plan, plan.tasks):
        return []
    review_tasks = [task for task in plan.tasks if _is_security_review_task(task)]
    execution_tasks = [
        task for task in plan.tasks
        if not _is_security_review_task(task) and _task_claims_production_code(task)
    ]
    return [ValidationIssue(
        code=W_SECURITY_REVIEW_NOT_INDEPENDENT,
        severity="warning",
        message="security review task assignment is not provably independent from implementation tasks",
        task_ids=[task.id for task in review_tasks],
        evidence={
            "review_task_ids": [task.id for task in review_tasks],
            "execution_task_ids": [task.id for task in execution_tasks],
            "review_assignments": [_task_assignment_label(task) for task in review_tasks],
            "execution_assignments": [_task_assignment_label(task) for task in execution_tasks],
        },
    )]


def _is_security_review_task(task: Any) -> bool:
    texts = (
        str(_task_value(task, "title") or "").casefold(),
        str(_task_value(task, "goal_behavior") or "").casefold(),
    )
    return any(token in text for text in texts for token in SECURITY_REVIEW_TOKENS)


def _task_claims_production_code(task: Any) -> bool:
    for claimed_path in _task_value(task, "claimed_paths") or []:
        normalized = str(claimed_path).strip().replace("\\", "/").strip("/")
        if not normalized or _is_claimed_test_path(normalized):
            continue
        if normalized.startswith("src/"):
            return True
        if any(normalized.endswith(ext) for ext in _PATH_EXTENSIONS):
            return True
    return False


def _task_is_independent_from_execution(review_task: Any, execution_tasks: List[Any]) -> bool:
    review_identity = _task_assignment_identity(review_task)
    if review_identity is None:
        return False
    review_kind, review_value = review_identity
    for execution_task in execution_tasks:
        execution_identity = _task_assignment_identity(execution_task)
        if execution_identity is None:
            return False
        execution_kind, execution_value = execution_identity
        if execution_kind != review_kind or execution_value == review_value:
            return False
    return True


def _task_assignment_identity(task: Any) -> Tuple[str, str] | None:
    actor = str(_task_value(task, "actor") or "").strip().casefold()
    if actor:
        return ("actor", actor)
    role = str(_task_value(task, "role") or "").strip().casefold()
    if role:
        return ("role", role)
    return None


def _task_assignment_label(task: Any) -> str:
    identity = _task_assignment_identity(task)
    if identity is None:
        return ""
    kind, value = identity
    return f"{kind}:{value}"


def _task_value(task: Any, field_name: str) -> Any:
    if isinstance(task, dict):
        return task.get(field_name)
    return getattr(task, field_name, None)


def _check_claimed_test_not_exercised(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        claimed_test_paths = _claimed_test_paths(task.claimed_paths)
        if not claimed_test_paths:
            continue
        check_commands = _verification_check_commands(task)
        for test_path in claimed_test_paths:
            if any(_command_exercises_test_path(command, test_path) for command in check_commands):
                continue
            issues.append(ValidationIssue(
                code="W_CLAIMED_TEST_NOT_EXERCISED",
                severity="warning",
                message=f"task '{task.id}' claims test file '{test_path}' but no verification check exercises it",
                task_ids=[task.id],
                evidence={"claimed_test_path": test_path},
            ))
    return issues


def _claimed_test_paths(claimed_paths: List[str]) -> List[str]:
    test_paths: List[str] = []
    seen_paths: Set[str] = set()
    for claimed_path in claimed_paths:
        normalized = claimed_path.strip().replace("\\", "/").strip("/")
        if not _is_claimed_test_path(normalized) or normalized in seen_paths:
            continue
        test_paths.append(normalized)
        seen_paths.add(normalized)
    return test_paths


def _is_claimed_test_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/").strip("/")
    if not normalized:
        return False
    basename = normalized.rsplit("/", 1)[-1]
    if normalized.startswith("tests/") or "/test_" in normalized or "/tests/" in normalized:
        return True
    if basename.startswith(_TEST_BASENAME_PREFIX) or basename.endswith(_TEST_BASENAME_SUFFIX):
        return True
    if not normalized.endswith(_PYTHON_TEST_SUFFIX):
        return False
    return "tests" in Path(normalized).parts


def _verification_check_commands(task: TaskSpec) -> List[str]:
    verification = task.verification
    if verification is None:
        return []
    commands = [verification.command, *[check.command for check in verification.checks]]
    seen_commands: Set[str] = set()
    filtered_commands: List[str] = []
    for command in commands:
        stripped = command.strip()
        if not stripped or stripped in seen_commands:
            continue
        filtered_commands.append(stripped)
        seen_commands.add(stripped)
    return filtered_commands


def _command_exercises_test_path(command: str, test_path: str) -> bool:
    command_text = command.casefold()
    normalized_path = test_path.casefold()
    basename = normalized_path.rsplit("/", 1)[-1]
    if normalized_path in command_text or basename in command_text:
        return True
    if _is_bare_pytest_suite(command):
        return True
    if not _is_pytest_or_tox_suite(command):
        return False
    return any(
        _directory_target_covers_test_path(target, normalized_path)
        for target in _extract_paths_from_command(command)
    )


def _is_bare_pytest_suite(command: str) -> bool:
    return _is_pytest_suite(command) and not _extract_paths_from_command(command)


def _is_pytest_or_tox_suite(command: str) -> bool:
    return _is_pytest_suite(command) or re.search(r"(^|\s)tox(\s|$)", command.casefold()) is not None


def _is_pytest_suite(command: str) -> bool:
    return re.search(r"(^|\s)(python\s+-m\s+)?pytest(\s|$)", command.casefold()) is not None


def _directory_target_covers_test_path(target: str, test_path: str) -> bool:
    normalized_target = target.replace("\\", "/").strip("/").casefold().split("::", 1)[0]
    if not normalized_target or normalized_target.endswith(_PYTHON_TEST_SUFFIX):
        return False
    return test_path == normalized_target or test_path.startswith(f"{normalized_target.rstrip('/')}/")


# ---------------------------------------------------------------------------
# 9. Issue coverage — required_issues must be addressed
# ---------------------------------------------------------------------------

def _check_issue_coverage(plan: Plan) -> List[ValidationIssue]:
    """Check that all required_issues are addressed by at least one task."""
    issues: List[ValidationIssue] = []
    if not plan.required_issues:
        return issues

    addressed = set()
    for t in plan.tasks:
        addressed.update(t.addresses)

    for issue_id in plan.required_issues:
        if issue_id not in addressed:
            issues.append(ValidationIssue(
                code="E_UNCOVERED_REQUIRED_ISSUE",
                severity="error",
                message=f"required issue '{issue_id}' is not addressed by any task",
                evidence={"issue_id": issue_id},
            ))

    return issues


def _check_acceptance_coverage(
    plan: Plan,
    tracker_path: Path | str | None,
) -> List[ValidationIssue]:
    raw_tracker_path = str(tracker_path or "").strip()
    if not raw_tracker_path:
        return []
    tracker_file = Path(raw_tracker_path)
    if not tracker_file.is_file():
        return []

    tracker_text = tracker_file.read_text(encoding="utf-8")
    tracker_sections = _tracker_issue_sections(tracker_text)
    issues: List[ValidationIssue] = []
    for issue_id in plan.required_issues:
        tracker_section = tracker_sections.get(issue_id.upper())
        addressed_tasks = [task for task in plan.tasks if issue_id in task.addresses]
        issue = _acceptance_coverage_issue(
            issue_id,
            tracker_section,
            addressed_tasks,
            str(tracker_file),
        )
        if issue is not None:
            issues.append(issue)
    return issues


def _acceptance_coverage_issue(
    issue_id: str,
    tracker_section: List[str] | None,
    addressed_tasks: List[TaskSpec],
    tracker_path: str,
) -> ValidationIssue | None:
    if tracker_section is None or not addressed_tasks:
        return None
    tracker_acceptance = _tracker_acceptance_text(tracker_section)
    tracker_keywords = _acceptance_keywords(tracker_acceptance)
    if not tracker_keywords:
        return None
    plan_acceptance = " ".join(task.acceptance_criteria for task in addressed_tasks).lower()
    matched_keywords = [keyword for keyword in tracker_keywords if keyword in plan_acceptance]
    coverage = len(matched_keywords) / len(tracker_keywords)
    if coverage >= _ACCEPTANCE_COVERAGE_THRESHOLD:
        return None
    return ValidationIssue(
        code="W_ACCEPTANCE_COVERAGE_GAP",
        severity="warning",
        message=(
            f"issue '{issue_id}' acceptance coverage is {coverage:.2f} "
            f"({len(matched_keywords)}/{len(tracker_keywords)} tracker keywords matched)"
        ),
        task_ids=[task.id for task in addressed_tasks],
        evidence={
            "issue_id": issue_id,
            "coverage": coverage,
            "tracker_keywords": tracker_keywords,
            "matched_keywords": matched_keywords,
            "tracker_path": tracker_path,
        },
    )


def _check_status_code_drift(plan: Plan) -> List[ValidationIssue]:
    """Check for status code drift between goal_behavior and acceptance_criteria."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        goal_codes = _extract_status_codes(task.goal_behavior)
        acceptance_codes = _extract_status_codes(task.acceptance_criteria)
        if not goal_codes or not acceptance_codes:
            continue
        drifted = goal_codes - acceptance_codes
        if drifted:
            issues.append(ValidationIssue(
                code="W_STATUS_CODE_DRIFT",
                severity="warning",
                message=(
                    f"task {task.id!r} goal_behavior declares status codes "
                    f"{sorted(drifted)} not present in acceptance_criteria"
                ),
                task_ids=[task.id],
                evidence={
                    "goal_codes": sorted(goal_codes),
                    "acceptance_codes": sorted(acceptance_codes),
                    "drifted": sorted(drifted),
                },
            ))
    return issues


def _extract_status_codes(text: str) -> Set[str]:
    """Extract HTTP status codes from plan text."""
    if not text:
        return set()
    return {match.group(1) for match in _STATUS_CODE_RE.finditer(text)}


def _extract_status_code_literals(text: str) -> Set[str]:
    if not text:
        return set()
    return set(_STATUS_CODE_LITERAL_RE.findall(text))


def _status_code_candidates(text: str) -> Set[str]:
    return _extract_status_codes(text) | _extract_status_code_literals(text)


def _claimed_python_status_codes(
    claimed_paths: List[str],
    project_root: Path,
) -> tuple[Set[str], List[str]]:
    status_codes: Set[str] = set()
    scanned_paths: List[str] = []
    for claimed_path in claimed_paths:
        source_path = Path(claimed_path)
        if source_path.suffix != ".py":
            continue
        resolved_path = source_path if source_path.is_absolute() else project_root / source_path
        if not resolved_path.is_file():
            continue
        scanned_paths.append(claimed_path)
        content = resolved_path.read_text(encoding="utf-8")
        status_codes.update(_status_code_candidates(content))
    return status_codes, scanned_paths


def _check_status_code_implementation_drift(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if project_root is None:
        return issues

    root = Path(project_root)
    for task in plan.tasks:
        goal_codes = _status_code_candidates(task.goal_behavior)
        if not goal_codes:
            continue
        implementation_codes, scanned_paths = _claimed_python_status_codes(
            task.claimed_paths,
            root,
        )
        if not scanned_paths:
            continue
        drifted = goal_codes - implementation_codes
        if not drifted:
            continue
        issues.append(ValidationIssue(
            code="W_STATUS_CODE_IMPLEMENTATION_DRIFT",
            severity="warning",
            message=(
                f"task {task.id!r} goal_behavior declares status codes "
                f"{sorted(drifted)} not present in claimed Python sources"
            ),
            task_ids=[task.id],
            evidence={
                "goal_codes": sorted(goal_codes),
                "implementation_codes": sorted(implementation_codes),
                "drifted": sorted(drifted),
                "scanned_paths": scanned_paths,
            },
        ))
    return issues


def _tracker_issue_sections(tracker_text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_issue_ids: List[str] = []
    current_lines: List[str] = []
    for line in tracker_text.splitlines():
        if line.startswith(_TRACKER_SECTION_PREFIX):
            _store_tracker_section(sections, current_issue_ids, current_lines)
            current_issue_ids = _heading_issue_ids(line)
            current_lines = []
            continue
        if current_issue_ids:
            current_lines.append(line)
    _store_tracker_section(sections, current_issue_ids, current_lines)
    return sections


def _store_tracker_section(
    sections: Dict[str, List[str]],
    issue_ids: List[str],
    lines: List[str],
) -> None:
    for issue_id in issue_ids:
        sections.setdefault(issue_id, list(lines))


def _heading_issue_ids(heading_line: str) -> List[str]:
    seen: Set[str] = set()
    issue_ids: List[str] = []
    for match in _TRACKER_ISSUE_RE.findall(heading_line.upper()):
        if match in seen:
            continue
        seen.add(match)
        issue_ids.append(match)
    return issue_ids


def _tracker_acceptance_text(section_lines: List[str]) -> str:
    collected: List[str] = []
    collecting = False
    for line in section_lines:
        stripped = line.strip()
        if not stripped:
            if collecting:
                collected.append("")
            continue
        if not collecting:
            if _ACCEPTANCE_HEADER_RE.search(stripped) is None:
                continue
            collecting = True
            inline = _acceptance_inline_text(stripped)
            if inline:
                collected.append(inline)
            continue
        if _is_acceptance_block_break(stripped):
            break
        collected.append(stripped)
    return "\n".join(part for part in collected if part).replace("`", " ").strip()


def _acceptance_inline_text(line: str) -> str:
    matched = _ACCEPTANCE_INLINE_RE.search(line)
    if matched is None:
        return ""
    return matched.group(1).replace("**", " ").replace("__", " ").strip()


def _is_acceptance_block_break(line: str) -> bool:
    return bool(
        re.match(r"^#{1,6}\s+", line)
        or _ACCEPTANCE_FIELD_BREAK_RE.match(line)
    )


def _acceptance_keywords(acceptance_text: str) -> List[str]:
    seen: Set[str] = set()
    keywords: List[str] = []
    for raw_keyword in _ASCII_KEYWORD_RE.findall(acceptance_text.lower()):
        if raw_keyword in _ACCEPTANCE_STOPWORDS:
            continue
        if raw_keyword in seen:
            continue
        seen.add(raw_keyword)
        keywords.append(raw_keyword)
    return keywords


def _check_task_addresses_disjoint(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    # Check 1: Single task with mixed-prefix addresses
    for t in plan.tasks:
        if len(t.addresses) <= 1:
            continue
        prefixes: Set[str] = set()
        for addr in t.addresses:
            # Extract prefix: everything before the first dash+digit
            m = re.match(r"^([A-Za-z]+(?:-[A-Za-z]+)*)", addr)
            if m:
                prefixes.add(m.group(1))
        if len(prefixes) > 1:
            groups: Dict[str, List[str]] = {}
            for addr in t.addresses:
                m = re.match(r"^([A-Za-z]+(?:-[A-Za-z]+)*)", addr)
                prefix = m.group(1) if m else "unknown"
                groups.setdefault(prefix, []).append(addr)
            issues.append(ValidationIssue(
                code="W_TASK_ADDRESSES_DISJOINT",
                severity="warning",
                message=(
                    f"task '{t.id}' addresses issues from different domains: "
                    f"{', '.join(sorted(prefixes))}"
                ),
                task_ids=[t.id],
                evidence={"task_id": t.id, "address_groups": groups},
            ))

    # Check 2: Same issue addressed by multiple tasks
    issue_to_tasks: Dict[str, List[str]] = {}
    for t in plan.tasks:
        for addr in t.addresses:
            issue_to_tasks.setdefault(addr, []).append(t.id)
    for issue_id, task_ids in issue_to_tasks.items():
        if len(task_ids) > 1:
            issues.append(ValidationIssue(
                code="H_DUPLICATE_ISSUE_ADDRESS",
                severity="hint",
                message=(
                    f"issue '{issue_id}' is addressed by multiple tasks: "
                    f"{', '.join(sorted(task_ids))}"
                ),
                task_ids=sorted(task_ids),
                evidence={"issue_id": issue_id, "addressing_tasks": sorted(task_ids)},
            ))

    return issues


def _check_mock_tests_completeness(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for t in plan.tasks:
        if not t.verification or not getattr(t.verification, "mock_tests", None):
            continue
        mode = getattr(t, "verification_mode", "ralph") or "ralph"
        if mode == "ralph":
            issues.append(ValidationIssue(
                code="H_MOCK_TESTS_ON_RALPH_MODE",
                severity="hint",
                message=(
                    f"task '{t.id}' has mock_tests but verification_mode='ralph'; "
                    "mock_tests only run in agent/challenge mode"
                ),
                task_ids=[t.id],
            ))
        for mt in t.verification.mock_tests:
            if not mt.name.strip():
                issues.append(ValidationIssue(
                    code="E_MOCK_TEST_MISSING_NAME",
                    severity="error",
                    message=f"task '{t.id}' has a mock_test with empty name",
                    task_ids=[t.id],
                ))
            if not mt.verify_command.strip():
                issues.append(ValidationIssue(
                    code="E_MOCK_TEST_MISSING_VERIFY_COMMAND",
                    severity="error",
                    message=f"task '{t.id}' mock_test '{mt.name}' has no verify_command",
                    task_ids=[t.id],
                ))
    return issues


# ---------------------------------------------------------------------------
# 11. Forbidden flows — anti-bypass declarations
# ---------------------------------------------------------------------------

def _check_forbidden_flows(plan: Plan) -> List[ValidationIssue]:
    """Check that declared forbidden_flows are covered by negative tests."""
    issues: List[ValidationIssue] = []
    if not plan.forbidden_flows:
        return issues

    # Collect all flows covered by any verification
    all_covered_flows: Set[str] = set()
    for t in plan.tasks:
        if t.verification:
            all_covered_flows.update(t.verification.covers.flows)

    # Map flow_id -> best verification level
    flow_best_level: Dict[str, int] = {}
    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        level_num = _LEVEL_ORDER.get(v.level, 0)
        for flow_id in v.covers.flows:
            if flow_id not in flow_best_level or level_num > flow_best_level[flow_id]:
                flow_best_level[flow_id] = level_num

    for flow in plan.forbidden_flows:
        if flow.id not in all_covered_flows:
            failed_tasks = _failed_test_creator_ids(
                flow.test_created_by,
                plan.state.failed_task_ids,
            )
            if failed_tasks:
                issues.append(ValidationIssue(
                    code="E_FLOW_TEST_CREATOR_FAILED",
                    severity="error",
                    message=(
                        f"forbidden flow '{flow.id}' is uncovered because its "
                        "test creator task already failed"
                    ),
                    evidence={
                        "flow_id": flow.id,
                        "namespace": "forbidden",
                        "failed_task_ids": failed_tasks,
                    },
                ))
                continue
            pending_tasks = _pending_test_creator_ids(
                flow.test_created_by,
                plan.state.completed_task_ids,
                plan.state.failed_task_ids,
            )
            if pending_tasks:
                issues.append(ValidationIssue(
                    code="E_FORBIDDEN_FLOW_UNCOVERED",
                    severity="hint",
                    message=f"[deferred] forbidden flow '{flow.id}' has no negative test covering it",
                    evidence={
                        "flow_id": flow.id,
                        "test_created_by": list(flow.test_created_by),
                        "pending_task_ids": pending_tasks,
                    },
                ))
                issues.append(ValidationIssue(
                    code="W_FLOW_COVERAGE_DEFERRED",
                    severity="warning",
                    message="[deferred] flow coverage not yet satisfied (creator pending)",
                    evidence={
                        "flow_id": flow.id,
                        "namespace": "forbidden",
                        "test_created_by": list(flow.test_created_by),
                        "pending_task_ids": pending_tasks,
                    },
                ))
                continue
            issues.append(ValidationIssue(
                code="E_FORBIDDEN_FLOW_UNCOVERED",
                severity="error",
                message=f"forbidden flow '{flow.id}' has no negative test covering it",
                evidence={"flow_id": flow.id},
            ))
        else:
            required = _LEVEL_ORDER.get(flow.required_verification_level, 0)
            actual = flow_best_level.get(flow.id, 0)
            if actual < required:
                actual_name = [k for k, v in _LEVEL_ORDER.items() if v == actual][0]
                issues.append(ValidationIssue(
                    code="E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK",
                    severity="error",
                    message=f"forbidden flow '{flow.id}' requires {flow.required_verification_level} "
                            f"but best coverage is {actual_name}",
                    evidence={
                        "flow_id": flow.id,
                        "required": flow.required_verification_level,
                        "actual": actual_name,
                    },
                ))

    return issues


def _check_forbidden_flow_field_coverage(
    plan: Plan,
    *,
    project_root: Path | None = None,
) -> List[ValidationIssue]:
    """Check forbidden flow fields in verification text and test file contents."""
    issues: List[ValidationIssue] = []
    if not plan.forbidden_flows:
        return issues

    all_covered_flows = _covered_flow_ids(plan)
    for flow in plan.forbidden_flows:
        if flow.id not in all_covered_flows:
            continue
        issues.extend(_forbidden_flow_field_issues_for_flow(
            plan,
            flow,
            project_root,
        ))
    return issues


def _covered_flow_ids(plan: Plan) -> Set[str]:
    covered_flow_ids: Set[str] = set()
    for task in plan.tasks:
        if task.verification:
            covered_flow_ids.update(task.verification.covers.flows)
    return covered_flow_ids


def _forbidden_flow_field_issues_for_flow(
    plan: Plan,
    flow: Any,
    project_root: Path | None,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    declared_fields = _extract_forbidden_flow_fields(flow.description)
    if not declared_fields:
        return issues
    covering_tasks = _covering_tasks_for_flow(plan, flow)
    if not covering_tasks:
        return issues
    covering_task_ids = [task.id for task in covering_tasks]
    uncovered = _declared_forbidden_fields_uncovered(covering_tasks, declared_fields)
    if uncovered:
        issues.append(_forbidden_flow_field_uncovered_issue(
            flow_id=flow.id,
            declared_fields=declared_fields,
            covering_task_ids=covering_task_ids,
            uncovered_fields=uncovered,
        ))
    unseen_fields, assertion_missing_fields, scanned_test_files, candidate_test_files = _untested_forbidden_flow_fields(
        covering_tasks,
        declared_fields,
        project_root,
    )
    if project_root is None:
        unverifiable_issue = _forbidden_flow_field_test_unverifiable_issue(
            flow_id=flow.id,
            declared_fields=declared_fields,
            covering_task_ids=covering_task_ids,
            uncovered_fields=uncovered,
            candidate_test_files=candidate_test_files,
        )
        if unverifiable_issue is not None:
            issues.append(unverifiable_issue)
        return issues
    if unseen_fields:
        issues.append(_forbidden_flow_field_test_issue(
            code="W_FORBIDDEN_FLOW_FIELD_UNTESTED",
            flow_id=flow.id,
            declared_fields=declared_fields,
            covering_task_ids=covering_task_ids,
            scanned_test_files=scanned_test_files,
            field_key="untested_fields",
            fields=unseen_fields,
            message="but covering verification checks do not mention them in test files",
        ))
    if assertion_missing_fields:
        issues.append(_forbidden_flow_field_test_issue(
            code=W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING,
            flow_id=flow.id,
            declared_fields=declared_fields,
            covering_task_ids=covering_task_ids,
            scanned_test_files=scanned_test_files,
            field_key="assertion_missing_fields",
            fields=assertion_missing_fields,
            message="but covering verification checks mention them in test files without negative assertions",
        ))
    return issues


def _forbidden_flow_field_uncovered_issue(
    *,
    flow_id: str,
    declared_fields: Set[str],
    covering_task_ids: List[str],
    uncovered_fields: Set[str],
) -> ValidationIssue:
    return ValidationIssue(
        code="W_FORBIDDEN_FLOW_FIELD_UNCOVERED",
        severity="warning",
        message=(
            f"forbidden flow {flow_id!r} declares fields {sorted(uncovered_fields)} "
            "but no covering task verifies them"
        ),
        task_ids=covering_task_ids,
        evidence={
            "flow_id": flow_id,
            "declared_fields": sorted(declared_fields),
            "covering_task_ids": covering_task_ids,
            "uncovered_fields": sorted(uncovered_fields),
        },
    )


def _forbidden_flow_field_test_issue(
    *,
    code: str,
    flow_id: str,
    declared_fields: Set[str],
    covering_task_ids: List[str],
    scanned_test_files: List[str],
    field_key: str,
    fields: Set[str],
    message: str,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity="warning",
        message=f"forbidden flow {flow_id!r} declares fields {sorted(fields)} {message}",
        task_ids=covering_task_ids,
        evidence={
            "flow_id": flow_id,
            "declared_fields": sorted(declared_fields),
            "covering_task_ids": covering_task_ids,
            "scanned_test_files": scanned_test_files,
            field_key: sorted(fields),
        },
    )


def _forbidden_flow_field_test_unverifiable_issue(
    *,
    flow_id: str,
    declared_fields: Set[str],
    covering_task_ids: List[str],
    uncovered_fields: Set[str],
    candidate_test_files: List[str],
) -> ValidationIssue | None:
    if not candidate_test_files:
        return None
    unverifiable_fields = declared_fields - uncovered_fields
    if not unverifiable_fields:
        return None
    return ValidationIssue(
        code=W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE,
        severity="warning",
        message=(
            f"forbidden flow {flow_id!r} declares fields {sorted(unverifiable_fields)} "
            "but test-file coverage cannot be verified without project_root"
        ),
        task_ids=covering_task_ids,
        evidence={
            "flow_id": flow_id,
            "declared_fields": sorted(declared_fields),
            "covering_task_ids": covering_task_ids,
            "candidate_test_files": candidate_test_files,
            "unverifiable_fields": sorted(unverifiable_fields),
            "reason": "project_root_missing",
        },
    )


def _declared_forbidden_fields_uncovered(
    covering_tasks: List[TaskSpec],
    declared_fields: Set[str],
) -> Set[str]:
    covered_fields: Set[str] = set()
    for task in covering_tasks:
        lowered_text = _verification_text_surfaces(task).casefold()
        for field in declared_fields:
            if field.casefold() in lowered_text:
                covered_fields.add(field)
    return declared_fields - covered_fields


def _untested_forbidden_flow_fields(
    covering_tasks: List[TaskSpec],
    declared_fields: Set[str],
    project_root: Path | None,
) -> tuple[Set[str], Set[str], List[str], List[str]]:
    candidate_test_files = _forbidden_flow_candidate_test_files(covering_tasks)
    if project_root is None or not candidate_test_files:
        return set(), set(), [], candidate_test_files

    seen_fields: Set[str] = set()
    asserted_fields: Set[str] = set()
    scanned_test_files: List[str] = []
    file_cache: Dict[str, Optional[str]] = {}
    root = Path(project_root)

    for test_path in candidate_test_files:
        content = _read_project_text_file(root, test_path, file_cache)
        if content is None:
            continue
        scanned_test_files.append(test_path)
        for field in declared_fields:
            if not _text_mentions_field(content, field):
                continue
            seen_fields.add(field)
            if _has_field_negative_assertion(content, field):
                asserted_fields.add(field)
    if not scanned_test_files:
        return set(), set(), [], candidate_test_files
    unseen_fields = declared_fields - seen_fields
    seen_without_negative_assert = seen_fields - asserted_fields
    return unseen_fields, seen_without_negative_assert, scanned_test_files, candidate_test_files


def _forbidden_flow_candidate_test_files(covering_tasks: List[TaskSpec]) -> List[str]:
    candidate_test_files: List[str] = []
    seen_test_files: Set[str] = set()
    for task in covering_tasks:
        for command in _verification_check_commands(task):
            for test_path in _check_command_test_paths(command):
                if test_path in seen_test_files:
                    continue
                candidate_test_files.append(test_path)
                seen_test_files.add(test_path)
    return candidate_test_files


def _has_field_negative_assertion(test_content: str, field_name: str) -> bool:
    lines = test_content.splitlines()
    for index, line in enumerate(lines):
        if not _text_mentions_field(line, field_name):
            continue
        context = _field_assertion_context(lines, index)
        if _has_negative_assertion_signature(context):
            return True
        if "pytest.raises" in context:
            return True
        if _has_malformed_rejection_assertion(context):
            return True
    return False


def _field_assertion_context(lines: List[str], index: int) -> str:
    start = max(0, index - _FORBIDDEN_FLOW_ASSERTION_WINDOW)
    end = min(len(lines), index + _FORBIDDEN_FLOW_ASSERTION_WINDOW + 1)
    return "\n".join(lines[start:end]).casefold()


def _has_negative_assertion_signature(context: str) -> bool:
    if "assert" not in context:
        return False
    if _CLIENT_ERROR_STATUS_RE.search(context):
        return True
    return any(token in context for token in _FORBIDDEN_FLOW_NEGATIVE_ASSERTION_TOKENS)


def _has_malformed_rejection_assertion(context: str) -> bool:
    if "assert" not in context:
        return False
    has_malformed_input = any(
        token in context for token in _FORBIDDEN_FLOW_MALFORMED_INPUT_TOKENS
    )
    if not has_malformed_input:
        return False
    return any(token in context for token in _FORBIDDEN_FLOW_NEGATIVE_ASSERTION_TOKENS)


def _text_mentions_field(text: str, field_name: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9_]+", field_name):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(field_name)}(?![A-Za-z0-9_])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return field_name.casefold() in text.casefold()


def _check_command_test_paths(command: str) -> List[str]:
    test_paths: List[str] = []
    seen_paths: Set[str] = set()
    for path in _extract_paths_from_command(command):
        normalized = path.strip().strip("'\"").replace("\\", "/").split("::", 1)[0]
        if not _is_claimed_test_path(normalized) or normalized in seen_paths:
            continue
        test_paths.append(normalized)
        seen_paths.add(normalized)
    return test_paths


def _read_project_text_file(
    project_root: Path,
    rel_path: str,
    file_cache: Dict[str, Optional[str]],
) -> Optional[str]:
    if rel_path in file_cache:
        return file_cache[rel_path]

    source_path = Path(rel_path)
    resolved_path = source_path if source_path.is_absolute() else project_root / source_path
    if not resolved_path.is_file() or not _is_within_root(resolved_path.resolve(), project_root.resolve()):
        file_cache[rel_path] = None
        return None

    file_cache[rel_path] = resolved_path.read_text(encoding="utf-8")
    return file_cache[rel_path]


def _extract_forbidden_flow_fields(description: str) -> Set[str]:
    """Extract field names from forbidden_flow description using high-confidence patterns."""
    fields: Set[str] = set()
    fields.update(match.strip() for match in re.findall(r"`([^`]+)`", description) if match.strip())
    fields.update(m.group(1) for m in re.finditer(r"\b(\w+)\s*=\s*\w+", description))
    fields.update(m.group(0) for m in re.finditer(r"\bis_\w+", description))
    for match in re.finditer(r"MUST NOT (?:accept|allow|permit)\s+(\w+)", description, re.IGNORECASE):
        fields.add(match.group(1))
    for match in re.finditer(r"禁止\s*(\w+)\s*注入", description):
        fields.add(match.group(1))
    return fields


def _verification_text_surfaces(task: object) -> str:
    """Unified extraction of all verification text from a task."""
    parts: List[str] = []
    verification = getattr(task, "verification", None)
    if verification is None:
        return ""
    if hasattr(verification, "command") and verification.command:
        parts.append(str(verification.command))
    for check in getattr(verification, "checks", []) or []:
        parts.append(str(getattr(check, "name", "") or ""))
        parts.append(str(getattr(check, "command", "") or ""))
    for mock_test in getattr(verification, "mock_tests", []) or []:
        dump = mock_test.model_dump() if hasattr(mock_test, "model_dump") else mock_test
        parts.append(str(dump))
    return " ".join(part for part in parts if part)


def _check_finding_refs(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    allowed_prefixes = ("E_", "W_", "H_", "ralph:", "monitor:")

    for ref in plan.finding_refs:
        if not ref.id.strip():
            issues.append(ValidationIssue(
                code="W_FINDING_REF_INCOMPLETE",
                severity="warning",
                message="finding_ref is missing id",
                evidence={"field": "id"},
            ))
        if not ref.mitigation.strip():
            issues.append(ValidationIssue(
                code="W_FINDING_REF_INCOMPLETE",
                severity="warning",
                message=f"finding_ref '{ref.id}' is missing mitigation",
                evidence={"field": "mitigation", "finding_ref_id": ref.id},
            ))
        for enforcer in ref.enforced_by:
            if enforcer.startswith(allowed_prefixes):
                continue
            issues.append(ValidationIssue(
                code="W_FINDING_REF_UNKNOWN_ENFORCER",
                severity="hint",
                message=f"finding_ref '{ref.id}' references unknown enforcer '{enforcer}'",
                evidence={"finding_ref_id": ref.id, "enforcer": enforcer},
            ))

    return issues


def _check_suppress_flows(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    declared = {flow.id for flow in plan.critical_flows}
    for flow_id in plan.suppress_flows:
        if flow_id in declared:
            continue
        issues.append(ValidationIssue(
            code="W_SUPPRESS_FLOWS_UNKNOWN",
            severity="warning",
            message=f"suppress_flows references unknown flow '{flow_id}'",
            evidence={"flow_id": flow_id},
        ))
    return issues


# ---------------------------------------------------------------------------
# Completeness rules (CMP bundle)
# ---------------------------------------------------------------------------

def _covered_flow_summary(plan: Plan) -> Dict[str, Any]:
    """Shared helper: gather covered flow IDs and best verification level per flow."""
    covered_flow_ids: Set[str] = set()
    best_level_by_flow: Dict[str, int] = {}
    for task in plan.tasks:
        v = task.verification
        if v is None:
            continue
        level_num = _LEVEL_ORDER.get(v.level, 0)
        for flow_id in v.covers.flows:
            covered_flow_ids.add(flow_id)
            if flow_id not in best_level_by_flow or level_num > best_level_by_flow[flow_id]:
                best_level_by_flow[flow_id] = level_num
    return {"covered_flow_ids": covered_flow_ids, "best_level_by_flow": best_level_by_flow}


def _check_covers_unknown_flow(plan: Plan) -> List[ValidationIssue]:
    """CMP-1: task.verification.covers.flows referencing an undeclared flow id."""
    issues: List[ValidationIssue] = []
    declared_flow_ids = {f.id for f in plan.critical_flows} | {f.id for f in plan.forbidden_flows}

    for task in plan.tasks:
        v = task.verification
        if v is None:
            continue
        for flow_id in v.covers.flows:
            if flow_id not in declared_flow_ids:
                issues.append(ValidationIssue(
                    code="E_COVERS_UNKNOWN_FLOW",
                    severity="error",
                    message=f"task '{task.id}' covers flow '{flow_id}' which is not declared "
                            f"in critical_flows or forbidden_flows",
                    task_ids=[task.id],
                    evidence={"flow_id": flow_id},
                    action_owner="author",
                    worker_relevance="none",
                ))
    return issues


def _check_state_unknown_task_ref(plan: Plan) -> List[ValidationIssue]:
    """CMP-2: state.* lists contain unknown task ids."""
    issues: List[ValidationIssue] = []
    task_ids = {t.id for t in plan.tasks}

    for tid in plan.state.completed_task_ids:
        if tid not in task_ids:
            issues.append(ValidationIssue(
                code="W_STATE_UNKNOWN_TASK_REF",
                severity="warning",
                message=f"state.completed_task_ids references unknown task '{tid}'",
                task_ids=[tid],
                evidence={"list": "completed_task_ids", "unknown_id": tid},
                action_owner="author",
                worker_relevance="none",
            ))

    for tid in plan.state.failed_task_ids:
        if tid not in task_ids:
            issues.append(ValidationIssue(
                code="W_STATE_UNKNOWN_TASK_REF",
                severity="warning",
                message=f"state.failed_task_ids references unknown task '{tid}'",
                task_ids=[tid],
                evidence={"list": "failed_task_ids", "unknown_id": tid},
                action_owner="author",
                worker_relevance="none",
            ))

    for rt in plan.state.running_tasks:
        if rt.task_id not in task_ids:
            issues.append(ValidationIssue(
                code="W_STATE_UNKNOWN_TASK_REF",
                severity="warning",
                message=f"state.running_tasks references unknown task '{rt.task_id}'",
                task_ids=[rt.task_id],
                evidence={"list": "running_tasks", "unknown_id": rt.task_id},
                action_owner="author",
                worker_relevance="none",
            ))

    return issues


def _check_state_task_status_conflict(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    buckets = _state_task_id_buckets(plan)
    for bucket_name, task_ids in buckets.items():
        for task_id in _duplicate_task_ids(task_ids):
            issues.append(ValidationIssue(
                code="E_STATE_TASK_STATUS_CONFLICT",
                severity="error",
                message=f"state bucket '{bucket_name}' contains duplicate task id '{task_id}'",
                task_ids=[task_id],
                evidence={"bucket": bucket_name, "task_id": task_id},
            ))
    for left_bucket, right_bucket in _bucket_pairs():
        shared = sorted(set(buckets[left_bucket]) & set(buckets[right_bucket]))
        for task_id in shared:
            issues.append(ValidationIssue(
                code="E_STATE_TASK_STATUS_CONFLICT",
                severity="error",
                message=f"task '{task_id}' appears in both state buckets '{left_bucket}' and '{right_bucket}'",
                task_ids=[task_id],
                evidence={"task_id": task_id, "buckets": [left_bucket, right_bucket]},
            ))
    return issues


def _check_running_task_claims(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    declared_by_task = {
        task.id: _normalized_claim_paths(task.claimed_paths)
        for task in plan.tasks
    }
    for running_task in plan.state.running_tasks:
        declared_paths = declared_by_task.get(running_task.task_id)
        if declared_paths is None:
            continue
        if not running_task.claimed_paths:
            issues.append(_running_task_claim_issue(running_task.task_id, "empty"))
            continue
        running_paths = _normalized_claim_paths(running_task.claimed_paths)
        if not running_paths:
            issues.append(_running_task_claim_issue(running_task.task_id, "empty"))
            continue
        offending = [
            path for path in running_paths
            if not _claim_within_declared_paths(path, declared_paths)
        ]
        if offending:
            issues.append(_running_task_claim_issue(
                running_task.task_id,
                "out_of_declared",
                offending_paths=offending,
            ))
    return issues


_AF_BYPASS_PATH_MARKERS = ("agentflow/", "af_engine", "actor_runner", "af_patches", "af_state")
_AF_GATE_PATH_MARKERS = ("verification_gate", "apply_task_event")
_AF_GATE_TEXT_TOKENS = ("verification gate", "verificationgate", "apply_task_event")


def _claimed_paths(task: Any) -> List[str]:
    return [str(path) for path in (getattr(task, "claimed_paths", None) or [])]


def _collect_gate_evidence(task: Any, all_tasks: List[Any]) -> Dict[str, List[str]]:
    gate_task_ids = {
        str(getattr(other, "id", "") or "")
        for other in all_tasks
        if any(marker in path for path in _claimed_paths(other) for marker in _AF_GATE_PATH_MARKERS)
    }
    covers = getattr(getattr(task, "verification", None), "covers", None)
    return {
        "claimed_gate_paths": [
            path for path in _claimed_paths(task)
            if any(marker in path for marker in _AF_GATE_PATH_MARKERS)
        ],
        "covers_gate_tasks": [
            task_id for task_id in getattr(covers, "tasks", []) or []
            if task_id in gate_task_ids
        ],
        "depends_on_gate_tasks": [
            task_id for task_id in getattr(task, "depends_on", []) or []
            if task_id in gate_task_ids
        ],
    }


def _gate_text_references(task: Any) -> List[str]:
    text = "\n".join(
        str(getattr(task, field, "") or "")
        for field in ("title", "goal_behavior", "acceptance_criteria")
    ).casefold()
    return [token for token in _AF_GATE_TEXT_TOKENS if token in text]


def _check_af_verification_gate_bypass(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        af_paths = [
            path for path in _claimed_paths(task)
            if any(marker in path for marker in _AF_BYPASS_PATH_MARKERS)
        ]
        if not af_paths:
            continue
        if any(_collect_gate_evidence(task, plan.tasks).values()):
            continue
        text_references = _gate_text_references(task)
        severity = "warning"
        message = (
            f"task {task.id!r} modifies AF engine paths but does not reference "
            "VerificationGate in claimed_paths, verification.covers.tasks, or depends_on"
        )
        evidence: Dict[str, Any] = {"af_paths": af_paths}
        if text_references:
            severity = "hint"
            message = (
                f"task {task.id!r} modifies AF engine paths and only references "
                "VerificationGate in text — add structured gate evidence"
            )
            evidence["text_references"] = text_references
        issues.append(ValidationIssue(
            code="W_AF_VERIFICATION_GATE_BYPASS",
            severity=severity,
            message=message,
            task_ids=[task.id],
            evidence=evidence,
        ))
    return issues


def _check_duplicate_ids(plan: Plan) -> List[ValidationIssue]:
    """CMP-3: duplicate flow IDs, forbidden flow IDs, and invariant names."""
    issues: List[ValidationIssue] = []

    # Duplicate critical flow IDs
    seen_flow: Set[str] = set()
    for flow in plan.critical_flows:
        if flow.id in seen_flow:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_FLOW_ID",
                severity="error",
                message=f"duplicate critical_flow id '{flow.id}'",
                evidence={"flow_id": flow.id},
                action_owner="author",
                worker_relevance="none",
            ))
        seen_flow.add(flow.id)

    # Duplicate forbidden flow IDs
    seen_forbidden: Set[str] = set()
    for flow in plan.forbidden_flows:
        if flow.id in seen_forbidden:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_FORBIDDEN_FLOW_ID",
                severity="error",
                message=f"duplicate forbidden_flow id '{flow.id}'",
                evidence={"flow_id": flow.id},
                action_owner="author",
                worker_relevance="none",
            ))
        seen_forbidden.add(flow.id)

    # Duplicate registration invariant names
    seen_inv: Set[str] = set()
    for inv in plan.registration_invariants:
        if inv.name in seen_inv:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_INVARIANT_NAME",
                severity="error",
                message=f"duplicate registration_invariant name '{inv.name}'",
                evidence={"invariant_name": inv.name},
                action_owner="author",
                worker_relevance="none",
            ))
        seen_inv.add(inv.name)

    return issues


def _check_flow_test_created_by_unknown(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    valid_task_ids = {task.id for task in plan.tasks}
    namespaces = (
        ("critical", plan.critical_flows),
        ("forbidden", plan.forbidden_flows),
    )
    for namespace, flows in namespaces:
        for flow in flows:
            for task_id in flow.test_created_by:
                if task_id in valid_task_ids:
                    continue
                issues.append(ValidationIssue(
                    code="E_FLOW_TEST_CREATED_BY_UNKNOWN_TASK",
                    severity="error",
                    message=f"{namespace} flow '{flow.id}' references unknown test_created_by task '{task_id}'",
                    task_ids=[task_id],
                    evidence={"flow_id": flow.id, "namespace": namespace, "unknown_id": task_id},
                ))
    return issues


def _check_flow_id_cross_namespace(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    critical_ids = {flow.id for flow in plan.critical_flows}
    forbidden_ids = {flow.id for flow in plan.forbidden_flows}
    for flow_id in sorted(critical_ids & forbidden_ids):
        issues.append(ValidationIssue(
            code="E_FLOW_ID_CROSS_NAMESPACE_COLLISION",
            severity="error",
            message=f"flow id '{flow_id}' is declared in both critical_flows and forbidden_flows",
            evidence={"flow_id": flow_id},
        ))
    return issues


def _check_critical_flow_no_entrypoints(plan: Plan) -> List[ValidationIssue]:
    """CMP-4: critical flow declared without any entrypoints."""
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not flow.entrypoints:
            issues.append(ValidationIssue(
                code="W_CRITICAL_FLOW_NO_ENTRYPOINTS",
                severity="warning",
                message=f"critical flow '{flow.id}' has no entrypoints declared",
                evidence={"flow_id": flow.id},
                action_owner="author",
                worker_relevance="none",
            ))
    return issues


def _check_critical_declaration_outside_scope(plan: Plan) -> List[ValidationIssue]:
    if not plan.plan_scope:
        return []
    issues: List[ValidationIssue] = []
    for flow in plan.critical_flows:
        if not flow.entrypoints:
            continue
        if any(_entrypoint_in_scope(ep, plan.plan_scope) for ep in flow.entrypoints):
            continue
        issues.append(ValidationIssue(
            code="W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE",
            severity="warning",
            message=f"critical flow '{flow.id}' is declared entirely outside plan_scope",
            evidence={
                "flow_id": flow.id,
                "entrypoints": list(flow.entrypoints),
                "plan_scope": list(plan.plan_scope),
            },
        ))
    if plan.critical_entrypoints and not any(
        _entrypoint_in_scope(entrypoint, plan.plan_scope)
        for entrypoint in plan.critical_entrypoints
    ):
        issues.append(ValidationIssue(
            code="W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE",
            severity="warning",
            message="critical_entrypoints are declared entirely outside plan_scope",
            evidence={
                "scope": "critical_entrypoints",
                "entrypoints": list(plan.critical_entrypoints),
                "plan_scope": list(plan.plan_scope),
            },
        ))
    return issues


def _check_suppress_unused(plan: Plan, all_issue_codes: Set[str]) -> List[ValidationIssue]:
    """CMP-5: suppress_codes that don't match any emitted issue (runs last)."""
    issues: List[ValidationIssue] = []
    for code in plan.effective_suppress_codes:
        if code not in all_issue_codes:
            issues.append(ValidationIssue(
                code="H_SUPPRESS_UNUSED",
                severity="hint",
                message=f"suppress_codes entry '{code}' did not match any emitted issue",
                evidence={"suppress_code": code},
                action_owner="author",
                worker_relevance="none",
            ))
    return issues


def _check_plan_scope_unused(plan: Plan) -> List[ValidationIssue]:
    """CMP-7: plan-level scope declarations that are never referenced by any task."""
    issues: List[ValidationIssue] = []
    summary = _covered_flow_summary(plan)
    covered_flow_ids: Set[str] = summary["covered_flow_ids"]

    # Critical flows never referenced by any task's covers.flows
    for flow in plan.critical_flows:
        if flow.id not in covered_flow_ids:
            # Already caught by E_CRITICAL_FLOW_UNCOVERED — skip to avoid double-reporting
            continue

    # Required issues not addressed — already caught by E_UNCOVERED_REQUIRED_ISSUE

    # Registration invariants: check if any invariant's registry_file is not
    # covered by any task's claimed_paths
    all_claimed: Set[str] = set()
    for t in plan.tasks:
        all_claimed.update(t.claimed_paths)

    for inv in plan.registration_invariants:
        if not inv.registry_file:
            continue
        owned = any(
            _paths_overlap(inv.registry_file, cp) for cp in all_claimed
        )
        if not owned:
            issues.append(ValidationIssue(
                code="W_PLAN_SCOPE_UNUSED",
                severity="warning",
                message=f"registration invariant '{inv.name}' references '{inv.registry_file}' "
                        f"which is not claimed by any task",
                evidence={"invariant_name": inv.name, "registry_file": inv.registry_file},
                action_owner="author",
                worker_relevance="none",
            ))

    return issues


def _check_full_regression_override_risk(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    override_signal_tasks = sorted(
        task.id for task in plan.tasks if _task_has_override_signal(task)
    )
    if not override_signal_tasks:
        return issues
    for task in plan.tasks:
        full_command = _task_full_regression_command(task)
        if not full_command:
            continue
        issues.append(ValidationIssue(
            code="W_FULL_REGRESSION_OVERRIDE_RISK",
            severity="warning",
            message=f"task '{task.id}' runs a full pytest gate while override signals exist elsewhere in the plan",
            task_ids=[task.id],
            evidence={
                "full_regression_command": full_command,
                "override_signal_tasks": override_signal_tasks,
                "hint": "consider importorskip/skip for planned-failure cases",
            },
        ))
    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commands_reference_paths(commands: List[str], claimed_paths: List[str]) -> bool:
    lowered = " ".join(command.lower() for command in commands if command)
    for path in claimed_paths:
        basename = path.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
        if path.lower() in lowered or basename in lowered:
            return True
    return False


def _command_mentions_any_path(command: str, claimed_paths: List[str]) -> bool:
    return any(path and path in command for path in claimed_paths)


def _has_issue_codes(issues: List[ValidationIssue], codes: Set[str]) -> bool:
    return any(issue.code in codes for issue in issues)


def _is_shallow_check(check: CheckSpec) -> bool:
    return is_shallow_check(check.name, check.command)


def _is_behavioral_check(check: CheckSpec) -> bool:
    name = check.name.lower()
    command = check.command.strip().lower()
    return (
        any(token in name for token in _BEHAVIORAL_CHECK_NAME_TOKENS)
        or re.search(r"(^|\s)(python\s+-m\s+)?pytest(\s|$)", command) is not None
    )


def _is_integration_shallow_check(check: CheckSpec) -> bool:
    command = check.command.strip().lower()
    return _is_shallow_check(check) or command.startswith("grep ")


def _acceptance_risk_keywords(acceptance_criteria: str) -> List[str]:
    text = acceptance_criteria.lower()
    return [keyword for keyword in _ACCEPTANCE_RISK_KEYWORDS if keyword in text]


def _has_self_covering_leaf(tasks: List[TaskSpec]) -> bool:
    return any(_is_self_covering_leaf(task) for task in tasks)


def _is_self_covering_leaf(task: TaskSpec) -> bool:
    verification = task.verification
    if verification is None or task.role != "leaf":
        return False
    return verification.covers.tasks == [task.id]


def _covered_by_downstream_integration_task(task_id: str, task_map: Dict[str, TaskSpec]) -> bool:
    for task in task_map.values():
        verification = task.verification
        if verification is None or verification.level not in ("integration", "e2e"):
            continue
        if task.id == task_id or task_id not in verification.covers.tasks:
            continue
        if task_id in transitive_deps(task.id, task_map):
            return True
    return False


def _pending_test_creator_ids(
    test_created_by: List[str],
    completed_task_ids: List[str],
    failed_task_ids: List[str],
) -> List[str]:
    if not test_created_by:
        return []
    completed = set(completed_task_ids)
    failed = set(failed_task_ids)
    return [
        task_id for task_id in test_created_by
        if task_id not in completed and task_id not in failed
    ]


def _failed_test_creator_ids(
    test_created_by: List[str],
    failed_task_ids: List[str],
) -> List[str]:
    if not test_created_by:
        return []
    failed = set(failed_task_ids)
    return [task_id for task_id in test_created_by if task_id in failed]


def _state_task_id_buckets(plan: Plan) -> Dict[str, List[str]]:
    return {
        "completed_task_ids": list(plan.state.completed_task_ids),
        "failed_task_ids": list(plan.state.failed_task_ids),
        "running_tasks": [running_task.task_id for running_task in plan.state.running_tasks],
    }


def _bucket_pairs() -> Tuple[Tuple[str, str], ...]:
    return (
        ("completed_task_ids", "failed_task_ids"),
        ("completed_task_ids", "running_tasks"),
        ("failed_task_ids", "running_tasks"),
    )


def _duplicate_task_ids(task_ids: List[str]) -> List[str]:
    seen: Set[str] = set()
    duplicates: Set[str] = set()
    for task_id in task_ids:
        if task_id in seen:
            duplicates.add(task_id)
            continue
        seen.add(task_id)
    return sorted(duplicates)


def _normalized_claim_paths(paths: List[str]) -> List[str]:
    return sorted(_normalize_write_set(paths))


def _claim_within_declared_paths(path: str, declared_paths: List[str]) -> bool:
    for declared_path in declared_paths:
        normalized_declared = declared_path.rstrip("/")
        if normalized_declared == "/":
            return True
        if path == normalized_declared or path.startswith(f"{normalized_declared}/"):
            return True
    return False


def _running_task_claim_issue(
    task_id: str,
    reason: str,
    *,
    offending_paths: Optional[List[str]] = None,
) -> ValidationIssue:
    evidence = {"task_id": task_id, "reason": reason}
    if offending_paths:
        evidence["offending_paths"] = sorted(offending_paths)
    return ValidationIssue(
        code="E_STATE_RUNNING_TASK_INVALID_CLAIMS",
        severity="error",
        message=f"running task '{task_id}' has invalid claimed_paths ({reason})",
        task_ids=[task_id],
        evidence=evidence,
    )


def _task_full_regression_command(task: TaskSpec) -> str:
    verification = task.verification
    if verification is None:
        return ""
    commands = [verification.command, *[check.command for check in verification.checks]]
    for command in commands:
        if _is_full_regression_pytest(command):
            return command
    return ""


def _is_full_regression_pytest(command: str) -> bool:
    if not _is_pytest_suite(command):
        return False
    command_text = command.casefold()
    pytest_args = _pytest_command_args(command)
    if any(arg == "-k" or arg.startswith("-k") for arg in pytest_args):
        return False
    if any(arg == "-m" or arg.startswith("-m") for arg in pytest_args):
        return False
    if "--co" in command_text or "--collect-only" in command_text:
        return False
    return not _extract_paths_from_command(command)


def _task_has_override_signal(task: TaskSpec) -> bool:
    verification = task.verification
    if verification is None:
        return False
    texts = [verification.command, *[check.command for check in verification.checks]]
    if any(_text_has_override_signal(text) for text in texts):
        return True
    return any(_mock_test_has_override_signal(mock_test) for mock_test in verification.mock_tests or [])


def _text_has_override_signal(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in _OVERRIDE_SIGNAL_TOKENS)


def _mock_test_has_override_signal(mock_test: Any) -> bool:
    fields = (
        getattr(mock_test, "name", ""),
        getattr(mock_test, "input", ""),
        getattr(mock_test, "expected_output", ""),
        getattr(mock_test, "setup_command", ""),
        getattr(mock_test, "verify_command", ""),
        getattr(mock_test, "description", ""),
    )
    return _text_has_override_signal(" ".join(str(field) for field in fields if field))


def _pytest_command_args(command: str) -> List[str]:
    tokens = command.split()
    for index, token in enumerate(tokens):
        if token.casefold() == "pytest":
            return tokens[index + 1:]
    return []


def _extract_paths_from_command(command: str) -> List[str]:
    """Extract path-like tokens from a shell command string."""
    paths: List[str] = []
    for token in command.split():
        # Skip flags
        if token.startswith("-"):
            continue
        # Skip known command names
        if token.lower() in _COMMAND_SKIP_TOKENS:
            continue
        # Skip shell operators / pipes
        if token in ("&&", "||", ";", "|", ">", ">>", "<", "2>&1"):
            continue
        # Must look like a path: contains "/" or ends with a known extension
        has_slash = "/" in token
        has_ext = any(token.endswith(ext) for ext in _PATH_EXTENSIONS)
        if has_slash or has_ext:
            paths.append(token)
    return paths


def _check_batch_e2e_command(plan: "Plan") -> List["ValidationIssue"]:
    """W_BATCH_E2E_NO_COMMAND: multi-batch plans without batch_e2e_command."""
    from ..models import Plan, ValidationIssue

    if plan.batch_e2e_command:
        return []

    dep_layers = _count_dag_layers(plan)
    if dep_layers <= 1:
        return []

    return [ValidationIssue(
        code="W_BATCH_E2E_NO_COMMAND",
        severity="warning",
        message=(
            f"plan has {dep_layers} dependency layers but no batch_e2e_command — "
            "cross-task integration won't be verified between batches"
        ),
        evidence={"dag_layers": dep_layers},
    )]


def _count_dag_layers(plan: "Plan") -> int:
    """Count the number of DAG layers (batch boundaries) in the plan."""
    task_map = {t.id: t for t in plan.tasks}
    completed = set(plan.state.completed_task_ids) if plan.state else set()
    layers = 0
    remaining = {t.id for t in plan.tasks} - completed
    while remaining:
        ready = {
            tid for tid in remaining
            if all(d in completed or d not in remaining for d in task_map[tid].depends_on)
        }
        if not ready:
            break
        layers += 1
        remaining -= ready
        completed |= ready
    return layers
