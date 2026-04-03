from __future__ import annotations

"""System/daemon/web/mcp CLI command handlers."""

from .common import *  # noqa: F401,F403

__all__ = [
    "cmd_version",
    "cmd_status",
    "cmd_doctor",
    "cmd_web",
    "cmd_mcp",
    "cmd_setup",
    "cmd_context_get",
    "cmd_capability",
    "cmd_memory",
    "cmd_coordination",
    "cmd_agent_state",
    "cmd_daemon",
]


def _require_group_id_for_system_cmd(args: argparse.Namespace) -> str | None:
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if group_id:
        return group_id
    _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
    return None


def _require_daemon_for_system_cmd() -> bool:
    if _ensure_daemon_running():
        return True
    _print_json({"ok": False, "error": {"code": "daemon_unavailable", "message": "daemon unavailable"}})
    return False


def _parse_cli_json_args(raw: Any, *, field: str) -> dict[str, Any] | None:
    try:
        return _parse_json_object_arg(raw, field=field)
    except Exception as e:
        _print_json({"ok": False, "error": {"code": f"invalid_{field}", "message": str(e)}})
        return None

def cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0

def cmd_status(_: argparse.Namespace) -> int:
    """Show overall CCCC status: daemon, groups, actors."""
    from ..kernel.runtime import detect_all_runtimes
    
    home = ensure_home()
    
    # Check daemon
    daemon_resp = call_daemon({"op": "ping"})
    daemon_ok = daemon_resp.get("ok", False)
    
    # Get groups
    groups_resp = call_daemon({"op": "groups"}) if daemon_ok else {"ok": False}
    groups = groups_resp.get("result", {}).get("groups", []) if groups_resp.get("ok") else []
    
    # Get active group
    active = load_active()
    active_group_id = str(active.get("active_group_id") or "").strip()
    
    # Get runtimes
    runtimes = detect_all_runtimes(primary_only=False)
    available_runtimes = [r.name for r in runtimes if r.available]
    
    print(f"CCCC Status")
    print(f"===========")
    print(f"Version:     {__version__}")
    print(f"Home:        {home}")
    print(f"Daemon:      {'running' if daemon_ok else 'stopped'}")
    print(f"Runtimes:    {', '.join(available_runtimes) if available_runtimes else '(none detected)'}")
    print()
    
    if not groups:
        print("Groups:      (none)")
    else:
        print(f"Groups:      {len(groups)}")
        for g in groups:
            gid = str(g.get("group_id") or "")
            title = str(g.get("title") or gid)
            running = g.get("running", False)
            active_mark = " *" if gid == active_group_id else ""
            status = "running" if running else "stopped"
            print(f"  - {title} ({gid}){active_mark} [{status}]")
            
            # Get actors for this group
            if daemon_ok:
                actors_resp = call_daemon({"op": "actor_list", "args": {"group_id": gid}})
                actors = actors_resp.get("result", {}).get("actors", []) if actors_resp.get("ok") else []
                for a in actors:
                    aid = str(a.get("id") or "")
                    role = str(a.get("role") or "peer")
                    enabled = a.get("enabled", False)
                    runtime = str(a.get("runtime") or "codex")
                    runner = str(a.get("runner") or "pty")
                    status = "on" if enabled else "off"
                    print(f"      {aid} ({role}, {runtime}, {runner}) [{status}]")
    
    return 0

def cmd_doctor(args: argparse.Namespace) -> int:
    """Check environment and show available agent runtimes."""
    import shutil
    from ..kernel.runtime import detect_all_runtimes, PRIMARY_RUNTIMES
    
    print("[DOCTOR] CCCC Environment Check")
    print()
    
    # Python version
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    
    # CCCC version
    print(f"CCCC: {__version__}")
    
    # CCCC_HOME
    home = ensure_home()
    print(f"CCCC_HOME: {home}")
    
    # Daemon status
    resp = call_daemon({"op": "ping"})
    if resp.get("ok"):
        r = resp.get("result") if isinstance(resp.get("result"), dict) else {}
        print(f"Daemon: running (pid={r.get('pid')}, version={r.get('version')})")
    else:
        print("Daemon: not running")
    
    print()
    print("Agent Runtimes:")
    
    # Check all runtimes
    all_runtimes = args.all if hasattr(args, 'all') else False
    runtimes = detect_all_runtimes(primary_only=not all_runtimes)
    
    available_count = 0
    for rt in runtimes:
        status = "OK" if rt.available else "NOT FOUND"
        mark = "✓" if rt.available else "✗"
        path_info = f" ({rt.path})" if rt.available else ""
        print(f"  {mark} {rt.name}: {status}{path_info}")
        if rt.available:
            available_count += 1
    
    print()
    if available_count == 0:
        print("No agent runtimes detected. Install one of:")
        print("  - Claude Code: https://claude.ai/code")
        print("  - Codex CLI: https://github.com/openai/codex")
        print("  - Droid: https://github.com/anthropics/droid")
        print("  - OpenCode: https://github.com/opencode-ai/opencode")
    else:
        print(f"{available_count} runtime(s) available.")
        print()
        print("Quick start:")
        print(f"  cccc setup --runtime {runtimes[0].name if runtimes[0].available else 'claude'}")
        print("  cccc attach .")
        print("  cccc actor add my-agent --runtime <name>")
        print("  cccc")
    
    return 0

def cmd_web(args: argparse.Namespace) -> int:
    from ..ports.web.main import main as web_main

    argv: list[str] = []
    if str(args.host or "").strip():
        argv.extend(["--host", str(args.host)])
    if args.port is not None:
        argv.extend(["--port", str(int(args.port))])
    if bool(getattr(args, "exhibit", False)):
        argv.append("--exhibit")
    elif str(getattr(args, "mode", "") or "").strip():
        argv.extend(["--mode", str(getattr(args, "mode"))])
    if bool(args.reload):
        argv.append("--reload")
    if str(args.log_level or "").strip():
        argv.extend(["--log-level", str(args.log_level)])
    return int(web_main(argv))

def cmd_mcp(args: argparse.Namespace) -> int:
    from ..ports.mcp.main import main as mcp_main

    return int(mcp_main())

def cmd_setup(args: argparse.Namespace) -> int:
    """Setup CCCC MCP for agent runtimes (configure MCP, print guidance)."""
    from ..daemon.mcp_install import build_mcp_add_command
    from ..kernel.runtime import detect_runtime
    from ..kernel.runtime import get_cccc_mcp_stdio_command

    runtime = str(args.runtime or "").strip()
    project_path = Path(args.path or ".").resolve()

    # Supported runtimes
    # - claude/codex/droid/amp/auggie/neovate/gemini: MCP setup can be automated via their CLIs
    # - cursor/kilocode/opencode/copilot: MCP setup is manual (cccc prints config guidance)
    # - custom: user-provided runtime; MCP setup is manual (generic guidance only)
    SUPPORTED_RUNTIMES = [
        "claude",
        "codex",
        "droid",
        "amp",
        "auggie",
        "neovate",
        "gemini",
        "cursor",
        "kilocode",
        "opencode",
        "copilot",
        "custom",
    ]

    if runtime and runtime not in SUPPORTED_RUNTIMES:
        _print_json({
            "ok": False,
            "error": {
                "code": "unsupported_runtime",
                "message": f"Unsupported runtime: {runtime}. Supported: {', '.join(SUPPORTED_RUNTIMES)}",
            },
        })
        return 2

    results: dict[str, Any] = {"mcp": {}, "notes": []}

    cccc_cmd = get_cccc_mcp_stdio_command()
    auto_mcp_runtimes = tuple(name for name in SUPPORTED_RUNTIMES if name != "custom")
    AUTO_SETUP_TIMEOUT_SECONDS = 30

    def _cmd_line(parts: list[str]) -> str:
        return " ".join(shlex.quote(p) for p in parts)

    def _manual_setup(rt: str, *, runtime_available: bool) -> None:
        cmd = build_mcp_add_command(rt) or cccc_cmd
        display_cmd = cmd
        if runtime_available:
            try:
                display_cmd = resolve_subprocess_argv(cmd)
            except FileNotFoundError:
                display_cmd = cmd
        results["mcp"][rt] = {"mode": "manual", "command": _cmd_line(display_cmd)}
        if runtime_available:
            results["notes"].append(f"{rt}: MCP CLI failed; run the command shown in result.mcp.{rt}.command")
        else:
            results["notes"].append(f"{rt}: CLI not found; run the command shown in result.mcp.{rt}.command")

    def _auto_setup(rt: str) -> None:
        runtime_info = detect_runtime(rt)
        add_cmd = build_mcp_add_command(rt)
        if not add_cmd:
            _manual_setup(rt, runtime_available=runtime_info.available)
            return

        try:
            result = subprocess.run(
                resolve_subprocess_argv(add_cmd),
                capture_output=True,
                text=True,
                timeout=AUTO_SETUP_TIMEOUT_SECONDS,
                cwd=str(project_path),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _manual_setup(rt, runtime_available=runtime_info.available)
            return

        if result.returncode == 0:
            results["mcp"][rt] = {"mode": "auto", "status": "added"}
            return
        _manual_setup(rt, runtime_available=runtime_info.available)

    # Runtime-specific setup
    runtimes_to_setup = [runtime] if runtime else SUPPORTED_RUNTIMES

    for rt in runtimes_to_setup:
        if rt in auto_mcp_runtimes:
            _auto_setup(rt)

        elif rt == "custom":
            results["mcp"]["custom"] = {
                "mode": "manual",
                "hint": f"Add an MCP stdio server named 'cccc' that runs: {_cmd_line(cccc_cmd)}",
            }
            results["notes"].append(
                "custom: MCP setup depends on your runtime. Add an MCP stdio server named 'cccc' that runs the command in result.mcp.custom.hint."
            )

    # Clean up empty notes
    if not results["notes"]:
        del results["notes"]

    _print_json({"ok": True, "result": results})
    return 0


def cmd_context_get(args: argparse.Namespace) -> int:
    """Get context snapshot (coordination, board, tasks_summary, agent_states)."""
    group_id = _resolve_group_id(getattr(args, "group", ""))
    if not group_id:
        _print_json({"ok": False, "error": {"code": "missing_group_id", "message": "missing group_id (no active group?)"}})
        return 2

    if _ensure_daemon_running():
        resp = call_daemon(
            {
                "op": "context_get",
                "args": {
                    "group_id": group_id,
                    "include_archived": bool(getattr(args, "include_archived", False)),
                },
            }
        )
        _print_json(resp)
        return 0 if resp.get("ok") else 2

    group = load_group(group_id)
    if group is None:
        _print_json({"ok": False, "error": {"code": "group_not_found", "message": f"group not found: {group_id}"}})
        return 2
    from ..daemon.context.context_ops import context_get

    result = context_get(group_id=group_id, include_archived=bool(getattr(args, "include_archived", False)))
    _print_json({"ok": True, "result": result})
    return 0


def cmd_capability(args: argparse.Namespace) -> int:
    """Run a capability tool via daemon."""
    group_id = _require_group_id_for_system_cmd(args)
    if not group_id:
        return 2
    tool_arguments = _parse_cli_json_args(getattr(args, "tool_arguments", ""), field="args")
    if tool_arguments is None:
        return 2
    if not _require_daemon_for_system_cmd():
        return 2
    tool_arguments["action"] = str(getattr(args, "action", "") or "").strip()
    resp = call_daemon(
        {
            "op": "capability_tool_call",
            "args": {
                "group_id": group_id,
                "actor_id": "user",
                "by": "user",
                "capability_id": str(getattr(args, "capability_id", "") or "").strip(),
                "tool_name": str(getattr(args, "tool_name", "") or "").strip(),
                "arguments": tool_arguments,
            },
        }
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 2


def cmd_memory(args: argparse.Namespace) -> int:
    """Memory operations via daemon."""
    group_id = _require_group_id_for_system_cmd(args)
    if not group_id:
        return 2
    action = str(getattr(args, "action", "") or "").strip().lower()
    op_map = {
        "layout_get": "memory_reme_layout_get",
        "search": "memory_reme_search",
        "get": "memory_reme_get",
        "write": "memory_reme_write",
    }
    op = op_map.get(action)
    if not op:
        _print_json({"ok": False, "error": {"code": "invalid_action", "message": f"unsupported memory action: {action}"}})
        return 2
    req_args: dict[str, Any] = {"group_id": group_id}
    key = str(getattr(args, "key", "") or "").strip()
    value = str(getattr(args, "value", "") or "")
    if action == "search" and key:
        req_args["query"] = key
    elif action == "get" and key:
        req_args["path"] = key
    elif action == "write":
        if key:
            req_args["target"] = key
        if value:
            req_args["content"] = value
    if not _require_daemon_for_system_cmd():
        return 2
    resp = call_daemon({"op": op, "args": req_args})
    _print_json(resp)
    return 0 if resp.get("ok") else 2


def cmd_coordination(args: argparse.Namespace) -> int:
    """Coordination operations via daemon."""
    group_id = _require_group_id_for_system_cmd(args)
    if not group_id:
        return 2
    action = str(getattr(args, "action", "") or "status").strip().lower()
    if not _require_daemon_for_system_cmd():
        return 2
    if action in {"status", "get"}:
        resp = call_daemon({"op": "context_get", "args": {"group_id": group_id, "include_archived": False}})
    else:
        note = str(getattr(args, "note", "") or "").strip()
        kind = "handoff" if action == "add_handoff" else "decision"
        resp = call_daemon(
            {
                "op": "context_sync",
                "args": {
                    "group_id": group_id,
                    "by": "user",
                    "ops": [{"op": "coordination.note.add", "kind": kind, "summary": note}],
                },
            }
        )
    _print_json(resp)
    return 0 if resp.get("ok") else 2


def cmd_agent_state(args: argparse.Namespace) -> int:
    """Query agent state via daemon."""
    group_id = _require_group_id_for_system_cmd(args)
    if not group_id:
        return 2
    if not _require_daemon_for_system_cmd():
        return 2
    resp = call_daemon({"op": "context_get", "args": {"group_id": group_id, "include_archived": True}})
    actor_id = str(getattr(args, "actor", "") or "").strip().lower()
    if resp.get("ok") and actor_id:
        result = resp.get("result") if isinstance(resp.get("result"), dict) else {}
        states = result.get("agent_states") if isinstance(result.get("agent_states"), list) else []
        target = next(
            (
                item
                for item in states
                if isinstance(item, dict) and str(item.get("id") or "").strip().lower() == actor_id
            ),
            None,
        )
        resp = {"ok": True, "result": {"agent_state": target, "version": result.get("version")}}
    _print_json(resp)
    return 0 if resp.get("ok") else 2

def cmd_daemon(args: argparse.Namespace) -> int:
    if args.action == "status":
        resp = call_daemon({"op": "ping"})
        if resp.get("ok"):
            r = resp.get("result") if isinstance(resp.get("result"), dict) else {}
            print(f"ccccd: running pid={r.get('pid')} version={r.get('version')}")
            return 0
        print("ccccd: not running")
        return 1

    if args.action == "start":
        if _ensure_daemon_running():
            print("ccccd: running")
            return 0
        print("ccccd: failed to start")
        return 1

    if args.action == "stop":
        resp = call_daemon({"op": "shutdown"})
        if resp.get("ok"):
            print("ccccd: shutdown requested")
            return 0
        print("ccccd: not running")
        return 0

    return 2
