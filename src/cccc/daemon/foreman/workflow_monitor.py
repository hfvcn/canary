"""Runtime anomaly detection for Foreman workflows.

Pure logic module — no imports from daemon/orchestrator internals.
All functions are stateless and testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from cccc.ralph.core import _paths_overlap


class MonitorMode(str, Enum):
    OBSERVE = "observe"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class MonitorConfig:
    silent_agent: MonitorMode
    path_deviation: MonitorMode
    unauthorized_subagent: MonitorMode
    completer_mismatch: MonitorMode
    file_overstepping: MonitorMode


def get_default_config() -> MonitorConfig:
    return MonitorConfig(
        silent_agent=MonitorMode.OBSERVE,
        path_deviation=MonitorMode.OBSERVE,
        unauthorized_subagent=MonitorMode.OBSERVE,
        completer_mismatch=MonitorMode.OBSERVE,
        file_overstepping=MonitorMode.OBSERVE,
    )


@dataclass
class MonitorAlert:
    alert_type: str   # "silent_agent" | "path_deviation" | "completer_mismatch" | "file_overstepping" | "unauthorized_subagent"
    severity: str     # "warning" | "error"
    task_id: str      # affected task (empty string when not task-scoped)
    message: str      # human-readable description
    evidence: Dict    # structured data for debugging
    mode: MonitorMode = MonitorMode.OBSERVE


# ---------------------------------------------------------------------------
# Check: silent agent
# ---------------------------------------------------------------------------

def check_silent_agent(
    task_id: str,
    assigned_at: float,    # timestamp
    last_event_at: float,  # timestamp of last event, 0 if none
    now: float,            # current timestamp
    timeout_s: float = 300,
) -> Optional[MonitorAlert]:
    """Alert if no events within timeout after assignment."""
    # Use last_event_at if it exists and is later than assigned_at,
    # otherwise fall back to assigned_at as the reference point.
    reference = last_event_at if last_event_at > assigned_at else assigned_at
    elapsed = now - reference
    if elapsed >= timeout_s:
        return MonitorAlert(
            alert_type="silent_agent",
            severity="warning",
            task_id=task_id,
            message=(
                f"Task {task_id!r} has been silent for {elapsed:.0f}s "
                f"(timeout={timeout_s}s)"
            ),
            evidence={
                "assigned_at": assigned_at,
                "last_event_at": last_event_at,
                "now": now,
                "elapsed_s": elapsed,
                "timeout_s": timeout_s,
            },
        )
    return None


# ---------------------------------------------------------------------------
# Check: path deviation (agent using direct messaging for task assignment)
# ---------------------------------------------------------------------------

_ASSIGN_KEYWORDS = frozenset(["assign", "please take", "your task", "handle task"])


def check_path_deviation(
    task_id: str,
    event_type: str,       # e.g. "message_send"
    event_payload: dict,   # event details
) -> Optional[MonitorAlert]:
    """Detect agent using direct messaging to assign tasks.

    Fires when a ``message_send`` event contains task-assignment language
    (e.g. the word "assign" together with what looks like a task reference)
    instead of going through the proper ``workflow.task_assigned`` channel.
    """
    if event_type == "workflow.task_assigned":
        # Proper channel — no deviation
        return None

    content: str = ""
    for key in ("content", "text", "body", "message"):
        val = event_payload.get(key)
        if isinstance(val, str):
            content = val
            break

    content_lower = content.lower()
    found_keywords = [kw for kw in _ASSIGN_KEYWORDS if kw in content_lower]

    if not found_keywords:
        return None

    return MonitorAlert(
        alert_type="path_deviation",
        severity="warning",
        task_id=task_id,
        message=(
            f"Event type {event_type!r} looks like a task assignment "
            f"(keywords: {found_keywords!r}); expected 'workflow.task_assigned'"
        ),
        evidence={
            "event_type": event_type,
            "matched_keywords": found_keywords,
            "content_snippet": content[:200],
        },
    )


# ---------------------------------------------------------------------------
# Check: unauthorized subagent
# ---------------------------------------------------------------------------

def check_unauthorized_subagent(
    agent_id: str,
    known_agents: set,
) -> Optional[MonitorAlert]:
    """Detect unplanned agent creation."""
    if agent_id in known_agents:
        return None
    return MonitorAlert(
        alert_type="unauthorized_subagent",
        severity="error",
        task_id="",
        message=f"Agent {agent_id!r} is not in the known-agents set",
        evidence={
            "agent_id": agent_id,
            "known_agents": sorted(known_agents),
        },
    )


# ---------------------------------------------------------------------------
# Check: completer mismatch
# ---------------------------------------------------------------------------

def check_completer_mismatch(
    task_id: str,
    assigned_agent: str,
    completing_agent: str,
) -> Optional[MonitorAlert]:
    """Detect wrong agent completing a task."""
    if not assigned_agent or not completing_agent:
        return None
    if assigned_agent == completing_agent:
        return None
    return MonitorAlert(
        alert_type="completer_mismatch",
        severity="error",
        task_id=task_id,
        message=(
            f"Task {task_id!r} was assigned to {assigned_agent!r} "
            f"but completed by {completing_agent!r}"
        ),
        evidence={
            "assigned_agent": assigned_agent,
            "completing_agent": completing_agent,
        },
    )


# ---------------------------------------------------------------------------
# Check: file overstepping
# ---------------------------------------------------------------------------

def check_file_overstepping(
    task_id: str,
    changed_files: List[str],
    claimed_paths: List[str],
) -> Optional[MonitorAlert]:
    """Detect worker modifying files outside claimed scope.

    A changed file is considered *in scope* if it overlaps with at least one
    claimed path (using the same overlap semantics as ralph.core._paths_overlap).
    An alert lists every out-of-scope file.
    """
    if not changed_files:
        return None

    # If no claimed paths are given we treat it as global scope (no restriction)
    if not claimed_paths:
        return None

    overstepping: List[str] = []
    for f in changed_files:
        in_scope = any(_paths_overlap(f, cp) for cp in claimed_paths)
        if not in_scope:
            overstepping.append(f)

    if not overstepping:
        return None

    return MonitorAlert(
        alert_type="file_overstepping",
        severity="error",
        task_id=task_id,
        message=(
            f"Task {task_id!r} modified {len(overstepping)} file(s) outside "
            f"claimed scope: {overstepping!r}"
        ),
        evidence={
            "overstepping_files": overstepping,
            "claimed_paths": claimed_paths,
            "changed_files": changed_files,
        },
    )
