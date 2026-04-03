"""Shared adapter-layer helpers for CLI, web, and MCP request shaping."""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Mapping

__all__ = [
    "build_daemon_request",
    "normalize_priority",
    "normalize_reply_required",
    "resolve_group_and_project_root",
    "resolve_sender_actor",
]

_DEFAULT_PRIORITY = "normal"
_ATTENTION_PRIORITY = "attention"
_TRUE_TOKENS = frozenset({"1", "true", "yes", "y", "on"})
_FALSE_TOKENS = frozenset({"", "0", "false", "no", "n", "off"})
_PRIORITY_ALIASES = {
    _DEFAULT_PRIORITY: _DEFAULT_PRIORITY,
    "low": _DEFAULT_PRIORITY,
    "false": _DEFAULT_PRIORITY,
    "off": _DEFAULT_PRIORITY,
    _ATTENTION_PRIORITY: _ATTENTION_PRIORITY,
    "high": _ATTENTION_PRIORITY,
    "urgent": _ATTENTION_PRIORITY,
    "true": _ATTENTION_PRIORITY,
    "on": _ATTENTION_PRIORITY,
}


def build_daemon_request(op: str, **kwargs: Any) -> dict[str, Any]:
    return {"op": str(op or "").strip(), "args": dict(kwargs)}


def resolve_group_and_project_root(
    group_id: str,
    daemon_request_fn: Callable[[dict[str, Any]], Any],
) -> tuple[dict[str, Any], str]:
    response = daemon_request_fn(build_daemon_request("group_show", group_id=group_id))
    if not isinstance(response, Mapping):
        return {}, ""
    if "ok" in response and not bool(response.get("ok")):
        return {}, ""
    result = response.get("result")
    if not isinstance(result, Mapping):
        return {}, ""
    raw_group = result.get("group")
    if not isinstance(raw_group, Mapping):
        return {}, ""
    group = dict(raw_group)
    return group, _extract_project_root(group)


def resolve_sender_actor(group: dict[str, Any], by: str) -> str:
    sender = str(by or "user").strip() or "user"
    if sender != "user":
        return sender
    env_actor = str(os.environ.get("CCCC_ACTOR_ID") or "").strip()
    if env_actor:
        return env_actor
    return _fallback_sender_from_group(group) or sender


def normalize_priority(value: Any) -> str:
    if value is None:
        return _DEFAULT_PRIORITY
    if isinstance(value, bool):
        return _ATTENTION_PRIORITY if value else _DEFAULT_PRIORITY
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return _DEFAULT_PRIORITY
        return _ATTENTION_PRIORITY if value else _DEFAULT_PRIORITY
    text = str(value).strip().lower()
    if not text:
        return _DEFAULT_PRIORITY
    normalized = _PRIORITY_ALIASES.get(text)
    if normalized is not None:
        return normalized
    try:
        return _ATTENTION_PRIORITY if int(text) else _DEFAULT_PRIORITY
    except Exception:
        return _DEFAULT_PRIORITY


def normalize_reply_required(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, float):
        if math.isnan(value):
            return False
        return value != 0.0
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    if text in _TRUE_TOKENS:
        return True
    if text in _FALSE_TOKENS:
        return False
    try:
        return int(text) != 0
    except Exception:
        return False


def _extract_project_root(group: Mapping[str, Any]) -> str:
    doc = group.get("doc")
    group_doc = doc if isinstance(doc, Mapping) else group
    # The adapters targeted by T11 currently resolve from active scope URLs.
    # We also check direct project_root keys first because the task contract
    # explicitly calls for a group.doc/project_root preference when present.
    for candidate in (group_doc, group):
        project_root = _string_value(candidate.get("project_root"))
        if project_root:
            return project_root
    scopes = group_doc.get("scopes")
    scope_list = scopes if isinstance(scopes, list) else []
    active_scope = _string_value(group_doc.get("active_scope_key"))
    for scope in scope_list:
        if not isinstance(scope, Mapping):
            continue
        if _string_value(scope.get("scope_key")) != active_scope:
            continue
        project_root = _string_value(scope.get("url"))
        if project_root:
            return project_root
    for scope in scope_list:
        if not isinstance(scope, Mapping):
            continue
        project_root = _string_value(scope.get("url"))
        if project_root:
            return project_root
    return ""


def _fallback_sender_from_group(group: Mapping[str, Any]) -> str:
    doc = group.get("doc")
    group_doc = doc if isinstance(doc, Mapping) else group
    actor_id = _string_value(group_doc.get("actor_id"))
    return actor_id


def _string_value(value: Any) -> str:
    return str(value or "").strip()
