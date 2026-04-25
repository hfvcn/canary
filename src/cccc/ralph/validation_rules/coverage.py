"""Coverage validation rules — verification strength, flow coverage, and completeness checks.

Extracted from validator.py as a pure refactor (RO-31).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from cccc.kernel.claimed_paths import normalize_write_set as _normalize_write_set, paths_overlap as _paths_overlap
from ..graph_utils import transitive_deps
from ..models import (
    CheckSpec,
    Plan,
    TaskSpec,
    Verification,
    ValidationIssue,
)


# Ordered levels for comparison
_LEVEL_ORDER: Dict[str, int] = {"compile": 0, "unit": 1, "integration": 2, "e2e": 3}

_SHALLOW_CHECK_NAME_TOKENS = ("compile", "py_compile", "import", "help", "cli_help", "syntax")
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


def _check_verification_shallow_checks(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
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
        issues.append(ValidationIssue(
            code="W_VERIFICATION_SHALLOW_CHECKS",
            severity="warning",
            message=(
                f"task '{task.id}' verification checks are all shallow "
                "(compile/import/help) — consider adding at least one behavioral test check"
            ),
            task_ids=[task.id],
            evidence=evidence,
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
        for covered_id in verification.covers.tasks:
            if covered_id == task.id or covered_id not in task_map:
                continue
            claimed_paths = task_map[covered_id].claimed_paths
            if _commands_reference_paths(commands, claimed_paths):
                continue
            issues.append(ValidationIssue(
                code="W_COVERS_NOT_EXERCISED",
                severity="warning",
                message=f"task '{task.id}' covers '{covered_id}' but its verification does not reference the covered paths",
                task_ids=[task.id, covered_id],
                evidence={"covered_task_id": covered_id, "covered_paths": list(claimed_paths)},
            ))
    return issues


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
    ep_norm = ep.strip().replace("\\", "/")
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
        ep_norm = ep.strip().replace("\\", "/")
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
            if flow.id in plan.suppress_flows:
                issues.append(ValidationIssue(
                    code="E_CRITICAL_FLOW_UNCOVERED",
                    severity="hint",
                    message=f"[suppress_flows] critical flow '{flow.id}' is not covered by any task's verification",
                    evidence={"flow_id": flow.id},
                ))
                continue
            pending_tasks = _pending_test_creator_ids(
                flow.test_created_by, plan.state.completed_task_ids,
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
                continue
            issues.append(ValidationIssue(
                code="E_CRITICAL_FLOW_UNCOVERED",
                severity="error",
                message=f"critical flow '{flow.id}' is not covered by any task's verification",
                evidence={"flow_id": flow.id},
            ))

        # Check entrypoints of this flow are owned
        for ep in flow.entrypoints:
            ep_norm = ep.strip().replace("\\", "/")
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
        if any(_paths_overlap(entrypoint, path) for path in owned_paths):
            result.append(entrypoint)
            continue
        resolved = _resolve_symbol_entrypoint(entrypoint, owned_paths)
        if resolved is not None:
            result.append(entrypoint)
    return result


def _check_flow_segment_ownership(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for flow in plan.critical_flows:
        entrypoints = [ep.strip().replace("\\", "/") for ep in flow.entrypoints]
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
            pending_tasks = _pending_test_creator_ids(
                flow.test_created_by, plan.state.completed_task_ids,
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
    name = check.name.lower()
    command = check.command.strip().lower()
    return (
        any(token in name for token in _SHALLOW_CHECK_NAME_TOKENS)
        or command.startswith("python -m py_compile")
        or _matches_python_inline_import(command)
        or "--help" in command
    )


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


def _matches_python_inline_import(command: str) -> bool:
    return re.search(r"python\s+-c\s+['\"]\s*(from|import)\s+", command) is not None


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
) -> List[str]:
    if not test_created_by:
        return []
    completed = set(completed_task_ids)
    return [task_id for task_id in test_created_by if task_id not in completed]


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
