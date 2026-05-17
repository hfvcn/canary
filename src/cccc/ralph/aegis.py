"""Aegis task intent helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

_FIX_KEYWORDS = ("fix", "bug", "debug", "修复", "修")
_FEATURE_KEYWORDS = ("add", "feature", "implement", "新增", "添加")
_REFACTOR_KEYWORDS = ("refactor", "重构", "migrate", "迁移", "replace", "替换")
_TEST_KEYWORDS = ("test", "测试")
_SUGGEST_PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:tbd|todo)\b(?![/\\.\-])",
    re.IGNORECASE,
)
_TEST_PATH_MARKERS = ("test_", "_test", "tests/")
_PATCH_SHAPE_RISK_KEYWORDS = (
    "fallback",
    "adapter",
    "guard",
    "compat",
    "legacy",
    "兼容",
    "降级",
)


@dataclass(frozen=True)
class SuggestAegisIssue:
    code: str
    severity: Literal["error", "warning"]
    reason: str


def effective_intent(task: Any) -> str:
    """Return the explicit Aegis intent or infer one from task wording."""
    explicit_intent = _aegis_value(task, "intent")
    if explicit_intent:
        return str(explicit_intent)

    text = _task_search_text(task)
    if _has_any_keyword(text, _FIX_KEYWORDS):
        return "fix"
    if _has_any_keyword(text, _FEATURE_KEYWORDS):
        return "feature"
    if _has_any_keyword(text, _REFACTOR_KEYWORDS):
        return "refactor"
    if _has_any_keyword(text, _TEST_KEYWORDS):
        return "test"
    return "general"


def has_patch_shape_risk(task: Any) -> bool:
    """Return whether task wording suggests fallback/compatibility patch shape."""
    return _has_any_keyword(_task_search_text(task), _PATCH_SHAPE_RISK_KEYWORDS)


def suggest_aegis_issues(task: Any) -> list[SuggestAegisIssue]:
    """Return quick Aegis issues used by suggest-stage candidate filtering."""
    issues: list[SuggestAegisIssue] = []
    placeholder_field = _suggest_placeholder_field(task)
    if placeholder_field:
        issues.append(_suggest_issue(
            task=task,
            code="E_AEGIS_PLACEHOLDER_CONTENT",
            severity="error",
            detail=f"placeholder content in {placeholder_field}",
        ))

    intent = effective_intent(task)
    if intent == "refactor" and _aegis_value(task, "retirement_track") is None:
        issues.append(_suggest_issue(
            task=task,
            code="E_AEGIS_RETIREMENT_TRACK_MISSING",
            severity="error",
            detail="refactor task has no retirement_track",
        ))
    if intent == "fix" and _aegis_value(task, "repair_track") is None:
        issues.append(_suggest_issue(
            task=task,
            code="W_AEGIS_FIX_NO_REPAIR_TRACK",
            severity="warning",
            detail="fix task has no repair_track",
        ))
    if intent in ("fix", "feature") and not _has_claimed_test_path(task):
        issues.append(_suggest_issue(
            task=task,
            code="W_AEGIS_TDD_NO_TEST_PATH",
            severity="warning",
            detail=f"{intent} task claims no test path",
        ))
    return issues


def _aegis_value(task: Any, key: str) -> Any:
    aegis = getattr(task, "aegis", None)
    if isinstance(aegis, dict):
        return aegis.get(key)
    if aegis is None:
        return None
    return getattr(aegis, key, None)


def _task_search_text(task: Any) -> str:
    title = getattr(task, "title", "") or ""
    goal = getattr(task, "goal", "") or ""
    goal_behavior = getattr(task, "goal_behavior", "") or ""
    return f"{title}\n{goal}\n{goal_behavior}".casefold()


def _suggest_placeholder_field(task: Any) -> str:
    for field_name in ("title", "goal", "goal_behavior"):
        value = str(getattr(task, field_name, "") or "")
        if _SUGGEST_PLACEHOLDER_PATTERN.search(value):
            return field_name
    return ""


def _suggest_issue(
    *,
    task: Any,
    code: str,
    severity: Literal["error", "warning"],
    detail: str,
) -> SuggestAegisIssue:
    task_id = str(getattr(task, "id", "") or "<unknown>")
    return SuggestAegisIssue(
        code=code,
        severity=severity,
        reason=f"{code}: task {task_id} {detail}",
    )


def _has_claimed_test_path(task: Any) -> bool:
    paths = getattr(task, "claimed_paths", []) or []
    normalized = [str(path).replace("\\", "/").casefold() for path in paths]
    return any(marker in path for path in normalized for marker in _TEST_PATH_MARKERS)


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.casefold() in text for keyword in keywords)
