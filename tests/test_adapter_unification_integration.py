import argparse
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cccc.daemon.ops import adapter_helpers
from cccc.ports.web.routes import messaging as web_messaging
from cccc.ports.web.schemas import RouteContext, SendRequest


def _anonymous_request() -> SimpleNamespace:
    principal = SimpleNamespace(kind="anonymous", user_id="", is_admin=False)
    return SimpleNamespace(state=SimpleNamespace(principal=principal))


def _build_route_context(daemon):
    return RouteContext(
        home=Path("/tmp"),
        version="test",
        web_mode="normal",
        read_only=False,
        exhibit_cache_ttl_s=0.0,
        exhibit_allow_terminal=False,
        dist_dir=None,
        daemon=daemon,
        cached_json=daemon,
        apply_web_logging=lambda **_: None,
    )


def _get_http_send_endpoint():
    async def _unused_daemon(_req):
        return {"ok": True}

    for router in web_messaging.create_routers(_build_route_context(_unused_daemon)):
        for route in router.routes:
            if getattr(route, "path", "") == "/api/v1/groups/{group_id}/send":
                return route.endpoint
    raise AssertionError("send endpoint not found")


def _capture_cli_send_request() -> dict:
    from cccc.cli import messaging_cmds

    captured = {}
    args = argparse.Namespace(
        group="g-sync",
        to=["peer2"],
        priority="attention",
        reply_required="true",
        by="peer1",
        text="hello",
        path="",
    )

    def _fake_call(req):
        captured["req"] = req
        return {"ok": True, "result": {"event": {"id": "ev-cli"}}}

    fake_group = SimpleNamespace(doc={})
    with (
        patch.object(messaging_cmds, "_resolve_group_id", return_value="g-sync"),
        patch.object(messaging_cmds, "load_group", return_value=fake_group),
        patch.object(messaging_cmds, "_ensure_daemon_running", return_value=True),
        patch.object(messaging_cmds, "call_daemon", side_effect=_fake_call),
        patch.object(messaging_cmds, "_print_json"),
    ):
        exit_code = messaging_cmds.cmd_send(args)

    assert exit_code == 0
    return captured["req"]


def _capture_http_send_request() -> dict:
    captured = {}

    async def _fake_daemon(req):
        captured["req"] = req
        return {"ok": True, "result": {"event": {"id": "ev-http"}}}

    endpoint = web_messaging.create_routers(_build_route_context(_fake_daemon))[0].routes[0].endpoint

    async def _invoke():
        return await endpoint(
            _anonymous_request(),
            "g-sync",
            SendRequest(
                text="hello",
                by="peer1",
                to=["peer2"],
                path="",
                priority="attention",
                reply_required=True,
                refs=[],
            ),
        )

    result = asyncio.run(_invoke())
    assert result["ok"] is True
    return captured["req"]


def _capture_mcp_send_request() -> dict:
    from cccc.ports.mcp.handlers import cccc_messaging

    captured = {}

    def _fake_call(req):
        captured["req"] = req
        return {"ok": True, "event_id": "ev-mcp"}

    with (
        patch.object(cccc_messaging, "_call_daemon_or_raise", side_effect=_fake_call),
        patch.object(cccc_messaging, "load_group", return_value=None),
    ):
        result = cccc_messaging.message_send(
            group_id="g-sync",
            actor_id="peer1",
            text="hello",
            to=["peer2"],
            priority="attention",
            reply_required="true",
            refs=[],
        )

    assert result["ok"] is True
    return captured["req"]


def test_cli_send_uses_shared_normalize_priority() -> None:
    from cccc.cli import messaging_cmds

    assert messaging_cmds.normalize_priority is adapter_helpers.normalize_priority
    source = inspect.getsource(messaging_cmds.cmd_send)
    assert "normalize_priority(" in source
    assert "build_daemon_request(" in source


def test_http_send_uses_shared_normalize_priority() -> None:
    assert web_messaging.normalize_priority is adapter_helpers.normalize_priority
    source = inspect.getsource(_get_http_send_endpoint())
    assert "normalize_priority(req.priority)" in source
    assert "build_daemon_request(" in source


def test_mcp_send_uses_shared_normalize() -> None:
    from cccc.ports.mcp.handlers import cccc_messaging

    assert cccc_messaging.normalize_priority is adapter_helpers.normalize_priority
    assert cccc_messaging.normalize_reply_required is adapter_helpers.normalize_reply_required
    source = inspect.getsource(cccc_messaging.message_send)
    assert "normalize_priority(priority)" in source
    assert "normalize_reply_required(reply_required)" in source
    assert "build_daemon_request(" in source


def test_cli_no_local_fallback() -> None:
    from cccc.cli import messaging_cmds

    cmd_send_source = inspect.getsource(messaging_cmds.cmd_send)
    module_path = inspect.getsourcefile(messaging_cmds)
    assert module_path is not None
    module_source = Path(module_path).read_text(encoding="utf-8")

    assert "append_event(" not in cmd_send_source
    assert "_ensure_daemon_running()" in cmd_send_source
    assert "call_daemon(" in cmd_send_source
    assert "# Fallback: local execution" not in module_source


def test_cli_daemon_unavailable_returns_error() -> None:
    from cccc.cli import messaging_cmds

    printed = []
    args = argparse.Namespace(
        group="g-sync",
        to=["peer2"],
        priority="normal",
        reply_required=False,
        by="peer1",
        text="hello",
        path="",
    )

    with (
        patch.object(messaging_cmds, "_resolve_group_id", return_value="g-sync"),
        patch.object(messaging_cmds, "load_group", return_value=SimpleNamespace(doc={})),
        patch.object(messaging_cmds, "_ensure_daemon_running", return_value=False),
        patch.object(messaging_cmds, "call_daemon", side_effect=AssertionError("call_daemon should not run")),
        patch.object(messaging_cmds, "append_event", side_effect=AssertionError("local fallback should not run")),
        patch.object(messaging_cmds, "_print_json", side_effect=printed.append),
    ):
        exit_code = messaging_cmds.cmd_send(args)

    assert exit_code == 2
    assert printed == [
        {
            "ok": False,
            "error": {"code": "daemon_unavailable", "message": "ccccd unavailable"},
        }
    ]


def test_build_daemon_request_consistent() -> None:
    cli_req = _capture_cli_send_request()
    http_req = _capture_http_send_request()
    mcp_req = _capture_mcp_send_request()

    expected_core = {
        "group_id": "g-sync",
        "text": "hello",
        "by": "peer1",
        "to": ["peer2"],
        "path": "",
        "priority": "attention",
        "reply_required": True,
    }

    for req in (cli_req, http_req, mcp_req):
        assert req["op"] == "send"
        assert set(req.keys()) == {"op", "args"}
        for key, value in expected_core.items():
            assert req["args"][key] == value

    assert cli_req == adapter_helpers.build_daemon_request("send", **expected_core)
    assert http_req == adapter_helpers.build_daemon_request(
        "send",
        **expected_core,
        src_group_id="",
        src_event_id="",
        client_id="",
        refs=[],
        sender_user_id=None,
        sender_is_admin=False,
    )
    assert mcp_req == adapter_helpers.build_daemon_request("send", **expected_core, refs=[])
