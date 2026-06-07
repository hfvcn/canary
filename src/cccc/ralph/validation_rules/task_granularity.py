"""Task granularity compression checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ..models import Plan, ValidationIssue

W_TASK_GRANULARITY_COMPRESSION = "W_TASK_GRANULARITY_COMPRESSION"

_MIN_ADDRESSES = 4
_MIN_COMPONENTS = 3
_MIN_BEHAVIOR_SEGMENTS = 4

_EXEMPT_ROLES = frozenset({"integration", "verification"})
_THIRD_LEVEL_COMPONENT_ROOTS = frozenset({"daemon", "ports", "providers", "vendor"})
_ENUMERATED_LINE_RE = re.compile(
    r"^\s*(?:[A-Z]\.|[a-z]\.|[0-9]+[.)]|[-*•]|[一二三四五六七八九十]+[、.])\s+",
)
_CONNECTOR_RE = re.compile(r"(^|[，,；;。.!?])\s*(另外|同时|此外)\s*")


def _path_parts(path: str) -> list[str]:
    raw = str(path or "").strip().replace("\\", "/")
    return [part for part in raw.split("/") if part and part != "."]


def _is_non_component(parts: list[str]) -> bool:
    lowered = [part.lower() for part in parts]
    if not lowered:
        return True
    if lowered[0] == "tests":
        return True
    return any("fixture" in part for part in lowered)


def _src_component(parts: list[str]) -> str | None:
    if len(parts) < 3 or parts[0].lower() != "src":
        return None
    package = parts[1]
    second_level = parts[2]
    if second_level.startswith("__"):
        return None
    if second_level not in _THIRD_LEVEL_COMPONENT_ROOTS or len(parts) < 4:
        return f"{package}/{second_level}"
    third_level = parts[3]
    if third_level.startswith("__") or "." in third_level:
        return f"{package}/{second_level}"
    return f"{package}/{second_level}/{third_level}"


def _component_of(path: str) -> str | None:
    parts = _path_parts(path)
    if _is_non_component(parts):
        return None
    return _src_component(parts)


def _connector_breaks(line: str, *, allow_line_start: bool) -> int:
    count = 0
    for match in _CONNECTOR_RE.finditer(line):
        if not allow_line_start and match.start() == 0:
            continue
        count += 1
    return count


def _behavior_segments(goal_behavior: str) -> int:
    text = str(goal_behavior or "").strip()
    if not text:
        return 0

    count = 0
    paragraph_open = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            paragraph_open = False
            continue
        starts_segment = _ENUMERATED_LINE_RE.match(line) is not None
        if starts_segment or not paragraph_open:
            count += 1
            paragraph_open = True
            allow_line_start = False
        else:
            allow_line_start = True
        count += _connector_breaks(line, allow_line_start=allow_line_start)
    return count


def _component_count(claimed_paths: list[str]) -> int:
    components = {
        component
        for path in claimed_paths
        for component in [_component_of(path)]
        if component is not None
    }
    return len(components)


def _check_task_granularity(
    plan: Plan,
    *,
    project_root: Path | None = None,
    **_: object,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for task in plan.tasks:
        if task.role in _EXEMPT_ROLES:
            continue
        n_addresses = len(task.addresses)
        n_components = _component_count(task.claimed_paths)
        n_segments = _behavior_segments(task.goal_behavior)
        if n_addresses < _MIN_ADDRESSES:
            continue
        if n_components < _MIN_COMPONENTS:
            continue
        if n_segments < _MIN_BEHAVIOR_SEGMENTS:
            continue
        issues.append(ValidationIssue(
            code=W_TASK_GRANULARITY_COMPRESSION,
            severity="warning",
            task_ids=[task.id],
            message=(
                f"task '{task.id}' appears to compress multiple independent work items "
                "into one coarse task"
            ),
            evidence={
                "n_addresses": n_addresses,
                "n_components": n_components,
                "n_segments": n_segments,
            },
        ))
    return issues
