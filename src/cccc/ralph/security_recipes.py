"""Security recipe hints for declared critical-flow surfaces."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, List

from .models import CriticalFlow, Plan, TaskSpec, ValidationIssue


HOSTNAME_ENCODING_MATRIX = [
    "0177.0.0.1",
    "2130706433",
    "0x7f000001",
    "[::ffff:127.0.0.1]",
    "[::1]",
]
TOCTOU_TEST_TEMPLATES = [
    "phase 1: store accepted value; phase 2: mutate backing state before use",
    "phase 1: store path or URL; phase 2: swap target and assert revalidation",
    "phase 1: barrier.wait() to synchronize revoke and access threads; phase 2: both threads start simultaneously, assert no stale reads",
]
AUTH_RECIPE_SURFACE_TYPES = ("auth_token", "token_type_confusion")
TIMING_SAFE_COMPARE = "secrets.compare_digest"
TOKEN_NAME_PATTERN = (
    r"\b(?=[A-Za-z_][A-Za-z0-9_]*\b)"
    r"[A-Za-z0-9_]*(?:auth|token|key)[A-Za-z0-9_]*\b"
)
TOKEN_COMPARE_RE = re.compile(
    rf"(?:{TOKEN_NAME_PATTERN})\s*(?:==|!=)|"
    rf"(?:==|!=)\s*(?:{TOKEN_NAME_PATTERN})",
    re.IGNORECASE,
)


SECURITY_RECIPES: dict[str, dict[str, Any]] = {
    "url_input": {
        "issue_code": "W_SSRF_ENCODING_UNCOVERED",
        "keywords": ("ssrf", "url"),
        "hostname_encoding_matrix": HOSTNAME_ENCODING_MATRIX,
        "coverage_terms": (
            "encoding matrix",
            "hostname matrix",
            *HOSTNAME_ENCODING_MATRIX,
        ),
    },
    "auth_token": {
        "issue_code": "W_AUTH_TIMING_UNSAFE",
        "keywords": ("auth", "token", "key"),
        "timing_safe_compare_patterns": {
            "python": TIMING_SAFE_COMPARE,
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
    "token_type_confusion": {
        "issue_code": "W_TOKEN_TYPE_CONFUSION_UNCOVERED",
        "keywords": ("auth", "token", "oauth", "jwt"),
        "coverage_terms": (
            "token_type",
            "type==access",
            "type confusion",
            "token type",
            "refresh.*access",
            "access.*refresh",
        ),
    },
    "temporal:store_then_use": {
        "issue_code": "W_VERIFICATION_TOCTOU_GAP",
        "keywords": ("temporal", "toctou", "store_then_use"),
        "temporal_pattern": "store_then_use",
        "toctou_test_templates": TOCTOU_TEST_TEMPLATES,
        "two_phase_test_template": TOCTOU_TEST_TEMPLATES,
        "coverage_terms": (
            "toctou",
            "store_then_use",
            "store then use",
            "temporal",
            "barrier",
            "synchronize",
        ),
    },
}


def check_security_recipes(plan: Plan, task: TaskSpec) -> List[ValidationIssue]:
    """Return security-recipe hints for one task when all gates match."""
    issues: List[ValidationIssue] = []
    for flow in _relevant_flows(plan, task):
        for recipe_name in SECURITY_RECIPES:
            if not _recipe_matches(flow, task, recipe_name):
                continue
            issues.append(_build_issue(task, flow, recipe_name))
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


def _recipe_matches(flow: CriticalFlow, task: TaskSpec, recipe_name: str) -> bool:
    recipe = SECURITY_RECIPES[recipe_name]
    if recipe_name == "temporal:store_then_use":
        return bool(_flow_temporal_pattern(flow))
    if recipe_name == "url_input":
        return _url_recipe_matches(flow, task, recipe)
    if recipe_name == "auth_token":
        return _auth_recipe_matches(flow, task, recipe)
    if recipe_name == "token_type_confusion":
        return _token_type_recipe_matches(flow, task, recipe)
    return False


def _url_recipe_matches(
    flow: CriticalFlow,
    task: TaskSpec,
    recipe: dict[str, Any],
) -> bool:
    return _flow_has_security_keyword(flow, recipe) and not _url_input_is_covered(task)


def _auth_recipe_matches(
    flow: CriticalFlow,
    task: TaskSpec,
    recipe: dict[str, Any],
) -> bool:
    return _flow_has_security_keyword(flow, recipe) and bool(
        _unsafe_auth_compare_paths(task)
    )


def _token_type_recipe_matches(
    flow: CriticalFlow,
    task: TaskSpec,
    recipe: dict[str, Any],
) -> bool:
    return (
        (_flow_has_security_keyword(flow, recipe) or _flow_has_auth_surface_type(flow))
        and _flow_has_token_type_context(flow, task, recipe)
        and not _task_has_recipe_coverage(task, recipe)
    )


def _flow_has_security_keyword(flow: CriticalFlow, recipe: dict[str, Any]) -> bool:
    text = _flow_security_text(flow)
    return any(str(keyword).casefold() in text for keyword in recipe["keywords"])


def _flow_security_text(flow: CriticalFlow) -> str:
    return " ".join([flow.id, flow.description]).casefold()


def _flow_has_auth_surface_type(flow: CriticalFlow) -> bool:
    surface_type = str(getattr(flow, "surface_type", "") or "")
    return surface_type in AUTH_RECIPE_SURFACE_TYPES


def _task_has_recipe_coverage(task: TaskSpec, recipe: dict[str, Any]) -> bool:
    return _text_has_coverage_terms(_verification_check_text(task), recipe)


def _verification_check_text(task: TaskSpec) -> str:
    verification = task.verification
    if verification is None or not verification.checks:
        return ""
    return " ".join(
        f"{check.name} {check.command}" for check in verification.checks
    ).casefold()


def _missing_encoding_entries(task: TaskSpec) -> List[str]:
    check_text = _verification_check_text(task)
    return [
        entry
        for entry in HOSTNAME_ENCODING_MATRIX
        if entry.casefold() not in check_text
    ]


def _url_input_is_covered(task: TaskSpec) -> bool:
    check_text = _verification_check_text(task)
    if any(term in check_text for term in ("encoding matrix", "hostname matrix")):
        return True
    return not _missing_encoding_entries(task)


def _resolve_recipe_severity(task: TaskSpec, recipe_name: str) -> str:
    if recipe_name != "url_input":
        return "hint"
    if len(_missing_encoding_entries(task)) == len(HOSTNAME_ENCODING_MATRIX):
        return "warning"
    return "hint"


def _coverage_terms(recipe: dict[str, Any]) -> List[str]:
    terms = [str(term).casefold() for term in recipe.get("coverage_terms", ())]
    return [term for term in terms if term]


def _text_has_coverage_terms(text: str, recipe: dict[str, Any]) -> bool:
    return any(_text_has_coverage_term(text, term) for term in _coverage_terms(recipe))


def _text_has_coverage_term(text: str, term: str) -> bool:
    if ".*" in term:
        return re.search(term, text) is not None
    return term in text


def _build_issue(
    task: TaskSpec,
    flow: CriticalFlow,
    recipe_name: str,
) -> ValidationIssue:
    recipe = SECURITY_RECIPES[recipe_name]
    return ValidationIssue(
        code=str(recipe["issue_code"]),
        severity=_resolve_recipe_severity(task, recipe_name),
        message=(
            f"task '{task.id}' verification lacks {recipe_name} security "
            f"recipe coverage for critical flow '{flow.id}'"
        ),
        task_ids=[task.id],
        evidence=_issue_evidence(task, flow, recipe_name),
    )


def _issue_evidence(
    task: TaskSpec,
    flow: CriticalFlow,
    recipe_name: str,
) -> dict[str, Any]:
    recipe = SECURITY_RECIPES[recipe_name]
    verification = task.verification
    check_names = [check.name for check in verification.checks] if verification else []
    evidence = {
        "flow_id": flow.id,
        "surface_type": recipe_name,
        "check_names": check_names,
    }
    if recipe_name == "url_input":
        evidence["missing_encodings"] = _missing_encoding_entries(task)
    if recipe_name == "temporal:store_then_use":
        evidence["temporal_pattern"] = _flow_temporal_pattern(flow)
    if recipe_name == "auth_token":
        evidence["unsafe_compare_paths"] = _unsafe_auth_compare_paths(task)
    for key in _recipe_evidence_keys(recipe):
        evidence[key] = recipe[key]
    return evidence


def _recipe_evidence_keys(recipe: dict[str, Any]) -> List[str]:
    keys = [
        "hostname_encoding_matrix",
        "timing_safe_compare_patterns",
        "toctou_test_templates",
        "two_phase_test_template",
    ]
    return [key for key in keys if key in recipe]


def _flow_temporal_pattern(flow: CriticalFlow) -> str:
    return str(getattr(flow, "temporal_pattern", "") or "")


def _flow_has_token_type_context(
    flow: CriticalFlow,
    task: TaskSpec,
    recipe: dict[str, Any],
) -> bool:
    context = " ".join(
        [
            _flow_security_text(flow),
            task.goal_behavior,
            task.acceptance_criteria,
        ]
    ).casefold()
    return _text_has_coverage_terms(context, recipe)


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


def _normalized_path(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/")


def _unsafe_auth_compare_paths(task: TaskSpec) -> List[str]:
    return [
        str(path)
        for path in _claimed_source_files(task.claimed_paths)
        if _path_has_unsafe_auth_compare(path)
    ]


def _claimed_source_files(paths: Iterable[str]) -> List[Path]:
    source_paths: List[Path] = []
    for raw_path in paths:
        path = _resolve_source_path(raw_path)
        if path.is_file():
            source_paths.append(path)
        elif path.is_dir():
            source_paths.extend(
                child for child in sorted(path.rglob("*.py")) if child.is_file()
            )
    return source_paths


def _resolve_source_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _path_has_unsafe_auth_compare(path: Path) -> bool:
    return any(
        _line_has_unsafe_auth_compare(line)
        for line in path.read_text().splitlines()
    )


def _line_has_unsafe_auth_compare(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if TIMING_SAFE_COMPARE in stripped:
        return False
    return bool(TOKEN_COMPARE_RE.search(stripped))
