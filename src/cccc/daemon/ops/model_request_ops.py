"""Model review request handlers for daemon."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from ...contracts.v1 import DaemonError, DaemonResponse
from ...kernel.group import load_group
from .model_ops import request_model_review


def _error(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> DaemonResponse:
    return DaemonResponse(ok=False, error=DaemonError(code=code, message=message, details=(details or {})))


def _resolve_group_project_root(group_id: str) -> tuple[bool, Optional[Path]]:
    group = load_group(group_id)
    if group is None:
        return False, None

    active_scope = str(group.doc.get("active_scope_key") or "").strip()
    scopes = group.doc.get("scopes") if isinstance(group.doc.get("scopes"), list) else []
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        scope_key = str(scope.get("scope_key") or "").strip()
        scope_url = str(scope.get("url") or "").strip()
        if scope_key == active_scope and scope_url:
            return True, Path(scope_url).expanduser()
    for scope in scopes:
        if isinstance(scope, dict):
            scope_url = str(scope.get("url") or "").strip()
            if scope_url:
                return True, Path(scope_url).expanduser()
    return True, None


def handle_model_review_request(
    args: Dict[str, Any],
    *,
    dispatch_send: Callable[[str, Dict[str, Any]], Tuple[DaemonResponse, bool]],
) -> DaemonResponse:
    group_id = str(args.get("group_id") or "").strip()
    model_key = str(args.get("model_key") or "").strip()
    if not group_id:
        return _error("missing_group_id", "missing group_id")
    if not model_key:
        return _error("missing_model_key", "missing model_key")

    group_exists, project_root = _resolve_group_project_root(group_id)
    if not group_exists:
        return _error("group_not_found", f"group not found: {group_id}")
    if project_root is None:
        return _error("missing_project_root", "group has no attached scope/project_root")

    registry_path = project_root / ".cccc" / "models" / "registry.yaml"

    def _send_message(target_group_id: str, target_actor: str, text: str) -> None:
        resp, _ = dispatch_send(
            "send",
            {
                "group_id": target_group_id,
                "by": "user",
                "text": text,
                "to": [f"@{target_actor}"],
            },
        )
        if not resp.ok:
            error = resp.error
            message = str(error.message) if error is not None else "unknown send error"
            raise ValueError(message)

    try:
        status = request_model_review(
            model_key,
            registry_path,
            group_id,
            _send_message,
        )
    except ValueError as exc:
        return _error("model_review_request_failed", str(exc))

    return DaemonResponse(
        ok=True,
        result={
            "group_id": group_id,
            "model_key": model_key,
            "status": status or "Review request sent",
        },
    )


def try_handle_model_request_op(
    op: str,
    args: Dict[str, Any],
    *,
    dispatch_send: Optional[Callable[[str, Dict[str, Any]], Tuple[DaemonResponse, bool]]] = None,
) -> Optional[DaemonResponse]:
    if op != "model_review_request":
        return None
    if dispatch_send is None:
        return _error("internal_error", "dispatch_send callback not configured")
    return handle_model_review_request(args, dispatch_send=dispatch_send)
