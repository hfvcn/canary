"""Pure runtime anomaly detection for Foreman workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from cccc.kernel.claimed_paths import normalize_path as _normalize_path
from cccc.kernel.claimed_paths import paths_overlap as _paths_overlap
from cccc.kernel.workflow_state_types import WorkflowTaskStatus

WORKER_EXCEEDED_SCOPE_CODE = "W_WORKER_EXCEEDED_SCOPE"
FRESH_SELF_TEST_ALERT_PREFIX = "INV-7:NO_COMPLETE_WITHOUT_FRESH_SELF_TEST"
LIVENESS_ALERT_TYPE = "liveness"


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
    fresh_self_test: MonitorMode
    liveness: MonitorMode


def get_default_config() -> MonitorConfig:
    return MonitorConfig(
        silent_agent=MonitorMode.OBSERVE,
        path_deviation=MonitorMode.OBSERVE,
        unauthorized_subagent=MonitorMode.OBSERVE,
        completer_mismatch=MonitorMode.OBSERVE,
        file_overstepping=MonitorMode.OBSERVE,
        fresh_self_test=MonitorMode.WARN,
        liveness=MonitorMode.WARN,
    )


@dataclass
class MonitorAlert:
    alert_type: str
    severity: str
    task_id: str
    message: str
    evidence: Dict
    mode: MonitorMode = MonitorMode.OBSERVE


def check_silent_agent(
    task_id: str,
    assigned_at: float,
    last_event_at: float,
    now: float,
    timeout_s: float = 300,
) -> Optional[MonitorAlert]:
    reference = last_event_at if last_event_at > assigned_at else assigned_at
    elapsed = now - reference
    if elapsed < timeout_s:
        return None
    return MonitorAlert(
        alert_type="silent_agent",
        severity="warning",
        task_id=task_id,
        message=f"Task {task_id!r} has been silent for {elapsed:.0f}s (timeout={timeout_s}s)",
        evidence={
            "assigned_at": assigned_at,
            "last_event_at": last_event_at,
            "now": now,
            "elapsed_s": elapsed,
            "timeout_s": timeout_s,
        },
    )


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
    if last_progress_pct is None or heartbeat_count < min_heartbeats:
        return None
    elapsed = now - first_heartbeat_at
    if elapsed < stagnant_timeout_s:
        return None
    return MonitorAlert(
        alert_type="progress_stall",
        severity="warning",
        task_id=task_id,
        message=f"Task {task_id!r} progress stayed at {last_progress_pct:g}% for {elapsed:.0f}s (timeout={stagnant_timeout_s}s)",
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


def check_liveness_deadline(
    task: Any,
    now: float,
    deadline_s: float,
) -> Optional[MonitorAlert]:
    reference = _liveness_reference_time(task)
    if reference is None:
        return None
    elapsed = now - reference
    if elapsed <= deadline_s:
        return None
    task_id = str(task.task.id)
    return MonitorAlert(
        alert_type=LIVENESS_ALERT_TYPE,
        severity="warning",
        task_id=task_id,
        message=f"Task {task_id!r} exceeded liveness deadline after {elapsed:.0f}s (deadline={deadline_s}s)",
        evidence={
            "status": getattr(task.status, "value", str(task.status)),
            "assigned_at": getattr(task, "assigned_at", None),
            "started_at": getattr(task, "started_at", None),
            "last_heartbeat": getattr(task, "last_heartbeat", None),
            "reference_at": reference,
            "elapsed_s": elapsed,
            "deadline_s": deadline_s,
        },
    )


def _liveness_reference_time(task: Any) -> Optional[float]:
    status = getattr(task, "status", None)
    if status == WorkflowTaskStatus.ASSIGNED:
        return getattr(task, "assigned_at", None)
    if status != WorkflowTaskStatus.RUNNING:
        return None
    return (
        getattr(task, "last_heartbeat", None)
        or getattr(task, "started_at", None)
        or getattr(task, "assigned_at", None)
    )


_ASSIGN_KEYWORDS = frozenset(["assign", "please take", "your task", "handle task"])


def check_path_deviation(task_id: str, event_type: str, event_payload: dict) -> Optional[MonitorAlert]:
    if event_type == "workflow.task_assigned":
        return None
    content = ""
    for key in ("content", "text", "body", "message"):
        value = event_payload.get(key)
        if isinstance(value, str):
            content = value
            break
    found_keywords = [kw for kw in _ASSIGN_KEYWORDS if kw in content.lower()]
    if not found_keywords:
        return None
    return MonitorAlert(
        alert_type="path_deviation",
        severity="warning",
        task_id=task_id,
        message=f"Event type {event_type!r} looks like a task assignment (keywords: {found_keywords!r}); expected 'workflow.task_assigned'",
        evidence={
            "event_type": event_type,
            "matched_keywords": found_keywords,
            "content_snippet": content[:200],
        },
    )


def check_unauthorized_subagent(agent_id: str, known_agents: set) -> Optional[MonitorAlert]:
    if agent_id in known_agents:
        return None
    return MonitorAlert(
        alert_type="unauthorized_subagent",
        severity="error",
        task_id="",
        message=f"Agent {agent_id!r} is not in the known-agents set",
        evidence={"agent_id": agent_id, "known_agents": sorted(known_agents)},
    )


def check_completer_mismatch(
    task_id: str,
    assigned_agent: str,
    completing_agent: str,
) -> Optional[MonitorAlert]:
    if not assigned_agent or not completing_agent or assigned_agent == completing_agent:
        return None
    return MonitorAlert(
        alert_type="completer_mismatch",
        severity="error",
        task_id=task_id,
        message=f"Task {task_id!r} was assigned to {assigned_agent!r} but completed by {completing_agent!r}",
        evidence={"assigned_agent": assigned_agent, "completing_agent": completing_agent},
    )


def check_file_overstepping(
    task_id: str,
    changed_files: List[str],
    claimed_paths: List[str],
) -> Optional[MonitorAlert]:
    if not changed_files or not claimed_paths:
        return None
    normalized_claimed = [_normalize_path(path) for path in claimed_paths]
    exceeded_files = [
        normalized
        for normalized in (_normalize_path(path) for path in changed_files)
        if not any(_paths_overlap(normalized, claimed) for claimed in normalized_claimed)
    ]
    if not exceeded_files:
        return None
    return MonitorAlert(
        alert_type=WORKER_EXCEEDED_SCOPE_CODE,
        severity="error",
        task_id=task_id,
        message=f"Task {task_id!r} modified {len(exceeded_files)} file(s) outside claimed scope: {exceeded_files!r}",
        evidence={"exceeded_files": exceeded_files, "claimed_paths": normalized_claimed},
    )


def check_fresh_self_test(
    task_id: str,
    current_attempt_id: str,
    self_test: Any,
) -> Optional[MonitorAlert]:
    normalized_self_test = dict(self_test) if isinstance(self_test, dict) else None
    if normalized_self_test and str(normalized_self_test.get("attempt_id") or "") == current_attempt_id:
        return None
    reason = "missing_self_test" if normalized_self_test is None else "stale_self_test"
    return MonitorAlert(
        alert_type=f"{FRESH_SELF_TEST_ALERT_PREFIX}:{task_id}",
        severity="error",
        task_id=task_id,
        message=f"Task {task_id!r} reported completion without a fresh self-test for attempt {current_attempt_id!r}",
        evidence={
            "reason": reason,
            "current_attempt_id": current_attempt_id,
            "self_test": normalized_self_test,
        },
    )


def _report_or_raise(engine, alert: MonitorAlert, mode: MonitorMode, rejected_cls) -> None:
    if mode == MonitorMode.BLOCK:
        raise rejected_cls(alert_type=alert.alert_type, message=alert.message, evidence=alert.evidence)
    engine.report_hook_alert(
        {
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "task_id": alert.task_id,
            "message": alert.message,
            "evidence": alert.evidence,
            "mode": mode.value,
        }
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
        evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
        alert = check_completer_mismatch(task_id, task_state.agent_id, str(evidence.get("agent_id") or ""))
        if not alert:
            return
        cfg = engine.get_monitor_config()
        _report_or_raise(engine, alert, cfg.completer_mismatch if cfg else MonitorMode.OBSERVE, TransitionRejected)

    hook.invariant_id = "completer_mismatch"
    return hook


def create_fresh_self_test_hook():
    def hook(kind, data, engine):
        from ...kernel.workflow_state_types import KIND_TASK_REPORTED_COMPLETED, TransitionRejected

        if kind != KIND_TASK_REPORTED_COMPLETED:
            return
        task_id = str(data.get("task_id") or "")
        task_state = engine.get_task(task_id)
        if not task_state:
            return
        evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
        alert = check_fresh_self_test(task_id, str(task_state.attempt_id or ""), evidence.get("self_test"))
        if not alert:
            return
        cfg = engine.get_monitor_config()
        _report_or_raise(engine, alert, cfg.fresh_self_test if cfg else MonitorMode.OBSERVE, TransitionRejected)

    hook.invariant_id = "fresh_self_test"
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
        evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
        alert = check_file_overstepping(task_id, list(evidence.get("changed_files") or []), list(task_state.task.claimed_paths or []))
        if not alert:
            return
        cfg = engine.get_monitor_config()
        _report_or_raise(engine, alert, cfg.file_overstepping if cfg else MonitorMode.OBSERVE, TransitionRejected)

    hook.invariant_id = "file_overstepping"
    return hook


def create_unauthorized_subagent_hook(known_actors_fn):
    def hook(kind, data, engine):
        from ...kernel.workflow_state_types import KIND_TASK_STARTED, TransitionRejected

        if kind != KIND_TASK_STARTED:
            return
        alert = check_unauthorized_subagent(str(data.get("agent_id") or ""), known_actors_fn())
        if not alert:
            return
        cfg = engine.get_monitor_config()
        _report_or_raise(engine, alert, cfg.unauthorized_subagent if cfg else MonitorMode.OBSERVE, TransitionRejected)

    hook.invariant_id = "unauthorized_subagent"
    return hook
