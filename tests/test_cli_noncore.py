from __future__ import annotations

from unittest.mock import patch

import pytest


def test_capability_help() -> None:
    from cccc import cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["capability", "--help"])
    assert exc.value.code == 0


def test_memory_help() -> None:
    from cccc import cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["memory", "--help"])
    assert exc.value.code == 0


def test_coordination_help() -> None:
    from cccc import cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["coordination", "--help"])
    assert exc.value.code == 0


def test_agent_state_help() -> None:
    from cccc import cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["agent-state", "--help"])
    assert exc.value.code == 0


def test_capability_builds_correct_request() -> None:
    from cccc import cli

    parser = cli.build_parser()
    args = parser.parse_args(
        ["capability", "cccc_space", "status", "--group", "g_test", "--args", '{"lane":"work"}']
    )
    calls: list[dict] = []

    def _fake_call_daemon(req: dict) -> dict:
        calls.append(req)
        return {"ok": True, "result": {"status": "ok"}}

    with patch.object(cli, "_ensure_daemon_running", return_value=True), patch.object(
        cli, "call_daemon", side_effect=_fake_call_daemon
    ), patch.object(cli, "_print_json"):
        code = args.func(args)

    assert code == 0
    assert len(calls) == 1
    req = calls[0]
    assert req.get("op") == "capability_tool_call"
    req_args = req.get("args") if isinstance(req.get("args"), dict) else {}
    assert req_args.get("group_id") == "g_test"
    assert req_args.get("actor_id") == "user"
    assert req_args.get("by") == "user"
    assert req_args.get("tool_name") == "cccc_space"
    tool_args = req_args.get("arguments") if isinstance(req_args.get("arguments"), dict) else {}
    assert tool_args.get("action") == "status"
    assert tool_args.get("lane") == "work"


def test_memory_builds_correct_request() -> None:
    from cccc import cli

    parser = cli.build_parser()
    args = parser.parse_args(["memory", "write", "--group", "g_test", "--key", "daily", "--value", "hello"])
    calls: list[dict] = []

    def _fake_call_daemon(req: dict) -> dict:
        calls.append(req)
        return {"ok": True, "result": {"written": True}}

    with patch.object(cli, "_ensure_daemon_running", return_value=True), patch.object(
        cli, "call_daemon", side_effect=_fake_call_daemon
    ), patch.object(cli, "_print_json"):
        code = args.func(args)

    assert code == 0
    assert len(calls) == 1
    req = calls[0]
    assert req.get("op") == "memory_reme_write"
    req_args = req.get("args") if isinstance(req.get("args"), dict) else {}
    assert req_args.get("group_id") == "g_test"
    assert req_args.get("target") == "daily"
    assert req_args.get("content") == "hello"
