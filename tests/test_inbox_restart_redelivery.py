from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1 import ChatMessageData
from cccc.daemon.actors import actor_lifecycle_ops
from cccc.kernel.actors import add_actor
from cccc.kernel.group import create_group, load_group
from cccc.kernel.inbox import get_cursor, set_cursor, unread_messages
from cccc.kernel.ledger import append_event
from cccc.kernel.registry import load_registry

ACTOR_ID = "peer1"
FOREMAN_ID = "foreman1"
INBOX_LIMIT = 10


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("CCCC_HOME", str(home))
    return home


def _create_group_with_actor() -> Any:
    group = create_group(load_registry(), title="inbox-restart-redelivery", topic="")
    add_actor(group, actor_id=FOREMAN_ID, runtime="codex", runner="pty", enabled=True)
    add_actor(group, actor_id=ACTOR_ID, runtime="codex", runner="pty", enabled=True)
    reloaded = load_group(group.group_id)
    assert reloaded is not None
    return reloaded


def _successful_start_actor_process(*_args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "success": True,
        "event": {"kind": "actor.start", "actor_id": ACTOR_ID},
        "effective_runner": kwargs.get("runner"),
    }


def _start_actor(group_id: str, actor_id: str = ACTOR_ID) -> Any:
    return actor_lifecycle_ops.handle_actor_start(
        {"group_id": group_id, "actor_id": actor_id, "by": "user"},
        foreman_id=lambda _group: FOREMAN_ID,
        maybe_reset_automation_on_foreman_change=lambda *_args, **_kwargs: None,
        start_actor_process=_successful_start_actor_process,
        effective_runner_kind=lambda runner: runner,
        get_actor_profile=lambda _profile_id: None,
        load_actor_profile_secrets=lambda _profile_id: {},
        update_actor_private_env=lambda *_args, **_kwargs: {},
    )


def _append_chat_message(group: Any, text: str) -> dict[str, Any]:
    return append_event(
        group.ledger_path,
        kind="chat.message",
        group_id=group.group_id,
        scope_key="",
        by="user",
        data=ChatMessageData(text=text, to=[ACTOR_ID]).model_dump(),
    )


def test_restart_clears_cursor(isolated_home: Path) -> None:
    group = _create_group_with_actor()
    message = _append_chat_message(group, "first")
    set_cursor(group, ACTOR_ID, event_id=str(message["id"]), ts=str(message["ts"]))

    response = _start_actor(group.group_id)

    assert response.ok is True
    assert get_cursor(group, ACTOR_ID) == ("", "")


def test_redelivery_after_restart(isolated_home: Path) -> None:
    group = _create_group_with_actor()
    first = _append_chat_message(group, "first")
    second = _append_chat_message(group, "second")
    set_cursor(group, ACTOR_ID, event_id=str(second["id"]), ts=str(second["ts"]))
    assert unread_messages(group, actor_id=ACTOR_ID, limit=INBOX_LIMIT) == []

    response = _start_actor(group.group_id)
    messages = unread_messages(group, actor_id=ACTOR_ID, limit=INBOX_LIMIT)
    message_ids = {str(message.get("id") or "") for message in messages}

    assert response.ok is True
    assert {str(first["id"]), str(second["id"])} <= message_ids


def test_cursor_delete_failure_logs_warning(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    group = _create_group_with_actor()

    def fail_delete_cursor(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("cursor delete failed")

    monkeypatch.setattr(actor_lifecycle_ops, "delete_cursor", fail_delete_cursor)
    with caplog.at_level(logging.WARNING, logger="cccc.daemon.actors"):
        response = _start_actor(group.group_id)

    assert response.ok is True
    assert "Failed to reset inbox cursor for actor peer1 on restart" in caplog.text
