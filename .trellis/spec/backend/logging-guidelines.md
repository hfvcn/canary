# Logging Guidelines

> How logging is done in this project.

---

## Overview

The project uses Python's **stdlib `logging` module** with a custom JSONL formatter for structured, machine-readable output. No third-party logging libraries (structlog, loguru, etc.).

---

## Setup

Logging is configured once per process via `src/cccc/util/obslog.py`:

```python
from cccc.util.obslog import setup_root_json_logging

setup_root_json_logging(component="daemon", level="INFO")
```

- Call **once** at process start (daemon entry, CLI entry)
- `component` identifies the process in log output (e.g., `"daemon"`, `"ralph"`, `"cli"`)
- Idempotent: repeated calls are no-ops unless `force=True`

---

## Log Format

Every log line is a JSON object (JSONL):

```json
{"ts":"2026-04-26T12:00:00Z","level":"INFO","logger":"cccc.daemon.server","component":"daemon","msg":"request handled","group_id":"g-abc","op":"actor.add"}
```

### Standard fields (always present)

| Field | Source |
|-------|--------|
| `ts` | UTC ISO 8601 timestamp |
| `level` | DEBUG, INFO, WARNING, ERROR |
| `logger` | Python logger name (`__name__`) |
| `component` | Process component set at init |
| `msg` | Log message |

### Correlation fields (optional, via `extra={}`)

| Field | When to use |
|-------|-------------|
| `trace_id` | Cross-process request tracing |
| `op` | Current operation name |
| `group_id` | Group context |
| `scope_key` | Scope context |
| `actor_id` | Actor context |
| `event_id` | Event being processed |
| `platform` | External platform identifier |

---

## Log Levels

| Level | Use for |
|-------|---------|
| `DEBUG` | Internal state transitions, detailed tracing (disabled in production) |
| `INFO` | Normal operations: requests handled, lifecycle events, process start/stop |
| `WARNING` | Degraded operation, deprecated usage, recoverable errors |
| `ERROR` | Unrecoverable failures, unhandled exceptions |

---

## How to Log

```python
import logging
log = logging.getLogger(__name__)

# Simple message
log.info("daemon started")

# With correlation context
log.info("request handled", extra={"op": "actor.add", "group_id": gid})

# With exception info
try:
    ...
except Exception:
    log.error("request failed", exc_info=True, extra={"op": op_name})
```

---

## What to Log

- Process lifecycle events (start, stop, reload)
- IPC request/response summaries (not full payloads)
- State transitions in the workflow engine
- External API calls to providers
- File lock acquisition/release (at DEBUG level)

---

## What NOT to Log

| Item | Why |
|------|-----|
| Full message content / chat payloads | Privacy; may contain user data |
| Access tokens or secrets | Security |
| Large data structures | Performance; use DEBUG level if essential |
| Routine polling with no state change | Log noise; only log when something changes |

---

## Forbidden Patterns

| Pattern | Why |
|---------|-----|
| `print()` for operational logging | Use `logging.getLogger(__name__)` — print bypasses the JSONL formatter |
| `structlog`, `loguru`, or other third-party loggers | Not in dependencies; project standardizes on stdlib `logging` |
| Creating custom `logging.Handler` subclasses | Use the centralized `setup_root_json_logging()` from `obslog.py` |
| Logging inside the `JsonlFormatter.format()` method | Causes infinite recursion; the formatter is designed to never crash |
