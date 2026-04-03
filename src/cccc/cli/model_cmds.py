from __future__ import annotations

"""Model-related CLI command handlers."""

from .common import *  # noqa: F401,F403

__all__ = [
    "cmd_model_review",
]


def cmd_model_review(args: argparse.Namespace) -> int:
    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_not_running", "message": "ccccd is not running"}})
        return 1

    group_id = _resolve_group_id(str(getattr(args, "group", "") or ""))
    model_key = str(getattr(args, "model_key", "") or "").strip()

    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "Missing --group or active group"}})
        return 2
    if not model_key:
        _print_json({"ok": False, "error": {"code": "missing_model_key", "message": "Missing model_key"}})
        return 2

    resp = call_daemon(
        {
            "op": "model_review_request",
            "args": {
                "group_id": group_id,
                "model_key": model_key,
            },
        }
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1
