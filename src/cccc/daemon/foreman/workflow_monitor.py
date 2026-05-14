"""Pure runtime anomaly detection for Foreman workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from cccc.kernel.claimed_paths import normalize_path as _normalize_path
from cccc.kernel.claimed_paths import paths_overlap as _paths_overlap


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
    alert_type: str   # "silent_agent" | "progress_stall" | "path_deviation" | "completer_mismatch" | "file_overstepping" | "unauthorized_subagent"
    severity: str     # "warning" | "error"
    task_id: str      # affected task (empty string when not task-scoped)
    message: str      # human-readable description
    evidence: Dict    # structured data for debugging
    mode: MonitorMode = MonitorMode.OBSERVE


def check_silent_agent(
    task_id: str,
    assigned_at: float,    # timestamp
    last_event_at: float,  # timestamp of last event, 0 if none
    now: float,            # current timestamp
    timeout_s: float = 300,
) -> Optional[MonitorAlert]:
    """Alert if no events within timeout after assignment."""
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


def check_progress_stall(
    task_id: str,
    heartbeat_count: int,
    last_progress_pct: Optional[float],
    first_heartbeat_at: float,
    last_heartbeat_at: float,
    now: float,
    min_heartbeats: int = 5,
    stagnant_timeout_s: float = 300,
) -> Optional[MonitorAlert]:
    """Alert when the current progress value survives enough heartbeats."""
    if last_progress_pct is None:
        return None
    if heartbeat_count < min_heartbeats:
        return None

    elapsed = now - first_heartbeat_at
    if elapsed < stagnant_timeout_s:
        return None

    return MonitorAlert(
        alert_type="progress_stall",
        severity="warning",
        task_id=task_id,
        message=(
            f"Task {task_id!r} progress stayed at {last_progress_pct:g}% "
            f"for {elapsed:.0f}s (timeout={stagnant_timeout_s}s)"
        ),
        evidence={
            "heartbeat_count": heartbeat_count,
            "min_heartbeats": min_heartbeats,
            "progress_pct": last_progress_pct,
            "first_heartbeat_at": first_heartbeat_at,
            "last_heartbeat_at": last_heartbeat_at,
            "now": now,
            "elapsed_s": elapsed,
            "stagnant_timeout_s": stagnant_timeout_s,
        },
    )


_ASSIGN_KEYWORDS = frozenset(["assign", "please take", "your task", "handle task"])


def check_path_deviation(
    task_id: str,
    event_type: str,       # e.g. "message_send"
    event_payload: dict,   # event details
) -> Optional[MonitorAlert]:
    """Detect direct-message task assignment instead of workflow channel use."""
    if event_type == "workflow.task_assigned":
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


def check_file_overstepping(
    task_id: str,
    changed_files: List[str],
    claimed_paths: List[str],
) -> Optional[MonitorAlert]:
    """Detect worker modifying files outside claimed scope."""
    if not changed_files:
        return None
    if not claimed_paths:
        return None

    normalized_claimed_paths = [_normalize_path(path) for path in claimed_paths]
    normalized_changed_files = [_normalize_path(path) for path in changed_files]
    overstepping: List[str] = []
    for path in normalized_changed_files:
        in_scope = any(_paths_overlap(path, claimed_path) for claimed_path in normalized_claimed_paths)
        if not in_scope:
            overstepping.append(path)

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
            "claimed_paths": normalized_claimed_paths,
            "changed_files": normalized_changed_files,
        },
    )
def create_completer_mismatch_hook():
    def hook(kind, data, engine):
        from ...kernel.workflow_state_types import KIND_TASK_REPORTED_COMPLETED, TransitionRejected
        if kind != KIND_TASK_REPORTED_COMPLETED:
            return
        task_id = str(data.get("task_id") or "")
        task_state = engine.get_task(task_id)
        if not task_state:
            return
        completing_agent = str((data.get("evidence") or {}).get("agent_id") or "")
        alert = check_completer_mismatch(task_id, task_state.agent_id, completing_agent)
        if not alert:
            return
        cfg = engine.get_monitor_config()
        mode = cfg.completer_mismatch if cfg else MonitorMode.OBSERVE
        if mode == MonitorMode.BLOCK:
            raise TransitionRejected(alert_type=alert.alert_type, message=alert.message, evidence=alert.evidence)
        engine.report_hook_alert({"alert_type": alert.alert_type, "severity": alert.severity, "task_id": alert.task_id, "message": alert.message, "evidence": alert.evidence, "mode": mode.value})
    hook.invariant_id = "completer_mismatch"
    return hook
def create_file_overstepping_hook():
    def hook(kind, data, engine):
        from ...kernel.workflow_state_types import KIND_TASK_REPORTED_COMPLETED, TransitionRejected
        if kind != KIND_TASK_REPORTED_COMPLETED:
            return
        task_id = str(data.get("task_id") or "")
        task_state = engine.get_task(task_id)
        if not task_state:
            return
        changed_files = list((data.get("evidence") or {}).get("changed_files") or [])
        claimed_paths = list(task_state.task.claimed_paths or [])
        alert = check_file_overstepping(task_id, changed_files, claimed_paths)
        if not alert:
            return
        cfg = engine.get_monitor_config()
        mode = cfg.file_overstepping if cfg else MonitorMode.OBSERVE
        if mode == MonitorMode.BLOCK:
            raise TransitionRejected(alert_type=alert.alert_type, message=alert.message, evidence=alert.evidence)
        engine.report_hook_alert({"alert_type": alert.alert_type, "severity": alert.severity, "task_id": alert.task_id, "message": alert.message, "evidence": alert.evidence, "mode": mode.value})
    hook.invariant_id = "file_overstepping"
    return hook
def create_unauthorized_subagent_hook(known_actors_fn):
    def hook(kind, data, engine):
        from ...kernel.workflow_state_types import KIND_TASK_STARTED, TransitionRejected
        if kind != KIND_TASK_STARTED:
            return
        agent_id = str(data.get("agent_id") or "")
        known = known_actors_fn()
        alert = check_unauthorized_subagent(agent_id, known)
        if not alert:
            return
        cfg = engine.get_monitor_config()
        mode = cfg.unauthorized_subagent if cfg else MonitorMode.OBSERVE
        if mode == MonitorMode.BLOCK:
            raise TransitionRejected(alert_type=alert.alert_type, message=alert.message, evidence=alert.evidence)
        engine.report_hook_alert({"alert_type": alert.alert_type, "severity": alert.severity, "task_id": alert.task_id, "message": alert.message, "evidence": alert.evidence, "mode": mode.value})
    hook.invariant_id = "unauthorized_subagent"
    return hook
