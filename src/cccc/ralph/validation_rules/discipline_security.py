"""Aegis security discipline validation rules."""

from __future__ import annotations

import re
from typing import Any, List

from ..models import Plan, ValidationIssue

FEATURE_INTENT = "feature"
SECURITY_CHAIN_MISSING_CODE = "E_AEGIS_SECURITY_CHAIN_MISSING"
SECURITY_FLOW_KEYWORDS = (
    "ssrf",
    "auth",
    "input-validation",
    "security",
    "xss",
    "injection",
    "token",
    "secret",
    "credential",
    "password",
    "permission",
    "csrf",
)
SECURITY_CHECK_KEYWORDS = SECURITY_FLOW_KEYWORDS
SECURITY_FLOW_FIELDS = ("id", "description", "surface_type", "temporal_pattern")


def _check_aegis_security_chain(plan: Plan) -> List[ValidationIssue]:
    """Require feature Aegis tasks to test declared security critical flows."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        issues.extend(_check_aegis_security_chain_for_task(plan, task))
    return issues


def _check_aegis_security_chain_for_task(
    plan: Plan,
    task: Any,
) -> List[ValidationIssue]:
    intent = _aegis_intent(task)
    if intent != FEATURE_INTENT:
        return []
    flow_ids = _security_critical_flow_ids(plan)
    if not flow_ids:
        return []
    if _task_has_security_check(task):
        return []
    return [_security_issue(task, intent, flow_ids)]


def _security_issue(
    task: Any,
    intent: str,
    flow_ids: List[str],
) -> ValidationIssue:
    return ValidationIssue(
        code=SECURITY_CHAIN_MISSING_CODE,
        severity="error",
        message=(
            f"{intent} task '{task.id}' has security critical_flow declarations "
            "without security-related verification checks"
        ),
        task_ids=[task.id],
        evidence={
            "intent": intent,
            "critical_flows": flow_ids,
            "check_names": _verification_check_names(task),
        },
    )


def _aegis_intent(task: Any) -> str:
    aegis = getattr(task, "aegis", None)
    if isinstance(aegis, dict):
        return str(aegis.get("intent") or "")
    if aegis is None:
        return ""
    return str(getattr(aegis, "intent", "") or "")


def _security_critical_flow_ids(plan: Plan) -> List[str]:
    return [
        flow.id
        for flow in plan.critical_flows
        if _contains_security_keyword(_flow_security_text(flow), SECURITY_FLOW_KEYWORDS)
    ]


def _flow_security_text(flow: Any) -> str:
    data = flow.model_dump() if hasattr(flow, "model_dump") else dict(flow)
    return " ".join(str(data.get(field) or "") for field in SECURITY_FLOW_FIELDS)


def _task_has_security_check(task: Any) -> bool:
    verification = getattr(task, "verification", None)
    checks = getattr(verification, "checks", []) if verification else []
    return any(
        _contains_security_keyword(_check_security_text(check), SECURITY_CHECK_KEYWORDS)
        for check in checks
    )


def _check_security_text(check: Any) -> str:
    return f"{getattr(check, 'name', '')} {getattr(check, 'command', '')}"


def _verification_check_names(task: Any) -> List[str]:
    verification = getattr(task, "verification", None)
    checks = getattr(verification, "checks", []) if verification else []
    return [str(getattr(check, "name", "")) for check in checks]


def _contains_security_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[\s_]+", "-", text.casefold())
    return any(keyword in normalized for keyword in keywords)
