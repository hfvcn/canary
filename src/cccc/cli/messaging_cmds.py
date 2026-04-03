from __future__ import annotations

"""Messaging/inbox/ledger CLI command handlers."""

from ..daemon.ops.adapter_helpers import (
    build_daemon_request,
    normalize_priority,
    normalize_reply_required,
    resolve_sender_actor,
)
from .common import *  # noqa: F401,F403

__all__ = [
    "cmd_send",
    "cmd_reply",
    "cmd_tail",
    "cmd_ledger_snapshot",
    "cmd_ledger_compact",
    "cmd_inbox",
    "cmd_read",
    "cmd_prompt",
]
def cmd_send(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2

    to_tokens: list[str] = []
    to_raw = getattr(args, "to", None)
    if isinstance(to_raw, list):
        for item in to_raw:
            if not isinstance(item, str):
                continue
            parts = [p.strip() for p in item.split(",") if p.strip()]
            to_tokens.extend(parts)
    priority = normalize_priority(getattr(args, "priority", "normal"))
    reply_required = normalize_reply_required(getattr(args, "reply_required", False))
    sender = resolve_sender_actor(group.doc, getattr(args, "by", "user"))

    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_unavailable", "message": "ccccd unavailable"}})
        return 2

    resp = call_daemon(
        build_daemon_request(
            "send",
            group_id=group_id,
            text=args.text,
            by=sender,
            path=str(args.path or ""),
            to=to_tokens,
            priority=priority,
            reply_required=reply_required,
        )
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 2

def cmd_reply(args: argparse.Namespace) -> int:
    """Reply to a message (IM-style, with quote)"""
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2

    reply_to = str(args.event_id or "").strip()
    if not reply_to:
        _print_json({"ok": False, "error": {"code": "missing_event_id", "message": "missing event_id to reply to"}})
        return 2

    to_tokens: list[str] = []
    to_raw = getattr(args, "to", None)
    if isinstance(to_raw, list):
        for item in to_raw:
            if not isinstance(item, str):
                continue
            parts = [p.strip() for p in item.split(",") if p.strip()]
            to_tokens.extend(parts)

    priority = normalize_priority(getattr(args, "priority", "normal"))
    reply_required = normalize_reply_required(getattr(args, "reply_required", False))
    sender = resolve_sender_actor(group.doc, getattr(args, "by", "user"))

    if not _ensure_daemon_running():
        _print_json({"ok": False, "error": {"code": "daemon_unavailable", "message": "ccccd unavailable"}})
        return 2

    resp = call_daemon(
        build_daemon_request(
            "reply",
            group_id=group_id,
            text=args.text,
            by=sender,
            reply_to=reply_to,
            to=to_tokens,
            priority=priority,
            reply_required=reply_required,
        )
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 2

def cmd_tail(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2
    if args.follow:
        for line in follow(group.ledger_path):
            print(line)
        return 0
    for line in read_last_lines(group.ledger_path, args.lines):
        print(line)
    return 0

def cmd_ledger_snapshot(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    by = str(args.by or "user").strip()
    reason = str(args.reason or "manual").strip()

    if _ensure_daemon_running():
        resp = call_daemon({"op": "ledger_snapshot", "args": {"group_id": group_id, "by": by, "reason": reason}})
        _print_json(resp)
        return 0 if resp.get("ok") else 2

    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2
    try:
        require_group_permission(group, by=by, action="group.update")
        snap = snapshot_ledger(group, reason=reason)
    except Exception as e:
        _print_json({"ok": False, "error": {"code": "ledger_snapshot_failed", "message": str(e)}})
        return 2
    _print_json({"ok": True, "result": {"snapshot": snap}})
    return 0

def cmd_ledger_compact(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    by = str(args.by or "user").strip()
    reason = str(args.reason or "manual").strip()
    force = bool(args.force)

    if _ensure_daemon_running():
        resp = call_daemon(
            {"op": "ledger_compact", "args": {"group_id": group_id, "by": by, "reason": reason, "force": force}}
        )
        _print_json(resp)
        return 0 if resp.get("ok") else 2

    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2
    try:
        require_group_permission(group, by=by, action="group.update")
        res = compact_ledger(group, reason=reason, force=force)
    except Exception as e:
        _print_json({"ok": False, "error": {"code": "ledger_compact_failed", "message": str(e)}})
        return 2
    _print_json({"ok": True, "result": res})
    return 0

def cmd_inbox(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    actor_id = str(args.actor_id or "").strip()
    by = str(args.by or "user").strip()
    limit = int(args.limit) if isinstance(args.limit, int) else 50
    kind_filter = str(getattr(args, "kind_filter", "all") or "all").strip()
    if kind_filter not in ("all", "chat", "notify"):
        kind_filter = "all"

    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    if not actor_id:
        _print_json({"ok": False, "error": {"code": "missing_actor_id", "message": "missing actor_id"}})
        return 2

    if _ensure_daemon_running():
        resp = call_daemon({"op": "inbox_list", "args": {"group_id": group_id, "actor_id": actor_id, "by": by, "limit": limit, "kind_filter": kind_filter}})
        if resp.get("ok") and not args.mark_read:
            _print_json(resp)
            return 0
        if resp.get("ok") and args.mark_read:
            result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
            messages = result.get("messages") if isinstance(result.get("messages"), list) else []
            if messages:
                last_id = str((messages[-1] or {}).get("id") or "").strip()
                if last_id:
                    mark = call_daemon({"op": "inbox_mark_read", "args": {"group_id": group_id, "actor_id": actor_id, "event_id": last_id, "by": by}})
                    if mark.get("ok"):
                        _print_json({"ok": True, "result": {"messages": messages, "marked": mark.get("result", {})}})
                        return 0
            _print_json(resp)
            return 0

    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2
    try:
        require_inbox_permission(group, by=by, target_actor_id=actor_id)
    except Exception as e:
        _print_json({"ok": False, "error": {"code": "permission_denied", "message": str(e)}})
        return 2

    messages = unread_messages(group, actor_id=actor_id, limit=limit, kind_filter=kind_filter)  # type: ignore
    cur_event_id, cur_ts = get_cursor(group, actor_id)
    if args.mark_read and messages:
        last = messages[-1]
        last_id = str(last.get("id") or "").strip()
        last_ts = str(last.get("ts") or "")
        if last_id:
            cursor = set_cursor(group, actor_id, event_id=last_id, ts=last_ts)
            read_ev = append_event(
                group.ledger_path,
                kind="chat.read",
                group_id=group.group_id,
                scope_key="",
                by=by,
                data={"actor_id": actor_id, "event_id": last_id},
            )
            _print_json({"ok": True, "result": {"messages": messages, "cursor": cursor, "event": read_ev}})
            return 0

    _print_json({"ok": True, "result": {"messages": messages, "cursor": {"event_id": cur_event_id, "ts": cur_ts}}})
    return 0

def cmd_read(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    actor_id = str(args.actor_id or "").strip()
    by = str(args.by or "user").strip()
    event_id = str(args.event_id or "").strip()

    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    if not actor_id:
        _print_json({"ok": False, "error": {"code": "missing_actor_id", "message": "missing actor_id"}})
        return 2
    if not event_id:
        _print_json({"ok": False, "error": {"code": "missing_event_id", "message": "missing event_id"}})
        return 2

    if _ensure_daemon_running():
        resp = call_daemon({"op": "inbox_mark_read", "args": {"group_id": group_id, "actor_id": actor_id, "event_id": event_id, "by": by}})
        _print_json(resp)
        return 0 if resp.get("ok") else 2

    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2
    try:
        require_inbox_permission(group, by=by, target_actor_id=actor_id)
    except Exception as e:
        _print_json({"ok": False, "error": {"code": "permission_denied", "message": str(e)}})
        return 2
    ev = find_event(group, event_id)
    if ev is None:
        _print_json({"ok": False, "error": {"code": "event_not_found", "message": f"event not found: {event_id}"}})
        return 2
    ts = str(ev.get("ts") or "")
    cursor = set_cursor(group, actor_id, event_id=event_id, ts=ts)
    read_ev = append_event(
        group.ledger_path,
        kind="chat.read",
        group_id=group.group_id,
        scope_key="",
        by=by,
        data={"actor_id": actor_id, "event_id": event_id},
    )
    _print_json({"ok": True, "result": {"cursor": cursor, "event": read_ev}})
    return 0

def cmd_prompt(args: argparse.Namespace) -> int:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    actor_id = str(args.actor_id or "").strip()
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2
    if not actor_id:
        _print_json({"ok": False, "error": {"code": "missing_actor_id", "message": "missing actor id"}})
        return 2

    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2

    actor = None
    for item in list_actors(group):
        if item.get("id") == actor_id:
            actor = item
            break
    if actor is None:
        _print_json({"ok": False, "error": {"code": "actor_not_found", "message": f"actor not found: {actor_id}"}})
        return 2
    prompt = render_actor_prompt(group=group, actor=actor)

    _print_json({"ok": True, "result": {"group_id": group_id, "actor_id": actor_id, "prompt": prompt}})
    return 0
