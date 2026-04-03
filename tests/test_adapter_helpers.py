from __future__ import annotations

import math

import pytest

from cccc.daemon.ops.adapter_helpers import (
    build_daemon_request,
    normalize_priority,
    normalize_reply_required,
    resolve_group_and_project_root,
    resolve_sender_actor,
)


def test_build_daemon_request_wraps_args() -> None:
    assert build_daemon_request("send", group_id="g1", text="hi") == {
        "op": "send",
        "args": {"group_id": "g1", "text": "hi"},
    }


def test_resolve_group_and_project_root_prefers_direct_project_root() -> None:
    def daemon_request(payload: dict[str, object]) -> dict[str, object]:
        assert payload == {"op": "group_show", "args": {"group_id": "g1"}}
        return {
            "ok": True,
            "result": {
                "group": {
                    "project_root": "/repo/direct",
                    "active_scope_key": "scope-a",
                    "scopes": [{"scope_key": "scope-a", "url": "/repo/fallback"}],
                }
            },
        }

    group, project_root = resolve_group_and_project_root("g1", daemon_request)

    assert group["project_root"] == "/repo/direct"
    assert project_root == "/repo/direct"


def test_resolve_group_and_project_root_falls_back_to_active_scope_then_first_scope() -> None:
    def daemon_request(payload: dict[str, object]) -> dict[str, object]:
        group_id = payload["args"]["group_id"]
        if group_id == "active":
            return {
                "ok": True,
                "result": {
                    "group": {
                        "active_scope_key": "scope-b",
                        "scopes": [
                            {"scope_key": "scope-a", "url": "/repo/a"},
                            {"scope_key": "scope-b", "url": "/repo/b"},
                        ],
                    }
                },
            }
        return {
            "ok": True,
            "result": {
                "group": {
                    "active_scope_key": "missing",
                    "scopes": [
                        {"scope_key": "scope-a", "url": ""},
                        {"scope_key": "scope-b", "url": "/repo/b"},
                    ],
                }
            },
        }

    _, active_root = resolve_group_and_project_root("active", daemon_request)
    _, fallback_root = resolve_group_and_project_root("fallback", daemon_request)

    assert active_root == "/repo/b"
    assert fallback_root == "/repo/b"


def test_resolve_group_and_project_root_returns_empty_for_failed_response() -> None:
    group, project_root = resolve_group_and_project_root("g1", lambda _: {"ok": False})

    assert group == {}
    assert project_root == ""


def test_resolve_sender_actor_prefers_explicit_by(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCCC_ACTOR_ID", "env-actor")

    assert resolve_sender_actor({}, "assistant-1") == "assistant-1"


def test_resolve_sender_actor_uses_env_then_group_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCCC_ACTOR_ID", "env-actor")
    assert resolve_sender_actor({}, "user") == "env-actor"

    monkeypatch.delenv("CCCC_ACTOR_ID", raising=False)
    assert resolve_sender_actor({"actor_id": "group-actor"}, "user") == "group-actor"
    assert resolve_sender_actor({}, "user") == "user"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "normal"),
        ("attention", "attention"),
        ("urgent", "attention"),
        ("0", "normal"),
        (0, "normal"),
        (1, "attention"),
        (True, "attention"),
        (False, "normal"),
        (math.nan, "normal"),
        ("weird", "normal"),
    ],
)
def test_normalize_priority(value: object, expected: str) -> None:
    assert normalize_priority(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (2.5, True),
        (math.nan, False),
        ("true", True),
        ("YES", True),
        ("0", False),
        ("unknown", False),
        ({}, False),
    ],
)
def test_normalize_reply_required(value: object, expected: bool) -> None:
    assert normalize_reply_required(value) is expected
