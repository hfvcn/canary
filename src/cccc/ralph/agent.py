"""Shared error-envelope definitions for the Ralph subsystem.

Provides a single source of truth for:
- Processing stages (RALPH_STAGES)
- Internal error codes (RULE_ERROR_REGISTRY)
- Structured error envelope builder (build_error_envelope)

Used by the CLI, daemon IPC, and orchestrator surfaces.
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Stable stage enum
# ---------------------------------------------------------------------------

RALPH_STAGES = frozenset({
    "load",
    "validate",
    "semantic",
    "ipc",
    "completion",
    "register",
    "suggest",
    "verify",
})


# ---------------------------------------------------------------------------
# Internal error code registry — single canonical copy
# ---------------------------------------------------------------------------

RULE_ERROR_REGISTRY: Dict[str, str] = {
    "load": "E_INTERNAL_LOAD",
    "validate": "E_INTERNAL_VALIDATE",
    "semantic": "E_INTERNAL_SEMANTIC",
    "ipc": "E_INTERNAL_IPC",
    "completion": "E_INTERNAL_COMPLETION",
    "register": "E_INTERNAL_REGISTER",
    "suggest": "E_INTERNAL_SUGGEST",
    "verify": "E_INTERNAL_VERIFY",
}


def _is_debug_traceback_enabled() -> bool:
    """Check whether raw traceback output is enabled via environment variable."""
    return os.environ.get("CCCC_DEBUG_TRACEBACK", "").strip() in ("1", "true", "yes")


def build_error_envelope(
    *,
    stage: str,
    exception: BaseException,
    internal_error_code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a structured error envelope dict.

    This is the canonical shape used across all three surfaces (CLI JSON
    output, daemon IPC response, and orchestrator ledger events).

    Parameters
    ----------
    stage:
        One of RALPH_STAGES (e.g. "load", "semantic", "ipc").
    exception:
        The caught exception.
    internal_error_code:
        Explicit error code. Derived from *stage* via RULE_ERROR_REGISTRY when omitted.
    extra:
        Additional key-value pairs merged into the envelope.

    Returns
    -------
    dict with keys: stage, internal_error_code, exception_type, message,
    and optionally traceback_truncated (only when CCCC_DEBUG_TRACEBACK=1).
    """
    code = internal_error_code or RULE_ERROR_REGISTRY.get(stage, "E_INTERNAL_UNKNOWN")
    envelope: Dict[str, Any] = {
        "stage": stage,
        "internal_error_code": code,
        "exception_type": type(exception).__name__,
        "message": str(exception).strip() or type(exception).__name__,
    }

    if _is_debug_traceback_enabled():
        tb_lines = traceback.format_exception(type(exception), exception, exception.__traceback__)
        full_tb = "".join(tb_lines)
        # Truncate to a reasonable size for structured output
        max_len = 4000
        if len(full_tb) > max_len:
            full_tb = full_tb[:max_len] + "\n... (truncated)"
        envelope["traceback_truncated"] = full_tb

    if extra:
        envelope.update(extra)

    return envelope
