"""Deterministic security check generation for Ralph plans."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Dict, List

from .models import CriticalFlow, Plan, TaskSpec
from .plan_io import load_plan


DEFAULT_ENDPOINT = "/"
DEFAULT_FORMAT = "json"
ENCODED_IP_MATRIX = (
    "0177.0.0.1",
    "2130706433",
    "0x7f000001",
    "::ffff:127.0.0.1",
    "::1",
)
FLOW_NAME_FIELDS = ("id", "description", "surface_type", "temporal_pattern")
FORMAT_KEYWORDS = ("json", "yaml", "xml", "form", "multipart", "csv")
HTTP_METHODS = "GET|POST|PUT|PATCH|DELETE"
INPUT_VALIDATION_TESTS = (
    ("fts5-sql-injection", "test_fts5_sql_injection"),
    ("pagination-lower-bound", "test_pagination_lower_bound"),
    ("pagination-upper-bound", "test_pagination_upper_bound"),
)
SSRF_TEST_TARGET = "tests/security/test_ssrf.py::test_encoded_ip_matrix"
AUTH_TEST_TARGET = "tests/security/test_auth_timing.py::test_timing_safe_token_compare"
ENDPOINT_RE = re.compile(rf"\b(?:{HTTP_METHODS})?\s*(/[A-Za-z0-9_./{{}}:-]+)")
METHOD_ENDPOINT_RE = re.compile(rf"\b({HTTP_METHODS})\s+(/[A-Za-z0-9_./{{}}:-]+)", re.I)


def generate_security_checks(plan_path: str) -> List[Dict]:
    """Return deterministic behavioral security checks for a Ralph plan."""
    plan = load_plan(Path(plan_path))
    checks: list[dict[str, object]] = []
    for flow in plan.critical_flows:
        flow_type = _flow_type(flow)
        if flow_type == "":
            continue
        context = _context_for_flow(plan, flow)
        checks.extend(_checks_for_flow(flow_type, context))
    return checks


def _flow_type(flow: CriticalFlow) -> str:
    text = _flow_text(flow)
    if _has_any(text, ("ssrf", "url-input", "url input", "url-validation")):
        return "ssrf"
    if _has_any(text, ("auth", "token", "key", "timing-safe", "timing safe")):
        return "auth"
    input_terms = ("input-validation", "input validation", "fts", "search", "xss", "injection")
    if _has_any(text, input_terms):
        return "input-validation"
    return ""


def _context_for_flow(plan: Plan, flow: CriticalFlow) -> dict[str, str]:
    tasks = _tasks_for_flow(plan, flow)
    text = "\n".join([_flow_text(flow), *[_task_text(task) for task in tasks]])
    return {
        "flow_id": flow.id,
        "flow_slug": _slug(flow.id),
        "endpoint": _extract_endpoint(text),
        "data_format": _extract_format(text),
    }


def _tasks_for_flow(plan: Plan, flow: CriticalFlow) -> list[TaskSpec]:
    matched = [task for task in plan.tasks if _task_matches_flow(task, flow)]
    return matched if matched else list(plan.tasks)


def _task_matches_flow(task: TaskSpec, flow: CriticalFlow) -> bool:
    verification = task.verification
    if verification and flow.id in verification.covers.flows:
        return True
    if task.id in flow.test_created_by:
        return True
    paths = [*task.claimed_paths, *task.awareness_paths]
    return any(_paths_overlap(entrypoint, path) for entrypoint in flow.entrypoints for path in paths)


def _checks_for_flow(flow_type: str, context: dict[str, str]) -> list[dict[str, object]]:
    if flow_type == "input-validation":
        return _input_validation_checks(context)
    if flow_type == "ssrf":
        matrix = {"SECURITY_URL_MATRIX": ",".join(ENCODED_IP_MATRIX)}
        return [_template_check(context, "ssrf-encoded-ip-matrix", SSRF_TEST_TARGET, extra_env=matrix)]
    if flow_type == "auth":
        return [_template_check(context, "auth-timing-safe-compare", AUTH_TEST_TARGET)]
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
        return " ".join(map(str, hint.values()))
    return str(hint)


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
    return any(needle in text for needle in needles)
