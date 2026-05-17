"""Security recipe hints for declared critical-flow surfaces."""

from __future__ import annotations

from typing import Any, List

from .models import CriticalFlow, Plan, TaskSpec, ValidationIssue


SECURITY_RECIPES: dict[str, dict[str, Any]] = {
    "url_input": {
        "issue_code": "W_SSRF_ENCODING_UNCOVERED",
        "keywords": ("ssrf", "url_validation", "url validation", "url input"),
        "hostname_encoding_matrix": [
            "0177.0.0.1",
            "2130706433",
            "0x7f000001",
            "::ffff:127.0.0.1",
            "::1",
        ],
        "coverage_terms": (
            "encoding matrix",
            "encoded ip",
            "hostname matrix",
            "0177.0.0.1",
            "2130706433",
            "0x7f000001",
            "::ffff:127.0.0.1",
            "::1",
        ),
    },
    "auth_token": {
        "issue_code": "W_AUTH_TIMING_UNSAFE",
        "keywords": ("auth", "token"),
        "timing_safe_compare_patterns": {
            "python": "secrets.compare_digest",
            "node": "crypto.timingSafeEqual",
            "go": "subtle.ConstantTimeCompare",
        },
        "coverage_terms": (
            "compare_digest",
            "timingsafeequal",
            "constanttimecompare",
            "timing-safe",
            "timing safe",
            "constant-time",
            "constant time",
        ),
    },
    "temporal:store_then_use": {
        "issue_code": "W_VERIFICATION_TOCTOU_GAP",
        "keywords": ("temporal", "toctou", "store_then_use"),
        "temporal_pattern": "store_then_use",
        "toctou_test_templates": [
            "store accepted value, mutate backing state, then use stored value",
            "store path or URL, swap target before use, then assert revalidation",
        ],
        "coverage_terms": (
            "toctou",
            "store_then_use",
            "store then use",
            "temporal",
        ),
    },
}


def check_security_recipes(plan: Plan, task: TaskSpec) -> List[ValidationIssue]:
    """Return security-recipe hints for one task when all gates match."""
    issues: List[ValidationIssue] = []
    for flow in _relevant_flows(plan, task):
        for surface_type, recipe in SECURITY_RECIPES.items():
            if not _all_gates_match(flow, task, surface_type, recipe):
                continue
            issues.append(_build_issue(task, flow, surface_type, recipe))
    return issues


def _relevant_flows(plan: Plan, task: TaskSpec) -> List[CriticalFlow]:
    return [
        flow
        for flow in plan.critical_flows
        if _task_relevant_to_flow(plan, task, flow)
    ]


def _task_relevant_to_flow(plan: Plan, task: TaskSpec, flow: CriticalFlow) -> bool:
    verification = task.verification
    if verification and flow.id in verification.covers.flows:
        return True
    if task.id in flow.test_created_by:
        return True
    if _flow_entrypoint_owned_by_task(flow, task):
        return True
    return len(plan.tasks) == 1 and verification is not None


def _all_gates_match(
    flow: CriticalFlow,
    task: TaskSpec,
    surface_type: str,
    recipe: dict[str, Any],
) -> bool:
    return (
        _flow_has_security_keyword(flow, recipe)
        and _flow_declares_recipe(flow, surface_type)
        and not _task_has_recipe_coverage(task, recipe)
    )


def _flow_has_security_keyword(flow: CriticalFlow, recipe: dict[str, Any]) -> bool:
    if recipe.get("temporal_pattern") and _flow_temporal_pattern(flow):
        return True
    text = " ".join([flow.id, flow.description]).casefold()
    return any(str(keyword).casefold() in text for keyword in recipe["keywords"])


def _flow_declares_recipe(flow: CriticalFlow, surface_type: str) -> bool:
    declared_surface = _normalized(getattr(flow, "surface_type", None))
    if declared_surface == _normalized(surface_type):
        return True
    if not surface_type.startswith("temporal:"):
        return False
    expected_temporal = surface_type.removeprefix("temporal:")
    return _normalized(_flow_temporal_pattern(flow)) == _normalized(expected_temporal)


def _task_has_recipe_coverage(task: TaskSpec, recipe: dict[str, Any]) -> bool:
    verification = task.verification
    if verification is None or not verification.checks:
        return False
    check_text = " ".join(
        f"{check.name} {check.command}" for check in verification.checks
    ).casefold()
    return any(term in check_text for term in _coverage_terms(recipe))


def _coverage_terms(recipe: dict[str, Any]) -> List[str]:
    terms = [str(term).casefold() for term in recipe.get("coverage_terms", ())]
    return [term for term in terms if term]


def _build_issue(
    task: TaskSpec,
    flow: CriticalFlow,
    surface_type: str,
    recipe: dict[str, Any],
) -> ValidationIssue:
    return ValidationIssue(
        code=str(recipe["issue_code"]),
        severity="hint",
        message=(
            f"task '{task.id}' verification lacks {surface_type} security "
            f"recipe coverage for critical flow '{flow.id}'"
        ),
        task_ids=[task.id],
        evidence=_issue_evidence(task, flow, surface_type, recipe),
    )


def _issue_evidence(
    task: TaskSpec,
    flow: CriticalFlow,
    surface_type: str,
    recipe: dict[str, Any],
) -> dict[str, Any]:
    verification = task.verification
    check_names = [check.name for check in verification.checks] if verification else []
    evidence = {
        "flow_id": flow.id,
        "surface_type": surface_type,
        "check_names": check_names,
    }
    for key in _recipe_evidence_keys(recipe):
        evidence[key] = recipe[key]
    return evidence


def _recipe_evidence_keys(recipe: dict[str, Any]) -> List[str]:
    keys = [
        "hostname_encoding_matrix",
        "timing_safe_compare_patterns",
        "toctou_test_templates",
        "temporal_pattern",
    ]
    return [key for key in keys if key in recipe]


def _flow_temporal_pattern(flow: CriticalFlow) -> str:
    return str(getattr(flow, "temporal_pattern", "") or "")


def _flow_entrypoint_owned_by_task(flow: CriticalFlow, task: TaskSpec) -> bool:
    task_paths = list(task.claimed_paths) + list(task.awareness_paths)
    for entrypoint in flow.entrypoints:
        if any(_paths_overlap(entrypoint, task_path) for task_path in task_paths):
            return True
    return False


def _paths_overlap(left: str, right: str) -> bool:
    left_path = _normalized_path(left)
    right_path = _normalized_path(right)
    if not left_path or not right_path:
        return False
    return (
        left_path == right_path
        or left_path.startswith(f"{right_path.rstrip('/')}/")
        or right_path.startswith(f"{left_path.rstrip('/')}/")
    )


def _normalized(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalized_path(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")
