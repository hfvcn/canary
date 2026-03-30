"""Ralph plan validator — structural checks that catch integration gaps before execution.

Design principle: every check corresponds to a concrete failure mode observed in practice.
The validator reads the Plan and produces a ValidationReport without side effects.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from .core import _normalize_write_set, _paths_overlap
from .models import (
    CriticalFlow,
    Plan,
    TaskSpec,
    Verification,
    VerificationLevel,
    ValidationIssue,
    ValidationReport,
)

# Ordered levels for comparison
_LEVEL_ORDER: Dict[str, int] = {"compile": 0, "unit": 1, "integration": 2, "e2e": 3}


def validate(plan: Plan) -> ValidationReport:
    """Run all structural checks on a plan. Returns a ValidationReport."""
    issues: List[ValidationIssue] = []

    issues.extend(_check_graph_structure(plan))
    issues.extend(_check_field_completeness(plan))
    issues.extend(_check_verification_strength(plan))
    issues.extend(_check_verification_behavior_match(plan))
    issues.extend(_check_contracts(plan))
    issues.extend(_check_contract_dep_alignment(plan))
    issues.extend(_check_critical_coverage(plan))
    issues.extend(_check_critical_flow_levels(plan))
    issues.extend(_check_forbidden_flows(plan))
    issues.extend(_check_issue_coverage(plan))
    issues.extend(_check_implicit_serialization(plan))
    issues.extend(_check_integration_spine(plan))

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    hints = [i for i in issues if i.severity == "hint"]

    return ValidationReport(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        hints=hints,
    )


# ---------------------------------------------------------------------------
# 1. Graph structure
# ---------------------------------------------------------------------------

def _check_graph_structure(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_ids = {t.id for t in plan.tasks}

    # Duplicate IDs
    seen: Set[str] = set()
    for t in plan.tasks:
        if t.id in seen:
            issues.append(ValidationIssue(
                code="E_DUPLICATE_TASK_ID",
                severity="error",
                message=f"duplicate task id '{t.id}'",
                task_ids=[t.id],
            ))
        seen.add(t.id)

    # Unknown deps
    for t in plan.tasks:
        for dep in t.depends_on:
            if dep not in task_ids:
                issues.append(ValidationIssue(
                    code="E_DEP_UNKNOWN",
                    severity="error",
                    message=f"task '{t.id}' depends on unknown task '{dep}'",
                    task_ids=[t.id],
                    evidence={"unknown_dep": dep},
                ))

    # Self-dependency
    for t in plan.tasks:
        if t.id in t.depends_on:
            issues.append(ValidationIssue(
                code="E_DEP_SELF",
                severity="error",
                message=f"task '{t.id}' depends on itself",
                task_ids=[t.id],
            ))

    # Cycle detection (Kahn's algorithm)
    cycle = _detect_cycle(plan.tasks, task_ids)
    if cycle:
        issues.append(ValidationIssue(
            code="E_DEP_CYCLE",
            severity="error",
            message=f"dependency cycle detected involving: {', '.join(cycle)}",
            task_ids=list(cycle),
        ))

    # Disconnected components (warning if >1 and plan has >1 task)
    if len(plan.tasks) > 1:
        components = _find_components(plan.tasks, task_ids)
        if len(components) > 1:
            issues.append(ValidationIssue(
                code="W_DISCONNECTED_COMPONENTS",
                severity="warning",
                message=f"plan has {len(components)} disconnected task groups",
                evidence={"components": [list(c) for c in components]},
            ))

    # Isolated task (no deps in or out)
    dep_targets = set()
    dep_sources = set()
    for t in plan.tasks:
        if t.depends_on:
            dep_sources.add(t.id)
            dep_targets.update(t.depends_on)
    for t in plan.tasks:
        if len(plan.tasks) > 2 and t.id not in dep_targets and t.id not in dep_sources:
            issues.append(ValidationIssue(
                code="W_ISOLATED_TASK",
                severity="warning",
                message=f"task '{t.id}' has no dependency edges (neither depends on others nor depended upon)",
                task_ids=[t.id],
            ))

    return issues


def _detect_cycle(tasks: List[TaskSpec], task_ids: Set[str]) -> List[str]:
    """Return task IDs involved in a cycle, or empty list if DAG is valid."""
    adj: Dict[str, List[str]] = {t.id: [] for t in tasks}
    in_degree: Dict[str, int] = {t.id: 0 for t in tasks}

    for t in tasks:
        for dep in t.depends_on:
            if dep in task_ids:
                adj[dep].append(t.id)
                in_degree[t.id] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited == len(tasks):
        return []
    return [tid for tid, deg in in_degree.items() if deg > 0]


def _find_components(tasks: List[TaskSpec], task_ids: Set[str]) -> List[Set[str]]:
    """Find connected components (treating dep edges as undirected)."""
    adj: Dict[str, Set[str]] = {t.id: set() for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep in task_ids:
                adj[t.id].add(dep)
                adj[dep].add(t.id)

    visited: Set[str] = set()
    components: List[Set[str]] = []

    for t in tasks:
        if t.id in visited:
            continue
        component: Set[str] = set()
        stack = [t.id]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            stack.extend(adj[node] - visited)
        components.append(component)

    return components


# ---------------------------------------------------------------------------
# 2. Field completeness
# ---------------------------------------------------------------------------

def _check_field_completeness(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for t in plan.tasks:
        if not t.claimed_paths:
            issues.append(ValidationIssue(
                code="E_MISSING_CLAIMED_PATHS",
                severity="error",
                message=f"task '{t.id}' has no claimed_paths",
                task_ids=[t.id],
            ))

        if t.verification is None:
            issues.append(ValidationIssue(
                code="E_MISSING_VERIFICATION",
                severity="error",
                message=f"task '{t.id}' has no verification defined",
                task_ids=[t.id],
            ))

        if not t.acceptance_criteria:
            issues.append(ValidationIssue(
                code="W_EMPTY_ACCEPTANCE",
                severity="warning",
                message=f"task '{t.id}' has no acceptance_criteria",
                task_ids=[t.id],
            ))

        # Global write claim warning
        ws = _normalize_write_set(t.claimed_paths)
        if "/" in ws and len(plan.tasks) > 1:
            issues.append(ValidationIssue(
                code="W_GLOBAL_WRITE_CLAIM",
                severity="warning",
                message=f"task '{t.id}' claims global write ('/') — blocks all parallel tasks",
                task_ids=[t.id],
            ))

    return issues


# ---------------------------------------------------------------------------
# 3. Verification strength
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


# ---------------------------------------------------------------------------
# 4. Contract matching (provides / consumes)
# ---------------------------------------------------------------------------

def _check_contracts(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    # Build provider map: name -> (task_id, contract)
    providers: Dict[str, List[Tuple[str, str]]] = {}  # name -> [(task_id, kind)]
    for t in plan.tasks:
        for c in t.provides:
            providers.setdefault(c.name, []).append((t.id, c.kind))

    # Check consumers
    for t in plan.tasks:
        for c in t.consumes:
            if c.name not in providers:
                issues.append(ValidationIssue(
                    code="E_CONSUMER_WITHOUT_PROVIDER",
                    severity="error",
                    message=f"task '{t.id}' consumes '{c.name}' but no task provides it",
                    task_ids=[t.id],
                    evidence={"contract_name": c.name},
                ))
            # Check from_task reference
            if c.from_task:
                task_ids = {tt.id for tt in plan.tasks}
                if c.from_task not in task_ids:
                    issues.append(ValidationIssue(
                        code="E_CONSUMER_FROM_UNKNOWN",
                        severity="error",
                        message=f"task '{t.id}' consumes '{c.name}' from unknown task '{c.from_task}'",
                        task_ids=[t.id],
                        evidence={"contract_name": c.name, "from_task": c.from_task},
                    ))

    # Unused providers (hint, not error)
    consumed_names = set()
    for t in plan.tasks:
        for c in t.consumes:
            consumed_names.add(c.name)

    for name, provider_list in providers.items():
        if name not in consumed_names:
            task_ids = [tid for tid, _ in provider_list]
            issues.append(ValidationIssue(
                code="W_PROVIDER_UNUSED",
                severity="hint",
                message=f"contract '{name}' is provided but never consumed",
                task_ids=task_ids,
                evidence={"contract_name": name},
            ))

    return issues


# ---------------------------------------------------------------------------
# 5. Critical entrypoints & flows coverage
# ---------------------------------------------------------------------------

def _check_critical_coverage(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    # All claimed paths across all tasks
    all_claimed: Set[str] = set()
    for t in plan.tasks:
        for p in _normalize_write_set(t.claimed_paths):
            all_claimed.add(p)

    # Check critical entrypoints are owned
    for ep in plan.critical_entrypoints:
        ep_norm = ep.strip().replace("\\", "/")
        owned = any(_paths_overlap(ep_norm, cp) for cp in all_claimed)
        if not owned:
            issues.append(ValidationIssue(
                code="E_CRITICAL_ENTRYPOINT_UNOWNED",
                severity="error",
                message=f"critical entrypoint '{ep}' is not claimed by any task",
                evidence={"path": ep},
            ))

    # Check critical flows
    all_covered_flows: Set[str] = set()
    for t in plan.tasks:
        if t.verification:
            all_covered_flows.update(t.verification.covers.flows)

    for flow in plan.critical_flows:
        if flow.id not in all_covered_flows:
            issues.append(ValidationIssue(
                code="E_CRITICAL_FLOW_UNCOVERED",
                severity="error",
                message=f"critical flow '{flow.id}' is not covered by any task's verification",
                evidence={"flow_id": flow.id},
            ))

        # Check entrypoints of this flow are owned
        for ep in flow.entrypoints:
            ep_norm = ep.strip().replace("\\", "/")
            owned = any(_paths_overlap(ep_norm, cp) for cp in all_claimed)
            if not owned:
                issues.append(ValidationIssue(
                    code="E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED",
                    severity="error",
                    message=f"entrypoint '{ep}' of critical flow '{flow.id}' is not claimed by any task",
                    evidence={"flow_id": flow.id, "path": ep},
                ))

    return issues


# ---------------------------------------------------------------------------
# 6. Contract ↔ dependency alignment
# ---------------------------------------------------------------------------

def _check_contract_dep_alignment(plan: Plan) -> List[ValidationIssue]:
    """Check that consumes edges align with depends_on edges."""
    issues: List[ValidationIssue] = []
    task_map = {t.id: t for t in plan.tasks}

    for t in plan.tasks:
        dep_set = set(t.depends_on)
        consume_sources = set()
        for c in t.consumes:
            if c.from_task:
                consume_sources.add(c.from_task)

        # consumes from a task not in depends_on
        for src in consume_sources:
            if src not in dep_set and src in task_map:
                issues.append(ValidationIssue(
                    code="W_CONSUME_WITHOUT_DEP",
                    severity="warning",
                    message=f"task '{t.id}' consumes from '{src}' but does not depend on it",
                    task_ids=[t.id, src],
                ))

        # depends_on a task that provides something, but no consume declared
        if t.consumes:  # only check if task uses contracts at all
            for dep_id in t.depends_on:
                dep_task = task_map.get(dep_id)
                if dep_task and dep_task.provides and dep_id not in consume_sources:
                    issues.append(ValidationIssue(
                        code="W_DEP_WITHOUT_CONSUME",
                        severity="hint",
                        message=f"task '{t.id}' depends on '{dep_id}' which provides contracts, "
                                f"but does not consume any of them",
                        task_ids=[t.id, dep_id],
                    ))

    return issues


# ---------------------------------------------------------------------------
# 7. Critical flow verification level check
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
# 8. Issue coverage — required_issues must be addressed
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
# 9. Verification ↔ goal behavior mismatch
# ---------------------------------------------------------------------------

# Keywords in goal_behavior that imply runtime/integration behavior
_RUNTIME_KEYWORDS = {
    "trigger", "state advance", "state transition", "end-to-end", "verify gate",
    "initialize", "instantiate", "daemon", "startup", "cold start", "lazy-init",
    "event chain", "ipc", "reachable", "connected",
}


def _check_verification_behavior_match(plan: Plan) -> List[ValidationIssue]:
    """Warn when goal implies runtime behavior but verification is static grep/compile."""
    issues: List[ValidationIssue] = []

    for t in plan.tasks:
        v = t.verification
        if v is None:
            continue
        if v.level in ("integration", "e2e"):
            continue  # already strong enough level

        goal_lower = (t.goal_behavior + " " + t.acceptance_criteria).lower()
        has_runtime_keyword = any(kw in goal_lower for kw in _RUNTIME_KEYWORDS)

        if has_runtime_keyword:
            issues.append(ValidationIssue(
                code="W_VERIFICATION_BEHAVIOR_MISMATCH",
                severity="warning",
                message=f"task '{t.id}' goal implies runtime behavior but "
                        f"verification is only {v.level}-level",
                task_ids=[t.id],
                evidence={"verification_level": v.level},
            ))

    return issues


# ---------------------------------------------------------------------------
# 10. Forbidden flows — anti-bypass declarations
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


# ---------------------------------------------------------------------------
# 11. Implicit serialization warning
# ---------------------------------------------------------------------------

def _check_implicit_serialization(plan: Plan) -> List[ValidationIssue]:
    """Warn when two tasks share claimed_paths but have no explicit depends_on."""
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    # Build pairs that share write-set overlap
    reported: Set[frozenset] = set()
    for i, t1 in enumerate(plan.tasks):
        for t2 in plan.tasks[i + 1:]:
            # Skip if they already have explicit dependency
            if t2.id in t1.depends_on or t1.id in t2.depends_on:
                continue

            ws1 = _normalize_write_set(t1.claimed_paths)
            ws2 = _normalize_write_set(t2.claimed_paths)

            if any(_paths_overlap(a, b) for a in ws1 for b in ws2):
                pair = frozenset([t1.id, t2.id])
                if pair not in reported:
                    reported.add(pair)
                    issues.append(ValidationIssue(
                        code="W_IMPLICIT_SERIALIZATION",
                        severity="hint",
                        message=f"tasks '{t1.id}' and '{t2.id}' share claimed_paths but have no "
                                f"explicit depends_on — Ralph will serialize them via write-set conflict",
                        task_ids=[t1.id, t2.id],
                    ))

    return issues


# ---------------------------------------------------------------------------
# 12. Integration spine — cross-boundary glue detection
# ---------------------------------------------------------------------------

def _check_integration_spine(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if len(plan.tasks) <= 1:
        return issues

    task_map = {t.id: t for t in plan.tasks}

    # For each dependency edge, check if there's cross-task verification covering both
    covered_pairs: Set[frozenset] = set()
    for t in plan.tasks:
        if t.verification and t.verification.covers.tasks:
            cover_set = set(t.verification.covers.tasks)
            for a in cover_set:
                for b in cover_set:
                    if a != b:
                        covered_pairs.add(frozenset([a, b]))

    # Check cross-boundary edges without glue
    for t in plan.tasks:
        for dep_id in t.depends_on:
            dep_task = task_map.get(dep_id)
            if dep_task is None:
                continue

            pair = frozenset([t.id, dep_id])
            if pair in covered_pairs:
                continue

            # Check if they're in different path boundaries
            t_ws = _normalize_write_set(t.claimed_paths)
            dep_ws = _normalize_write_set(dep_task.claimed_paths)

            # If write sets don't overlap, they're in different areas — need glue
            if not any(_paths_overlap(a, b) for a in t_ws for b in dep_ws):
                issues.append(ValidationIssue(
                    code="W_CROSS_BOUNDARY_WITHOUT_GLUE",
                    severity="warning",
                    message=f"task '{t.id}' depends on '{dep_id}' across different path boundaries, "
                            f"but no integration/e2e verification covers both",
                    task_ids=[t.id, dep_id],
                    evidence={
                        "consumer_paths": t_ws,
                        "producer_paths": dep_ws,
                    },
                ))

    # Check integration spine exists for plans with >3 tasks
    if len(plan.tasks) > 3:
        has_spine = False
        for t in plan.tasks:
            v = t.verification
            if v and v.level in ("integration", "e2e") and len(v.covers.tasks) >= 2:
                has_spine = True
                break

        if not has_spine:
            issues.append(ValidationIssue(
                code="E_MISSING_INTEGRATION_SPINE",
                severity="error",
                message=f"plan has {len(plan.tasks)} tasks but no task provides integration/e2e "
                        f"verification covering multiple tasks",
                task_ids=[t.id for t in plan.tasks],
            ))

    return issues
