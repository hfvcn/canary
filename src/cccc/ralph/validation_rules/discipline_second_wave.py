"""Second-wave Aegis discipline validation rules."""

from __future__ import annotations

from typing import Any, Iterable, List

from ..models import Plan, ValidationIssue

MULTI_STAGE_MODULE_COUNT = 3
PATCH_SHAPE_TRIAGE_KEYWORDS = ("fallback", "adapter", "guard")
OWNER_PATTERN_KEYWORDS = ("new owner", "duplicate")
SHARED_MODULE_SEGMENTS = frozenset({"shared", "core"})
CONTRACT_MODULE_SEGMENTS = frozenset({"contract", "contracts"})


def check_patch_shape_triage_missing(plan: Plan) -> List[ValidationIssue]:
    """Require triage metadata for fallback/adapter/guard task goals."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        keyword = _matching_keyword(_goal_text(task), PATCH_SHAPE_TRIAGE_KEYWORDS)
        if not keyword or _has_aegis_value(task, "patch_shape_triage"):
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING",
            severity="warning",
            message=f"task '{task.id}' has patch-shape risk without aegis.patch_shape_triage",
            evidence={"keyword": keyword},
        ))
    return issues


def check_ripple_triage_missing(plan: Plan) -> List[ValidationIssue]:
    """Require downstream awareness when shared paths create ripple risk."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        reason = _ripple_risk_reason(plan, task)
        downstream_missing = _missing_downstream_awareness(plan, task)
        if not reason or not downstream_missing:
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_RIPPLE_TRIAGE_MISSING",
            severity="warning",
            message=f"task '{task.id}' has ripple risk without downstream awareness_paths",
            evidence={"reason": reason, "missing_awareness_paths": downstream_missing},
        ))
    return issues


def check_decision_hygiene_missing(plan: Plan) -> List[ValidationIssue]:
    """Require decision review metadata for new-owner/duplicate-owner tasks."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        keyword = _matching_keyword(_goal_text(task), OWNER_PATTERN_KEYWORDS)
        if not keyword or _has_aegis_value(task, "decision_review"):
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_DECISION_HYGIENE_MISSING",
            severity="warning",
            message=f"task '{task.id}' introduces owner-pattern risk without decision_review",
            evidence={"keyword": keyword},
        ))
    return issues


def check_drift_check_missing(plan: Plan) -> List[ValidationIssue]:
    """Require drift checks for multi-stage module decomposition."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        module_count = len(getattr(task, "modules", []) or [])
        if module_count < MULTI_STAGE_MODULE_COUNT:
            continue
        if _has_aegis_value(task, "drift_check"):
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_DRIFT_CHECK_MISSING",
            severity="warning",
            message=f"task '{task.id}' has {module_count} modules without aegis.drift_check",
            evidence={"module_count": module_count},
        ))
    return issues


def check_plan_compat_boundary_missing(plan: Plan) -> List[ValidationIssue]:
    """Require at least one compatibility boundary for cross-task dependency plans."""
    dependencies = _cross_task_dependencies(plan)
    if not dependencies or _plan_has_compat_boundary(plan):
        return []
    return [ValidationIssue(
        code="W_AEGIS_PLAN_NO_COMPAT_BOUNDARY",
        severity="warning",
        message="plan has cross-task dependencies but no task declares aegis.compat_boundary",
        evidence={"dependencies": dependencies},
    )]


def check_ripple_verification_too_narrow(plan: Plan) -> List[ValidationIssue]:
    """Reject self-only verification for contract/shared/core changes."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if not _has_contract_shared_core_path(task):
            continue
        if not _verification_only_covers_self(task):
            continue
        issues.append(_task_issue(
            task=task,
            code="E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW",
            severity="error",
            message=f"task '{task.id}' modifies ripple-prone paths but verification only covers itself",
            evidence={"claimed_paths": list(getattr(task, "claimed_paths", []))},
        ))
    return issues


def _ripple_risk_reason(plan: Plan, task: Any) -> str:
    if _has_shared_or_core_path(task):
        return "shared_or_core_path"
    if _claimed_path_overlaps_other(plan, task):
        return "claimed_by_multiple_tasks"
    return ""


def _missing_downstream_awareness(plan: Plan, task: Any) -> List[str]:
    awareness_paths = _normalized_paths(getattr(task, "awareness_paths", []))
    downstream_paths = _downstream_claimed_paths(plan, str(task.id))
    return [
        path
        for path in downstream_paths
        if not _path_overlaps_any(path, awareness_paths)
    ]


def _downstream_claimed_paths(plan: Plan, task_id: str) -> List[str]:
    paths: List[str] = []
    for task in plan.tasks:
        if task_id not in getattr(task, "depends_on", []):
            continue
        paths.extend(_normalized_paths(getattr(task, "claimed_paths", [])))
    return sorted(set(paths))


def _claimed_path_overlaps_other(plan: Plan, task: Any) -> bool:
    claimed_paths = _normalized_paths(getattr(task, "claimed_paths", []))
    for other in plan.tasks:
        if other.id == task.id:
            continue
        if _path_sets_overlap(claimed_paths, _normalized_paths(other.claimed_paths)):
            return True
    return False


def _has_shared_or_core_path(task: Any) -> bool:
    return any(
        _src_path_has_segment(path, SHARED_MODULE_SEGMENTS)
        for path in getattr(task, "claimed_paths", [])
    )


def _has_contract_shared_core_path(task: Any) -> bool:
    segments = SHARED_MODULE_SEGMENTS | CONTRACT_MODULE_SEGMENTS
    return any(
        _src_path_has_segment(path, segments)
        for path in getattr(task, "claimed_paths", [])
    )


def _verification_only_covers_self(task: Any) -> bool:
    verification = getattr(task, "verification", None)
    covers = getattr(verification, "covers", None) if verification else None
    if not covers:
        return False
    covered_tasks = set(getattr(covers, "tasks", []) or [])
    has_other_coverage = bool(
        getattr(covers, "paths", []) or getattr(covers, "flows", [])
    )
    return covered_tasks == {task.id} and not has_other_coverage


def _cross_task_dependencies(plan: Plan) -> List[str]:
    task_ids = {task.id for task in plan.tasks}
    dependencies: List[str] = []
    for task in plan.tasks:
        for dependency in task.depends_on:
            if dependency in task_ids and dependency != task.id:
                dependencies.append(f"{task.id}->{dependency}")
    return sorted(dependencies)


def _plan_has_compat_boundary(plan: Plan) -> bool:
    return any(_has_aegis_value(task, "compat_boundary") for task in plan.tasks)


def _matching_keyword(text: str, keywords: Iterable[str]) -> str:
    return next((keyword for keyword in keywords if keyword in text), "")


def _goal_text(task: Any) -> str:
    return str(getattr(task, "goal_behavior", "") or "").casefold()


def _has_aegis_value(task: Any, key: str) -> bool:
    value = _aegis_value(task, key)
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _aegis_value(task: Any, key: str) -> Any:
    aegis = getattr(task, "aegis", None)
    if isinstance(aegis, dict):
        return aegis.get(key)
    if aegis is None:
        return None
    return getattr(aegis, key, None)


def _src_path_has_segment(path: str, target_segments: frozenset[str]) -> bool:
    parts = _normalize_path(path).split("/")
    if not parts or parts[0] != "src":
        return False
    return any(part in target_segments for part in parts[1:-1])


def _path_sets_overlap(left_paths: List[str], right_paths: List[str]) -> bool:
    return any(
        _paths_overlap(left, right)
        for left in left_paths
        for right in right_paths
    )


def _path_overlaps_any(path: str, candidates: List[str]) -> bool:
    return any(_paths_overlap(path, candidate) for candidate in candidates)


def _normalized_paths(paths: Iterable[str]) -> List[str]:
    return [_normalize_path(path) for path in paths if str(path or "").strip()]


def _normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def _paths_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return (
        left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


def _task_issue(
    *,
    task: Any,
    code: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        task_ids=[task.id],
        evidence=evidence,
    )
