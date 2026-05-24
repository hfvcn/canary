"""Aegis discipline validation rules."""

from __future__ import annotations

import re
from typing import Any, Callable, List

from ..aegis import effective_intent
from ..models import Plan, ValidationIssue
from .discipline_security import _check_aegis_security_chain, _check_fts_cjk_coverage, _check_silent_degradation_pattern, _check_ssrf_route_binding
from .discipline_second_wave import (
    check_decision_hygiene_missing,
    check_drift_check_missing,
    check_patch_shape_triage_missing,
    check_plan_compat_boundary_missing,
    check_ripple_triage_missing,
    check_ripple_verification_too_narrow,
)

DisciplineRule = Callable[[Plan], List[ValidationIssue]]

PLACEHOLDER_TOKENS = (
    "tbd",
    "todo",
    "placeholder",
    "fill in",
    "implement later",
)
PLACEHOLDER_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(token)}\b(?![/\\.\-])" for token in PLACEHOLDER_TOKENS),
    re.IGNORECASE,
)
CODE_FENCE_PATTERN = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.DOTALL)
TEST_PATH_MARKERS = ("test_", "_test", "tests/")
COMPLEX_DEPENDENCY_COUNT = 3
RETIREMENT_INTENTS = ("refactor", "migration")
RETIREMENT_SHAPE_KEYWORDS = ("fallback", "adapter", "provider")

# RL-22/RL-25 are known limitations: agent-runtime judgment and dynamic
# execution behavior are out of scope for static plan analysis here.


def collect_discipline_issues(plan: Plan) -> List[ValidationIssue]:
    """Run registered Aegis discipline rules for the plan."""
    issues: List[ValidationIssue] = []
    for rule in _DISCIPLINE_RULES:
        issues.extend(rule(plan))
    return issues


def _check_placeholder_content(plan: Plan) -> List[ValidationIssue]:
    """Flag placeholder wording in task outcome fields."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        field_name = _placeholder_field(task)
        if not field_name:
            continue
        issues.append(_task_issue(
            task=task,
            code="E_AEGIS_PLACEHOLDER_CONTENT",
            severity="error",
            message=f"task '{task.id}' contains placeholder content in {field_name}",
            evidence={"field": field_name},
        ))
    return issues


def _check_retirement_track(plan: Plan) -> List[ValidationIssue]:
    """Require retirement metadata for risky refactor patch shapes."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        intent = effective_intent(task)
        if intent not in RETIREMENT_INTENTS:
            continue
        if not _has_retirement_shape(task):
            continue
        if _aegis_value(task, "retirement_track") is not None:
            continue
        issues.append(_task_issue(
            task=task,
            code="E_AEGIS_RETIREMENT_TRACK_MISSING",
            severity="error",
            message=f"{intent} task '{task.id}' has patch-shape risk without retirement_track",
            evidence={"intent": intent},
        ))
    return issues


def _check_fix_repair_track(plan: Plan) -> List[ValidationIssue]:
    """Require repair metadata for fix tasks."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if effective_intent(task) != "fix":
            continue
        if _repair_root_cause(task):
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_FIX_NO_REPAIR_TRACK",
            severity="warning",
            message=f"fix task '{task.id}' has no repair_track",
            evidence={"intent": "fix"},
        ))
    return issues


def _check_tdd_test_path(plan: Plan) -> List[ValidationIssue]:
    """Require fix/feature tasks to claim a test path."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        intent = effective_intent(task)
        if intent not in ("fix", "feature"):
            continue
        if _has_claimed_test_path(task.claimed_paths):
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_TDD_NO_TEST_PATH",
            severity="warning",
            message=f"{intent} task '{task.id}' claims no test path",
            evidence={"claimed_paths": list(task.claimed_paths)},
        ))
    return issues


def _check_complex_baseline(plan: Plan) -> List[ValidationIssue]:
    """Require baseline references for tasks with integration-level complexity."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        reason = _complex_reason(plan, task)
        if reason is None:
            continue
        if _aegis_value(task, "baseline_refs"):
            continue
        issues.append(_task_issue(
            task=task,
            code="W_AEGIS_COMPLEX_MISSING_BASELINE",
            severity="warning",
            message=f"complex task '{task.id}' has no aegis.baseline_refs",
            evidence={"reason": reason},
        ))
    return issues


_DISCIPLINE_RULES: List[DisciplineRule] = [
    _check_placeholder_content,
    _check_retirement_track,
    _check_fix_repair_track,
    _check_tdd_test_path,
    _check_complex_baseline,
    check_patch_shape_triage_missing,
    check_ripple_triage_missing,
    check_decision_hygiene_missing,
    check_drift_check_missing,
    check_plan_compat_boundary_missing,
    check_ripple_verification_too_narrow,
    _check_aegis_security_chain,
    _check_ssrf_route_binding,
    _check_fts_cjk_coverage,
    _check_silent_degradation_pattern,
]
DISCIPLINE_CHECKS: tuple[DisciplineRule, ...] = tuple(_DISCIPLINE_RULES)


def _check_aegis_discipline(plan: Plan) -> List[ValidationIssue]:
    """Backward-compatible entrypoint for registered discipline checks."""
    return collect_discipline_issues(plan)


def _placeholder_field(task: Any) -> str:
    fields = {
        "title": getattr(task, "title", ""),
        "goal_behavior": getattr(task, "goal_behavior", ""),
        "acceptance_criteria": getattr(task, "acceptance_criteria", ""),
    }
    for field_name, value in fields.items():
        if _contains_placeholder(str(value or "")):
            return field_name
    return ""


def _contains_placeholder(value: str) -> bool:
    return PLACEHOLDER_PATTERN.search(_without_code_fences(value)) is not None


def _without_code_fences(value: str) -> str:
    return CODE_FENCE_PATTERN.sub("", value)


def _has_claimed_test_path(paths: List[str]) -> bool:
    normalized_paths = [path.replace("\\", "/").casefold() for path in paths]
    return any(
        marker in path
        for path in normalized_paths
        for marker in TEST_PATH_MARKERS
    )


def _has_retirement_shape(task: Any) -> bool:
    text = _task_text(task)
    return any(keyword in text for keyword in RETIREMENT_SHAPE_KEYWORDS)


def _task_text(task: Any) -> str:
    fields = (
        getattr(task, "title", ""),
        getattr(task, "goal_behavior", ""),
        getattr(task, "acceptance_criteria", ""),
    )
    return "\n".join(str(field or "") for field in fields).casefold()


def _repair_root_cause(task: Any) -> str:
    repair_track = _aegis_value(task, "repair_track")
    if repair_track is None:
        return ""
    if isinstance(repair_track, dict):
        return str(repair_track.get("root_cause") or "").strip()
    return str(getattr(repair_track, "root_cause", "") or "").strip()


def _complex_reason(plan: Plan, task: Any) -> str | None:
    if len(getattr(task, "depends_on", [])) >= COMPLEX_DEPENDENCY_COUNT:
        return "depends_on>=3"
    if getattr(task, "provides", []):
        return "contracts"
    if getattr(task, "consumes", []):
        return "contracts"
    if _task_critical_flow_ids(plan, task):
        return "critical_flows"
    return None


def _task_critical_flow_ids(plan: Plan, task: Any) -> List[str]:
    if not plan.critical_flows:
        return []
    covered_ids = _verification_flow_ids(task)
    if covered_ids:
        declared_ids = {flow.id for flow in plan.critical_flows}
        return sorted(flow_id for flow_id in covered_ids if flow_id in declared_ids)
    return [
        flow.id
        for flow in plan.critical_flows
        if _flow_entrypoint_matches_task(flow, task)
    ]


def _verification_flow_ids(task: Any) -> List[str]:
    verification = getattr(task, "verification", None)
    covers = getattr(verification, "covers", None) if verification else None
    return list(getattr(covers, "flows", []) if covers else [])


def _flow_entrypoint_matches_task(flow: Any, task: Any) -> bool:
    claimed_paths = [
        path.replace("\\", "/").rstrip("/")
        for path in getattr(task, "claimed_paths", [])
    ]
    entrypoints = [entry.replace("\\", "/").rstrip("/") for entry in flow.entrypoints]
    return any(
        _paths_overlap(entrypoint, claimed_path)
        for entrypoint in entrypoints
        for claimed_path in claimed_paths
    )


def _paths_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return (
        left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


def _aegis_value(task: Any, key: str) -> Any:
    aegis = getattr(task, "aegis", None)
    if isinstance(aegis, dict):
        return aegis.get(key)
    if aegis is None:
        return None
    return getattr(aegis, key, None)


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
