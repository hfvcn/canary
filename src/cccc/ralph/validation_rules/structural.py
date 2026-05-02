"""Structural validation rules — graph, dependency, field, and integration spine checks.

Extracted from validator.py as a pure refactor (RO-31).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from cccc.kernel.claimed_paths import normalize_write_set as _normalize_write_set, paths_overlap as _paths_overlap
from ..graph_utils import transitive_deps, detect_cycle, find_components
from ..models import (
    Plan,
    TaskSpec,
    Verification,
    ValidationIssue,
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
    cycle = detect_cycle(plan.tasks, task_ids)
    if cycle:
        issues.append(ValidationIssue(
            code="E_DEP_CYCLE",
            severity="error",
            message=f"dependency cycle detected involving: {', '.join(cycle)}",
            task_ids=list(cycle),
        ))

    # Disconnected components (warning if >1 and plan has >1 task)
    if len(plan.tasks) > 1:
        components = find_components(plan.tasks, task_ids)
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


# ---------------------------------------------------------------------------
# 2. covers.tasks graph
# ---------------------------------------------------------------------------

def _check_covers_graph(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        verification = task.verification
        if verification is None:
            continue

        for covered_id in verification.covers.tasks:
            if covered_id not in task_map:
                issues.append(ValidationIssue(
                    code="E_COVERS_UNKNOWN_TASK",
                    severity="error",
                    message=f"task '{task.id}' covers unknown task '{covered_id}'",
                    task_ids=[task.id],
                ))
                continue

            if covered_id == task.id:
                continue

            if covered_id not in transitive_deps(task.id, task_map):
                issues.append(ValidationIssue(
                    code="E_COVERS_WITHOUT_DEP_ORDER",
                    severity="error",
                    message=f"task '{task.id}' covers '{covered_id}' but '{covered_id}' "
                            f"is not in its transitive dependency closure",
                    task_ids=[task.id, covered_id],
                ))

    return issues


# ---------------------------------------------------------------------------
# 3. Field completeness
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

        # RA-3: unknown verification_mode
        _valid_modes = {"ralph", "agent", "challenge"}
        if hasattr(t, "verification_mode") and t.verification_mode not in _valid_modes:
            issues.append(ValidationIssue(
                code="W_UNKNOWN_VERIFICATION_MODE",
                severity="warning",
                message=f"task '{t.id}' has unknown verification_mode '{t.verification_mode}'",
                task_ids=[t.id],
                evidence={"task_id": t.id, "verification_mode": t.verification_mode},
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
# 12. Implicit serialization warning
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


def _check_shared_file_verification(plan: Plan) -> List[ValidationIssue]:
    """Hint when two dependent tasks share files but neither verification tests them."""
    issues: List[ValidationIssue] = []
    if len(plan.tasks) < 2:
        return issues

    task_map = {t.id: t for t in plan.tasks}
    reported: Set[frozenset] = set()

    for t1 in plan.tasks:
        for dep_id in t1.depends_on:
            t2 = task_map.get(dep_id)
            if t2 is None:
                continue

            ws1 = _normalize_write_set(t1.claimed_paths)
            ws2 = _normalize_write_set(t2.claimed_paths)
            shared = [p1 for p1 in ws1 for p2 in ws2 if _paths_overlap(p1, p2)]
            if not shared:
                continue

            pair = frozenset([t1.id, t2.id])
            if pair in reported:
                continue

            v1 = t1.verification
            v2 = t2.verification
            if v1 is None or v2 is None:
                continue

            cmd1 = v1.command
            cmd2 = v2.command
            if _command_mentions_any_path(cmd1, shared) or _command_mentions_any_path(cmd2, shared):
                continue

            reported.add(pair)
            issues.append(ValidationIssue(
                code="W_SHARED_FILE_PARTIAL_VERIFICATION",
                severity="hint",
                message=f"tasks '{t1.id}' and '{t2.id}' share paths but neither verification mentions them",
                task_ids=[t1.id, t2.id],
                evidence={"shared_paths": shared},
            ))

    return issues


# ---------------------------------------------------------------------------
# 13. Integration spine — cross-boundary glue detection
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


def _check_role_constraints(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for task in plan.tasks:
        verification = task.verification

        if task.role == "integration" and not _is_cross_task_verifier(verification):
            verification_level = verification.level if verification else None
            covered_tasks_count = len(verification.covers.tasks) if verification else 0
            issues.append(ValidationIssue(
                code="W_INTEGRATION_ROLE_WEAK_VERIFICATION",
                severity="warning",
                message=f"task '{task.id}' has role='integration' but lacks integration/e2e "
                        f"verification covering at least 2 tasks",
                task_ids=[task.id],
                evidence={
                    "verification_level": verification_level,
                    "covered_tasks_count": covered_tasks_count,
                },
            ))

        if task.role == "verification":
            covered_tasks = verification.covers.tasks if verification else []
            if not covered_tasks:
                issues.append(ValidationIssue(
                    code="W_VERIFICATION_ROLE_NO_COVERS",
                    severity="warning",
                    message=f"task '{task.id}' has role='verification' but no verification covers.tasks",
                    task_ids=[task.id],
                ))

            offending_path = next(
                (
                    path for path in task.claimed_paths
                    if not path.startswith("tests/") and not path.startswith("test_")
                ),
                None,
            )
            if offending_path is not None:
                issues.append(ValidationIssue(
                    code="W_VERIFICATION_ROLE_CLAIMS_SOURCE",
                    severity="warning",
                    message=f"task '{task.id}' has role='verification' but claims source path "
                            f"'{offending_path}'",
                    task_ids=[task.id],
                    evidence={"offending_path": offending_path},
                ))

        if task.role == "leaf" and _is_cross_task_verifier(verification):
            issues.append(ValidationIssue(
                code="W_LEAF_ROLE_IS_INTEGRATOR",
                severity="warning",
                message=f"task '{task.id}' has role='leaf' but provides integration/e2e "
                        f"verification covering multiple tasks",
                task_ids=[task.id],
                evidence={
                    "verification_level": verification.level,
                    "covered_tasks_count": len(verification.covers.tasks),
                },
            ))

    return issues


def _check_early_integration_checkpoint(plan: Plan) -> List[ValidationIssue]:
    if len(plan.tasks) < 5:
        return []

    verifier_ids = [task.id for task in plan.tasks if _is_cross_task_verifier(task.verification)]
    if not verifier_ids:
        return []

    dependents = _dependent_map(plan.tasks)
    if any(dependents.get(task_id) for task_id in verifier_ids):
        return []

    depths = _task_depths(plan.tasks)
    if not depths:
        return []

    max_depth = max(depths.values())
    if max_depth <= 0:
        return []

    min_depth = min(depths.get(task_id, 0) for task_id in verifier_ids)
    depth_ratio = min_depth / max_depth
    if depth_ratio < 0.5:
        return []

    return [ValidationIssue(
        code="W_NO_EARLY_INTEGRATION_CHECKPOINT",
        severity="warning",
        message="all cross-task integration/e2e verifiers are sink tasks and appear late in the graph",
        task_ids=verifier_ids,
        evidence={"min_depth": min_depth, "max_depth": max_depth, "depth_ratio": depth_ratio},
    )]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _command_mentions_any_path(command: str, claimed_paths: List[str]) -> bool:
    return any(path and path in command for path in claimed_paths)


def _task_depths(tasks: List[TaskSpec]) -> Dict[str, int]:
    dependents = _dependent_map(tasks)
    roots = [task.id for task in tasks if not task.depends_on]
    depths = {task_id: 0 for task_id in roots}
    queue = list(roots)

    while queue:
        task_id = queue.pop(0)
        next_depth = depths[task_id] + 1
        for dependent_id in dependents.get(task_id, []):
            if next_depth <= depths.get(dependent_id, -1):
                continue
            depths[dependent_id] = next_depth
            queue.append(dependent_id)

    return depths


def _dependent_map(tasks: List[TaskSpec]) -> Dict[str, List[str]]:
    dependents: Dict[str, List[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dep_id in task.depends_on:
            if dep_id in dependents:
                dependents[dep_id].append(task.id)
    return dependents


def _is_cross_task_verifier(verification: Verification | None) -> bool:
    return bool(
        verification
        and verification.level in ("integration", "e2e")
        and len(verification.covers.tasks) >= 2
    )
