from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List

from ...kernel.access_tokens import list_access_tokens
from .streams import sse_jsonl_tail_shared

HIDDEN_MESSAGE_TEXT = ""
HIDDEN_QUOTE_TEXT = ""
SENDER_USER_ID_KEY = "sender_user_id"
SENDER_IS_ADMIN_KEY = "sender_is_admin"


def principal_can_view_message_bodies(principal: Any) -> bool:
    if len(list_access_tokens()) == 0:
        return True
    return bool(getattr(principal, "kind", "") == "user" and getattr(principal, "is_admin", False))


def principal_user_id(principal: Any) -> str:
    return str(getattr(principal, "user_id", "") or "").strip()


def sender_user_id_for_principal(principal: Any) -> str:
    if str(getattr(principal, "kind", "") or "") != "user":
        return ""
    return principal_user_id(principal)


def sender_is_admin_for_principal(principal: Any) -> bool:
    return bool(getattr(principal, "kind", "") == "user" and getattr(principal, "is_admin", False))


def _message_data(event: Dict[str, Any]) -> Dict[str, Any]:
    data = event.get("data")
    return dict(data) if isinstance(data, dict) else {}


def _is_member_message(event: Dict[str, Any]) -> bool:
    if str(event.get("kind") or "") != "chat.message":
        return False
    if str(event.get("by") or "") != "user":
        return False
    return not bool(_message_data(event).get(SENDER_IS_ADMIN_KEY))


def _strip_sender_metadata(event: Dict[str, Any]) -> Dict[str, Any]:
    copied = dict(event)
    data = _message_data(event)
    data.pop(SENDER_USER_ID_KEY, None)
    data.pop(SENDER_IS_ADMIN_KEY, None)
    copied["data"] = data
    return copied


def should_hide_message_body(event: Dict[str, Any], principal: Any) -> bool:
    if principal_can_view_message_bodies(principal):
        return False
    if not _is_member_message(event):
        return False
    sender_user_id = str(_message_data(event).get(SENDER_USER_ID_KEY) or "").strip()
    viewer_user_id = principal_user_id(principal)
    return not (sender_user_id and viewer_user_id and sender_user_id == viewer_user_id)


def redact_message_event(event: Dict[str, Any]) -> Dict[str, Any]:
    redacted = _strip_sender_metadata(event)
    data = _message_data(redacted)
    data["text"] = HIDDEN_MESSAGE_TEXT
    if "quote_text" in data:
        data["quote_text"] = HIDDEN_QUOTE_TEXT
    redacted["data"] = data
    redacted["_member_message"] = True
    redacted["_message_body_hidden"] = True
    return redacted


def present_message_event(event: Dict[str, Any]) -> Dict[str, Any]:
    presented = _strip_sender_metadata(event)
    if _is_member_message(event):
        presented["_member_message"] = True
    return presented


def filter_events_for_principal(
    events: Iterable[Dict[str, Any]],
    principal: Any,
    *,
    drop_hidden_matches: bool = False,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if should_hide_message_body(event, principal):
            if drop_hidden_matches:
                continue
            filtered.append(redact_message_event(event))
            continue
        filtered.append(present_message_event(event))
    return filtered


async def sse_ledger_tail_for_principal(path: Path, principal: Any) -> AsyncIterator[bytes]:
    async for chunk in sse_jsonl_tail_shared(path, event_name="ledger", heartbeat_s=30.0):
        if not chunk.startswith(b"event: ledger\n"):
            yield chunk
            continue
        prefix = b"event: ledger\ndata: "
        if not chunk.startswith(prefix) or not chunk.endswith(b"\n\n"):
            yield chunk
            continue
        raw = chunk[len(prefix):-2]
        try:
            event = json.loads(raw.decode("utf-8"))
        except Exception:
            yield chunk
            continue
        if not isinstance(event, dict):
            yield chunk
            continue
        presented = redact_message_event(event) if should_hide_message_body(event, principal) else present_message_event(event)
        payload = json.dumps(presented, ensure_ascii=False).encode("utf-8")
        yield prefix + payload + b"\n\n"
