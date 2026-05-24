"""Deterministic security check generation for Ralph plans."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from .models import CriticalFlow, Plan, TaskSpec
from .plan_io import load_plan
from .security_check_generator_llm import generate_llm_security_checks as _generate_llm_security_checks
from .security_recipes import SECURITY_RECIPES

DEFAULT_ENDPOINT = "/"
DEFAULT_FORMAT = "json"
FLOW_NAME_FIELDS = ("id", "description", "surface_type", "temporal_pattern")
FORMAT_KEYWORDS = ("json", "yaml", "xml", "form", "multipart", "csv")
HTTP_METHODS = "GET|POST|PUT|PATCH|DELETE"
INPUT_VALIDATION_CATEGORY = "input_validation"
URL_INPUT_RECIPE = "url_input"
AUTH_TOKEN_RECIPE = "auth_token"
TOKEN_TYPE_RECIPE = "token_type_confusion"
TEMPORAL_RECIPE = "temporal:store_then_use"
FLOW_CATEGORY_ORDER = (
    INPUT_VALIDATION_CATEGORY,
    URL_INPUT_RECIPE,
    AUTH_TOKEN_RECIPE,
    TOKEN_TYPE_RECIPE,
    TEMPORAL_RECIPE,
)
INPUT_VALIDATION_TERMS = (
    "input-validation",
    "input validation",
    "input_validation",
    "fts",
    "sql",
    "search",
    "xss",
    "injection",
)
URL_CATEGORY_TERMS = ("url-input", "url input", "url_validation", "url-validation")
AUTH_CATEGORY_TERMS = (
    "auth-token",
    "auth token",
    "timing-safe",
    "timing safe",
    "credential",
    "secret",
    "password",
)
AUTH_FLOW_TERMS = ("auth", "oauth", "jwt")
TOKEN_TYPE_CATEGORY_TERMS = (
    "token type",
    "type confusion",
    "type==access",
    "access token",
    "refresh token",
)
TOKEN_TYPE_EXPLICIT_TERMS = ("token type", "type confusion", "type==access")
ACCESS_TOKEN_TERMS = ("access token",)
REFRESH_TOKEN_TERMS = ("refresh token",)
INPUT_VALIDATION_TESTS = (
    ("fts5-sql-injection", "test_fts5_sql_injection"),
    ("pagination-lower-bound", "test_pagination_lower_bound"),
    ("pagination-upper-bound", "test_pagination_upper_bound"),
)
SSRF_TEST_TARGET = "tests/security/test_ssrf.py::test_encoded_ip_matrix"
AUTH_TEST_TARGET = "tests/security/test_auth_timing.py::test_timing_safe_token_compare"
TOKEN_TYPE_TEST_TARGET = (
    "tests/security/test_auth_token_types.py::"
    "test_reject_refresh_token_as_access_token"
)
TOCTOU_TEST_TARGET = "tests/security/test_toctou.py::test_store_then_use_revalidation"
ENDPOINT_RE = re.compile(rf"(?:^|\s)(?:{HTTP_METHODS})?\s*(/[A-Za-z0-9_./{{}}:-]+)", re.I)
METHOD_ENDPOINT_RE = re.compile(rf"\b({HTTP_METHODS})\s+(/[A-Za-z0-9_./{{}}:-]+)", re.I)


def generate_security_checks(plan_path: str) -> list[dict[str, object]]:
    """Return deterministic behavioral security checks for a Ralph plan."""
    plan = load_plan(Path(plan_path))
    checks: list[dict[str, object]] = []
    for flow in plan.critical_flows:
        context = _context_for_flow(plan, flow)
        categories = _flow_categories(flow, context["category_text"])
        if not categories:
            continue
        for category in categories:
            checks.extend(_checks_for_category(category, context))
    return checks


def generate_llm_security_checks(
    plan_path: str,
    *,
    provider: str = "gemini",
) -> list[dict[str, object]]:
    """Return LLM-generated behavioral security checks for a Ralph plan."""
    return _generate_llm_security_checks(plan_path, provider=provider)


def _flow_categories(flow: CriticalFlow, category_text: str) -> list[str]:
    flow_text = _flow_text(flow)
    return [
        category
        for category in FLOW_CATEGORY_ORDER
        if _flow_matches_category(flow, flow_text, category_text, category)
    ]


def _flow_matches_category(
    flow: CriticalFlow,
    flow_text: str,
    category_text: str,
    category: str,
) -> bool:
    if category == INPUT_VALIDATION_CATEGORY:
        return _has_any(flow_text, INPUT_VALIDATION_TERMS)
    if category == URL_INPUT_RECIPE:
        return _has_any(
            flow_text,
            _recipe_terms(URL_INPUT_RECIPE, URL_CATEGORY_TERMS),
        )
    if category == AUTH_TOKEN_RECIPE:
        return _has_any(
            flow_text,
            _recipe_terms(AUTH_TOKEN_RECIPE, AUTH_CATEGORY_TERMS),
        )
    if category == TOKEN_TYPE_RECIPE:
        return _token_type_category_matches(flow, flow_text, category_text)
    if category == TEMPORAL_RECIPE:
        return bool(_temporal_pattern(flow))
    return False


def _context_for_flow(plan: Plan, flow: CriticalFlow) -> dict[str, str]:
    tasks = _tasks_for_flow(plan, flow)
    text = "\n".join([_flow_text(flow), *[_task_text(task) for task in tasks]])
    return {
        "category_text": text,
        "flow_id": flow.id,
        "flow_slug": _slug(flow.id),
        "endpoint": _extract_endpoint(text),
        "data_format": _extract_format(text),
        "temporal_pattern": _temporal_pattern(flow),
        "temporal_slug": _slug(_temporal_pattern(flow) or "temporal"),
    }


def _tasks_for_flow(plan: Plan, flow: CriticalFlow) -> list[TaskSpec]:
    matched = [task for task in plan.tasks if _task_matches_flow(task, flow)]
    if matched:
        return matched
    return list(plan.tasks) if len(plan.tasks) == 1 else []


def _task_matches_flow(task: TaskSpec, flow: CriticalFlow) -> bool:
    verification = task.verification
    if verification and flow.id in verification.covers.flows:
        return True
    if task.id in flow.test_created_by:
        return True
    paths = [*task.claimed_paths, *task.awareness_paths]
    return any(_paths_overlap(entrypoint, path) for entrypoint in flow.entrypoints for path in paths)


def _checks_for_category(category: str, context: dict[str, str]) -> list[dict[str, object]]:
    if category == INPUT_VALIDATION_CATEGORY:
        return _input_validation_checks(context)
    if category == URL_INPUT_RECIPE:
        matrix = {"SECURITY_URL_MATRIX": ",".join(_recipe_sequence(
            URL_INPUT_RECIPE,
            "hostname_encoding_matrix",
        ))}
        return [_template_check(context, "ssrf-encoded-ip-matrix", SSRF_TEST_TARGET, extra_env=matrix)]
    if category == AUTH_TOKEN_RECIPE:
        return [_template_check(
            context,
            "auth-timing-safe-compare",
            AUTH_TEST_TARGET,
            extra_env=_auth_recipe_env(),
        )]
    if category == TOKEN_TYPE_RECIPE:
        return [_template_check(
            context,
            "token-type-confusion",
            TOKEN_TYPE_TEST_TARGET,
        )]
    if category == TEMPORAL_RECIPE:
        return [_template_check(
            context,
            f"toctou-{context['temporal_slug']}",
            TOCTOU_TEST_TARGET,
            extra_env=_temporal_recipe_env(context),
        )]
    return []


def _input_validation_checks(context: dict[str, str]) -> list[dict[str, object]]:
    return [
        _template_check(context, suffix, f"tests/security/test_input_validation.py::{test_name}")
        for suffix, test_name in INPUT_VALIDATION_TESTS
    ]


def _template_check(
    context: dict[str, str],
    suffix: str,
    test_target: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> dict[str, object]:
    env = {
        "SECURITY_FLOW_ID": context["flow_id"],
        "SECURITY_ENDPOINT": context["endpoint"],
        "SECURITY_FORMAT": context["data_format"],
        **(extra_env or {}),
    }
    return _check(_name(context, suffix), _env_command(test_target, env))


def _env_command(test_target: str, env: dict[str, str]) -> str:
    assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
    return f"{assignments} python -m pytest {shlex.quote(test_target)} -q"


def _check(name: str, command: str) -> dict[str, object]:
    return {"name": name, "command": command, "auto_generated": True}


def _flow_text(flow: CriticalFlow) -> str:
    parts = [str(getattr(flow, field) or "") for field in FLOW_NAME_FIELDS]
    return " ".join(parts).casefold().replace("_", "-")


def _task_text(task: TaskSpec) -> str:
    parts = [task.goal_behavior, task.acceptance_criteria]
    parts.extend(_schema_hint_text(task))
    return "\n".join(str(part) for part in parts if part)


def _schema_hint_text(task: TaskSpec) -> list[str]:
    hints: list[str] = []
    for contract in task.provides:
        hint = contract.schema_hint
        hints.append(_hint_text(hint))
    return hints


def _hint_text(hint: object) -> str:
    if isinstance(hint, dict):
        return " ".join(_hint_text(hint[key]) for key in sorted(hint))
    if isinstance(hint, (list, tuple)):
        return " ".join(_hint_text(value) for value in hint)
    if hint is None:
        return ""
    return str(hint)


def _auth_recipe_env() -> dict[str, str]:
    patterns = SECURITY_RECIPES[AUTH_TOKEN_RECIPE]["timing_safe_compare_patterns"]
    if not isinstance(patterns, dict):
        raise TypeError("auth_token timing_safe_compare_patterns must be a dict")
    return {"SECURITY_COMPARE_PATTERNS": ",".join(map(str, patterns.values()))}


def _temporal_recipe_env(context: dict[str, str]) -> dict[str, str]:
    templates = _recipe_sequence(TEMPORAL_RECIPE, "two_phase_test_template")
    return {
        "SECURITY_TEMPORAL_PATTERN": context["temporal_pattern"],
        "SECURITY_TOCTOU_BARRIER": "true",
        "SECURITY_TOCTOU_TEMPLATES": " | ".join(templates),
    }


def _recipe_terms(recipe_name: str, extra_terms: tuple[str, ...]) -> tuple[str, ...]:
    keywords = SECURITY_RECIPES[recipe_name]["keywords"]
    return (*_string_tuple(keywords), *extra_terms)


def _recipe_sequence(recipe_name: str, key: str) -> tuple[str, ...]:
    return _string_tuple(SECURITY_RECIPES[recipe_name][key])


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(str(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if value:
        return (str(value),)
    return ()


def _extract_endpoint(text: str) -> str:
    method_match = METHOD_ENDPOINT_RE.search(text)
    if method_match:
        return method_match.group(2)
    endpoint_match = ENDPOINT_RE.search(text)
    return endpoint_match.group(1) if endpoint_match else DEFAULT_ENDPOINT


def _extract_format(text: str) -> str:
    normalized = text.casefold()
    for data_format in FORMAT_KEYWORDS:
        if data_format in normalized:
            return data_format
    return DEFAULT_FORMAT


def _paths_overlap(left: str, right: str) -> bool:
    left_path = left.strip().replace("\\", "/").strip("/")
    right_path = right.strip().replace("\\", "/").strip("/")
    return bool(left_path and right_path) and (
        left_path == right_path
        or left_path.startswith(f"{right_path}/")
        or right_path.startswith(f"{left_path}/")
    )


def _name(context: dict[str, str], suffix: str) -> str:
    return f"{context['flow_slug']}-{suffix}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "security-flow"


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    normalized = _normalized_text(text)
    return any(_contains_term(normalized, needle) for needle in needles)


def _contains_term(normalized_text: str, term: str) -> bool:
    normalized_term = _normalized_text(term)
    if not normalized_term:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def _token_type_category_matches(
    flow: CriticalFlow,
    flow_text: str,
    category_text: str,
) -> bool:
    return _is_auth_flow(flow, flow_text) and (
        _has_any(category_text, TOKEN_TYPE_EXPLICIT_TERMS)
        or (
            _has_any(category_text, ACCESS_TOKEN_TERMS)
            and _has_any(category_text, REFRESH_TOKEN_TERMS)
            and _has_any(category_text, TOKEN_TYPE_CATEGORY_TERMS)
        )
    )


def _is_auth_flow(flow: CriticalFlow, flow_text: str) -> bool:
    surface_type = str(getattr(flow, "surface_type", "") or "")
    return surface_type in {AUTH_TOKEN_RECIPE, TOKEN_TYPE_RECIPE} or _has_any(
        flow_text,
        AUTH_FLOW_TERMS,
    )


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _temporal_pattern(flow: CriticalFlow) -> str:
    return str(getattr(flow, "temporal_pattern", "") or "")
