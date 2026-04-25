# Directory Structure

> How backend code is organized in this project.

---

## Overview

cccc-pair is a Python multi-agent delivery kernel. The project uses a hexagonal (ports & adapters) architecture with a long-running daemon, a kernel domain layer, and CLI entry points.

**Language**: Python 3.9+ | **Package manager**: setuptools | **Source root**: `src/`

---

## Directory Layout

```
src/cccc/
├── cli/                  # CLI command handlers (argparse)
│   ├── __init__.py       # Custom _CliModule proxy for star imports
│   ├── common.py         # Shared helpers: call_daemon(), _print_json()
│   ├── actor_cmds.py     # cmd_actor_* functions
│   ├── agent_cmds.py     # cmd_agent_* functions
│   ├── im_cmds.py        # cmd_im_* functions
│   ├── space_cmds.py     # cmd_space_* functions
│   ├── system_cmds.py    # cmd_system_* functions
│   ├── workflow_cmds.py  # cmd_workflow_* functions
│   └── daemon_lifecycle.py  # DaemonLifecycleManager
├── contracts/            # Pydantic schemas, versioned
│   └── v1/              # Current contract version
│       ├── event.py     # EventKind literal + per-event BaseModel data classes
│       ├── actor.py     # Actor, ActorRole, AgentRuntime
│       ├── message.py   # ChatMessageData, ChatStreamData
│       ├── ipc.py       # Daemon IPC request/response contracts
│       └── ralph_ipc.py # Ralph subsystem IPC types
├── daemon/               # Long-running server process (ccccd)
│   ├── server.py        # Unix-socket JSON IPC server + call_daemon() client
│   ├── actors/          # Actor pool, profile store, lifecycle
│   ├── context/         # Context storage & sync
│   ├── foreman/         # Workflow orchestration engine
│   ├── group/           # Group lifecycle, bootstrap
│   ├── memory/          # Memory management
│   ├── ops/             # Operation handlers (one per domain)
│   └── space/           # Group space runtime
├── kernel/               # Core domain logic (no I/O dependencies)
│   ├── workflow_state_engine.py  # State machine for workflows
│   ├── workflow_state_types.py   # Transition exceptions
│   ├── group.py         # Group CRUD (file-based)
│   ├── actors.py        # Actor CRUD (file-based)
│   ├── ledger.py        # Append-only JSONL event log
│   ├── inbox.py         # Message cursor and unread tracking
│   └── settings.py      # Configuration resolution
├── ports/                # External adapters (inbound)
│   ├── web/             # FastAPI HTTP/WebSocket server
│   ├── im/              # Messaging platform adapters
│   └── mcp/             # Model Context Protocol adapters
├── providers/            # External integrations (outbound)
│   └── notebooklm/     # NotebookLM provider
├── ralph/                # Plan validator & AI agent subsystem
│   ├── cli.py           # Standalone `ralph` CLI entry point
│   ├── core.py          # suggest(), verify() top-level API
│   ├── agent.py         # AI-powered validation agent
│   ├── validator.py     # Rule-based plan validation (E_* codes)
│   ├── models.py        # Plan, ValidationReport, ValidationIssue
│   └── plan_io.py       # YAML/JSON plan file loading
├── resources/            # Static assets (yaml, md)
├── runners/              # Task execution (pty, headless)
├── util/                 # Shared utilities
│   ├── obslog.py        # JSONL structured logging setup
│   ├── file_lock.py     # Advisory file locking
│   ├── process.py       # Subprocess management, signal handling
│   ├── fs.py            # Filesystem helpers
│   ├── time.py          # UTC timestamp helpers
│   └── conv.py          # Type coercion (coerce_bool, etc.)
├── vendor/               # Vendored third-party code (reme)
├── daemon_main.py        # ccccd entry point: spawn & manage daemon
├── paths.py              # CCCC_HOME and path resolution
└── __init__.py           # Package metadata (__version__)
```

**Root-level directories:**
- `tests/` — All tests (flat, not mirroring src structure)
- `web/` — Frontend (Vite + TypeScript, separate from backend)
- `ralph/` — Standalone Ralph package (separate pyproject.toml, own tests)

---

## Module Organization

### Adding a new CLI command

1. Create or extend a `cmd_*` function in the appropriate `cli/*_cmds.py` module
2. Export it in `__all__`
3. Wire it into the argparse subparser in `cli/__init__.py`

```python
# src/cccc/cli/actor_cmds.py
__all__ = ["cmd_actor_add", "cmd_actor_remove", "cmd_actor_list"]

def cmd_actor_add(args: argparse.Namespace) -> None:
    ...
```

### Adding a new daemon operation

1. Create a handler in `daemon/ops/` (one file per domain)
2. Register it in the daemon's request dispatcher in `daemon/server.py`

### Adding a new contract

1. Add a new Pydantic model in `contracts/v1/`
2. Use `ConfigDict(extra="forbid")` to catch schema drift

---

## Naming Conventions

| Item | Convention | Example |
|------|-----------|---------|
| Python files | `snake_case.py` | `workflow_state_engine.py` |
| CLI command functions | `cmd_<noun>_<verb>` | `cmd_actor_add` |
| Custom exceptions | `<Domain><Action>Error` | `PlanLoadError`, `LockUnavailableError` |
| Contract models | `PascalCase` + `Data` suffix for payloads | `GroupCreateData`, `ChatMessageData` |
| Event kinds | `<domain>.<action>` dot-notation | `"group.create"`, `"chat.message"` |

---

## Entry Points

Defined in `pyproject.toml [project.scripts]`:

| Command | Module | Purpose |
|---------|--------|---------|
| `cccc` | `cccc.cli:main` | CLI client |
| `ccccd` | `cccc.daemon_main:main` | Daemon server |
| `ralph` | `cccc.ralph.cli:main` | Plan validator |
