# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Python 3.9+ codebase using setuptools. Tests use a mix of `unittest.TestCase` and pytest. No linter or formatter is currently enforced in CI — quality is maintained through conventions and code review.

---

## Required Patterns

### Type hints

All public functions must have type annotations. Use `from __future__ import annotations` at the top of every file (PEP 563 deferred evaluation):

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional

def resolve_group(group_id: str, *, strict: bool = False) -> Optional[Dict[str, Any]]:
    ...
```

### Pydantic v2 for data models

Use `BaseModel` with `ConfigDict(extra="forbid")` for all wire-format contracts:

```python
from pydantic import BaseModel, ConfigDict, Field

class GroupCreateData(BaseModel):
    title: str
    topic: str = ""
    model_config = ConfigDict(extra="forbid")
```

### `__all__` exports

CLI command modules must declare `__all__` listing all public `cmd_*` functions:

```python
# src/cccc/cli/actor_cmds.py
__all__ = ["cmd_actor_add", "cmd_actor_remove", "cmd_actor_list"]
```

### Imports

- Use absolute imports from `cccc.*` (not relative) in daemon ops:
  ```python
  from cccc.contracts.v1.ralph_ipc import TaskEvent
  from cccc.kernel.workflow_state import WorkflowTaskStatus
  ```
- Use relative imports within tightly coupled sub-packages (e.g., within `contracts/v1/`):
  ```python
  from ...util.time import utc_now_iso
  ```

---

## Testing

### Framework

- Test framework: **pytest** (configured in `pyproject.toml`)
- Test files live in `tests/` (flat directory, not mirroring `src/` structure)
- Naming: `test_<domain>_<feature>.py`
- Both `unittest.TestCase` classes and plain pytest functions are used

### Test patterns

```python
# Using unittest.TestCase (common in this codebase)
class TestAccessTokenRoutes(unittest.TestCase):
    def _with_home(self):
        """Set up temp CCCC_HOME, return (tmpdir, cleanup_fn)."""
        old_home = os.environ.get("CCCC_HOME")
        td = tempfile.mkdtemp()
        os.environ["CCCC_HOME"] = td
        def cleanup():
            os.environ["CCCC_HOME"] = old_home if old_home else ""
        return td, cleanup
```

- Isolate tests by pointing `CCCC_HOME` to a temp directory
- Clean up via explicit cleanup functions or `addCleanup()`
- Integration tests that hit the daemon use `TestClient(create_app())`

### Running tests

```bash
pytest tests/
pytest tests/test_ralph_wave1_integration.py -v
```

---

## Forbidden Patterns

| Pattern | Why |
|---------|-----|
| `pydantic<2.0` syntax (`class Config:` inner class) | Project uses v2 `ConfigDict` |
| Mutable default arguments (`def f(items=[])`) | Standard Python footgun |
| `from cccc.cli.common import *` outside of `cli/__init__.py` | Star imports only in the CLI module proxy |
| Importing from `vendor/` directly in new code | Vendored code is for existing integrations; prefer adding new dependencies to `pyproject.toml` |
| Synchronous blocking calls in async FastAPI routes | `ports/web/` uses `async def` routes; use `httpx` for HTTP, not `requests` |
| `os.path` for new code | Use `pathlib.Path` consistently (existing code already does) |

---

## Code Style

| Item | Convention |
|------|-----------|
| String quotes | Double quotes for user-visible strings, single or double for internal (no strict rule) |
| Line length | No enforced limit, but keep readable (~100-120 chars in practice) |
| Docstrings | One-line docstrings for modules; skip for obvious functions |
| Constants | `UPPER_SNAKE_CASE`, defined at module level |
| Private helpers | Prefix with `_` (e.g., `_classify_error`, `_normalize_text`) |

---

## Dependencies

Key dependencies (from `pyproject.toml`):

| Package | Version | Usage |
|---------|---------|-------|
| `pydantic` | `>=2.0,<3.0` | Data modeling (contracts, ralph models) |
| `fastapi` | `>=0.110,<1.0` | Web server (`ports/web/`) |
| `uvicorn[standard]` | `>=0.27,<1.0` | ASGI server (with standard extras) |
| `httpx[socks]` | `>=0.24,<1.0` | Async HTTP client (with SOCKS proxy support) |
| `PyYAML` | `>=6.0,<7.0` | Plan file parsing |
| `websocket-client` | `>=1.8,<2.0` | WebSocket connections |

Do not add new dependencies without justification. Check if `util/` or `vendor/` already provides the functionality.
