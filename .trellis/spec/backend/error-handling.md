# Error Handling

> How errors are handled in this project.

---

## Overview

The project uses **traditional raise/except** for error propagation, with a **ResultDict classification pattern** at the daemon IPC boundary. There are no Result/Either monads.

---

## Error Types

Custom exceptions are domain-scoped and inherit from standard Python exceptions:

```python
# Kernel (workflow state machine)
class PreTransitionVetoed(RuntimeError):   # src/cccc/kernel/workflow_state_types.py
    code: str; message: str

class TransitionRejected(Exception):       # src/cccc/kernel/workflow_state_types.py
    alert_type: str; message: str; evidence: dict

# Ralph (plan validation)
class PlanLoadError(Exception): ...        # src/cccc/ralph/plan_io.py
class SchemaUnknownFieldError(Exception): ...

# Daemon (runtime)
class PromptMinimaOverflow(ValueError): ...   # daemon/foreman/prompt_builder.py
class ProfileRevisionMismatchError(RuntimeError): ...
class ActorProfileNotFoundError(RuntimeError): ...
class SpaceProviderError(RuntimeError): ...

# Utilities
class LockUnavailableError(RuntimeError): ...  # util/file_lock.py

# Ports
class MCPError(Exception): ...                 # ports/mcp/common.py
```

**Convention**: Inherit from `RuntimeError` for operational failures, `Exception` for domain logic errors, `ValueError` for invalid input.

---

## Error Classification at IPC Boundary

Daemon ops use a ResultDict pattern to normalize exceptions into structured JSON responses. See `src/cccc/daemon/ops/workflow_task_ops.py`:

```python
ResultDict = Dict[str, Any]

def _success(result: ResultDict) -> ResultDict:
    return {"ok": True, "result": dict(result), "error": {}}

def _failure(code: str, message: str) -> ResultDict:
    return {"ok": False, "result": {}, "error": {"code": str(code), "message": str(message)}}

def _classify_error(exc: Exception) -> ResultDict:
    if isinstance(exc, PreTransitionVetoed):
        return _failure(exc.code or "plan_digest_divergence", str(exc))
    message = str(exc).strip() or exc.__class__.__name__
    if message.startswith("task not found:"):
        return _failure("task_not_found", message)
    # ... pattern-match on message content for known error classes
    return _failure("workflow_task_op_error", message)
```

Each ops module has its own `_classify_error()` variant (see also `daemon/ops/capability_ops/_install.py`, `daemon/space/group_space_runtime.py`).

---

## CLI Error Responses

CLI commands return JSON to stdout with a consistent shape:

```json
{"ok": false, "error": {"code": "task_not_found", "message": "task not found: abc123"}}
```

Exit codes: `0` = success, `1` = user/input error, `2` = system/daemon error.

---

## Required Patterns

| Pattern | Where |
|---------|-------|
| Domain exceptions at raise site, classification at boundary | All `daemon/ops/` handlers |
| `{"ok": bool, "result": {}, "error": {"code", "message"}}` | All IPC responses (daemon ↔ CLI) |
| Never let exceptions escape the JSONL formatter | `src/cccc/util/obslog.py` wraps everything in try/except |
| Validate Pydantic models with `extra="forbid"` | All `contracts/v1/` models |

---

## Forbidden Patterns

| Pattern | Why |
|---------|-----|
| Bare `except:` or `except Exception: pass` | Swallows errors silently; always log or re-raise |
| Returning error strings instead of raising | Project uses exceptions, not error-return style |
| Inventing new ResultDict shapes | Use `_success()` / `_failure()` helpers for consistency |
| Raising generic `Exception("...")` in ops | Define or reuse a domain-specific exception class |
