"""Aegis security discipline validation rules."""

from __future__ import annotations

import re
from typing import Any, List

from ..models import Plan, ValidationIssue

FEATURE_INTENT = "feature"
SECURITY_CHAIN_MISSING_CODE = "E_AEGIS_SECURITY_CHAIN_MISSING"
SSRF_ROUTE_BINDING_MISSING_CODE = "W_SSRF_ROUTE_BINDING_MISSING"
FTS_CJK_SUBSTRING_MISSING_CODE = "W_FTS_CJK_SUBSTRING_MISSING"
SILENT_DEGRADATION_CODE = "W_SILENT_DEGRADATION_UNCHECKED"
SECURITY_FLOW_KEYWORDS = (
    "ssrf", "auth", "input-validation", "security", "xss", "injection",
    "token", "secret", "credential", "password", "permission", "csrf",
)
SECURITY_CHECK_KEYWORDS = SECURITY_FLOW_KEYWORDS
FTS_FLOW_KEYWORDS = ("fts", "search", "fulltext", "full-text", "full_text")
DEGRADATION_FLOW_KEYWORDS = ("search", "query", "database", "db")
CJK_CONTEXT_KEYWORDS = (
    "chinese", "cjk", "中文", "unicode", "i18n", "zh", "ja", "ko",
    "multilingual", "日本語", "韓國語",
)
SUBSTRING_TEST_KEYWORDS = ("substring", "partial", "子串", "分词", "tokenize", "segment", "bigram", "ngram")
ERROR_PROPAGATION_KEYWORDS = (
    "error-propagation", "error_propagation", "exception", "error-handling",
    "error_handling", "fault", "degradation", "fallback-test", "fallback_test",
    "error-path", "error_path", "failure-mode", "failure_mode",
)
SECURITY_FLOW_FIELDS = ("id", "description", "surface_type", "temporal_pattern")
ROUTE_LEVEL_KEYWORDS = (
    "endpoint", "route", "handler", "api", "request", "response", "client",
    "call-chain", "call_chain",
)
IMPORT_ONLY_KEYWORDS = ("import", "compile", "syntax")
def _check_aegis_security_chain(plan: Plan) -> List[ValidationIssue]:
    """Require feature Aegis tasks to test declared security critical flows."""
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        issues.extend(_check_aegis_security_chain_for_task(plan, task))
    return issues


def _check_ssrf_route_binding(plan: Plan) -> List[ValidationIssue]:
    """Warn when SSRF verification is import-only and lacks route binding."""
    return _collect_task_warnings(plan, set(_ssrf_critical_flow_ids(plan)), _check_ssrf_route_binding_for_task)
def _check_fts_cjk_coverage(plan: Plan) -> List[ValidationIssue]:
    """Warn when FTS/CJK coverage lacks substring-oriented verification."""
    return _collect_task_warnings(plan, set(_fts_cjk_critical_flow_ids(plan)), _check_fts_cjk_coverage_for_task)
def _check_silent_degradation_pattern(plan: Plan) -> List[ValidationIssue]:
    """Warn when search/query verification omits error-propagation coverage."""
    return _collect_task_warnings(plan, set(_degradation_critical_flow_ids(plan)), _check_silent_degradation_pattern_for_task)
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
        message=f"{intent} task '{task.id}' has security critical_flow declarations without security-related verification checks",
        task_ids=[task.id],
        evidence={"intent": intent, "critical_flows": flow_ids, "check_names": _verification_check_names(task)},
    )
def _check_ssrf_route_binding_for_task(
    task: Any,
    ssrf_flow_ids: set[str],
) -> ValidationIssue | None:
    checks = _verification_checks(task)
    if not checks:
        return None
    covered_flow_ids = _covered_flow_ids(task, ssrf_flow_ids)
    if not covered_flow_ids:
        return None
    check_texts = [_check_security_text(check) for check in checks]
    if not any(
        _contains_security_keyword(text, SECURITY_CHECK_KEYWORDS)
        for text in check_texts
    ):
        return None
    if any(
        _contains_security_keyword(text, ROUTE_LEVEL_KEYWORDS)
        for text in check_texts
    ):
        return None
    if not all(
        _contains_security_keyword(text, IMPORT_ONLY_KEYWORDS)
        for text in check_texts
    ):
        return None
    return _warning_issue(task, SSRF_ROUTE_BINDING_MISSING_CODE, f"task '{task.id}' covers SSRF critical flows with import-only checks and lacks route-level verification", covered_flow_ids)
def _check_fts_cjk_coverage_for_task(
    task: Any,
    fts_cjk_flow_ids: set[str],
) -> ValidationIssue | None:
    checks = _verification_checks(task)
    if not checks:
        return None
    covered_flow_ids = _covered_flow_ids(task, fts_cjk_flow_ids)
    if not covered_flow_ids:
        return None
    check_texts = [_check_security_text(check) for check in checks]
    if any(
        _contains_security_keyword(text, SUBSTRING_TEST_KEYWORDS)
        for text in check_texts
    ):
        return None
    return _warning_issue(task, FTS_CJK_SUBSTRING_MISSING_CODE, f"task '{task.id}' covers FTS/CJK critical flows without substring-oriented verification", covered_flow_ids)
def _check_silent_degradation_pattern_for_task(
    task: Any,
    degradation_flow_ids: set[str],
) -> ValidationIssue | None:
    checks = _verification_checks(task)
    if not checks:
        return None
    covered_flow_ids = _covered_flow_ids(task, degradation_flow_ids)
    if not covered_flow_ids:
        return None
    check_texts = [_check_security_text(check) for check in checks]
    if any(
        _contains_security_keyword(text, ERROR_PROPAGATION_KEYWORDS)
        for text in check_texts
    ):
        return None
    return _warning_issue(task, SILENT_DEGRADATION_CODE, "search/query critical flow lacks error-propagation test — catch-all exceptions may mask failures", covered_flow_ids)
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
def _ssrf_critical_flow_ids(plan: Plan) -> List[str]:
    return [
        flow.id
        for flow in plan.critical_flows
        if _contains_security_keyword(_flow_security_text(flow), ("ssrf",))
    ]
def _fts_cjk_critical_flow_ids(plan: Plan) -> List[str]:
    return [
        flow.id
        for flow in plan.critical_flows
        if _contains_security_keyword(_flow_security_text(flow), FTS_FLOW_KEYWORDS)
        and _contains_security_keyword(
            str(getattr(flow, "description", "") or ""),
            CJK_CONTEXT_KEYWORDS,
        )
    ]
def _degradation_critical_flow_ids(plan: Plan) -> List[str]:
    return [
        flow.id
        for flow in plan.critical_flows
        if _contains_security_keyword(
            _flow_security_text(flow), DEGRADATION_FLOW_KEYWORDS
        )
    ]
def _flow_security_text(flow: Any) -> str:
    data = flow.model_dump() if hasattr(flow, "model_dump") else dict(flow)
    return " ".join(str(data.get(field) or "") for field in SECURITY_FLOW_FIELDS)
def _task_has_security_check(task: Any) -> bool:
    return any(
        _contains_security_keyword(_check_security_text(check), SECURITY_CHECK_KEYWORDS)
        for check in _verification_checks(task)
    )
def _check_security_text(check: Any) -> str:
    return f"{getattr(check, 'name', '')} {getattr(check, 'command', '')}"
def _verification_check_names(task: Any) -> List[str]:
    return [str(getattr(check, "name", "")) for check in _verification_checks(task)]
def _verification_checks(task: Any) -> List[Any]:
    verification = getattr(task, "verification", None)
    checks = getattr(verification, "checks", []) if verification else []
    return list(checks)
def _covered_flow_ids(task: Any, critical_flow_ids: set[str]) -> List[str]:
    verification = getattr(task, "verification", None)
    covers = getattr(verification, "covers", None) if verification else None
    flow_ids = getattr(covers, "flows", []) if covers else []
    return sorted(flow_id for flow_id in flow_ids if flow_id in critical_flow_ids)
def _collect_task_warnings(plan: Plan, flow_ids: set[str], checker: Any) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not flow_ids:
        return issues
    for task in plan.tasks:
        issue = checker(task, flow_ids)
        if issue is not None:
            issues.append(issue)
    return issues
def _warning_issue(
    task: Any,
    code: str,
    message: str,
    flow_ids: List[str],
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity="warning",
        message=message,
        task_ids=[task.id],
        evidence={"critical_flows": flow_ids, "check_names": _verification_check_names(task)},
    )
def _contains_security_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[\s_]+", "-", text.casefold())
    return any(keyword in normalized for keyword in keywords)
