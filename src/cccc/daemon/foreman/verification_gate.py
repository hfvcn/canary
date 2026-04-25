"""Verification gate — task completion verification flow.

Extracted from workflow_orchestrator.py as a pure refactor (RO-31).
These are module-level helpers called by WorkflowOrchestrator.apply_task_event.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...contracts.v1.ralph_ipc import VerificationResult
from ...kernel.workflow_state import WorkflowTaskStatus
from ...kernel.workflow_state_types import TaskState
from .workflow_monitor import (
    check_completer_mismatch,
    MonitorMode,
)

logger = logging.getLogger("cccc.daemon.foreman.orchestrator")

COMPLETER_MISMATCH_BLOCKED_REASON = "completer_mismatch_blocked"


def auto_start_assigned_task_for_completion(
    *,
    engine: Any,
    task_id: str,
    state: TaskState,
    payload_agent_id: str,
    result: Dict[str, Any],
    hook_ctx: Dict[str, Any],
) -> Optional[TaskState]:
    """Auto-start an ASSIGNED task so completion can proceed.

    Checks for completer mismatch; blocks if monitor config says BLOCK.
    Returns the updated TaskState, or None if blocked.
    """
    original_agent_id = str(getattr(state, "agent_id", "") or "").strip()
    alert = check_completer_mismatch(task_id, original_agent_id, payload_agent_id)
    if alert:
        config = engine.get_monitor_config()
        mode = config.completer_mismatch if config else MonitorMode.OBSERVE
        if mode == MonitorMode.BLOCK:
            logger.warning("apply_task_event blocked pre-start completer mismatch: %s", alert.message)
            engine.record_verification_warning(
                task_id=task_id,
                warning_type=alert.alert_type,
                message=alert.message,
                evidence=alert.evidence,
            )
            result["accepted"] = False
            result["reason"] = COMPLETER_MISMATCH_BLOCKED_REASON
            return None
        logger.warning(
            "apply_task_event observed pre-start completer mismatch: %s",
            alert.message,
            extra={"evidence": alert.evidence, "mode": mode.value},
        )
    engine.report_worker_started(task_id, original_agent_id, hook_ctx=hook_ctx)
    return engine.get_task(task_id) or state


def process_completed_event(
    *,
    engine: Any,
    ralph_service: Any,
    task_id: str,
    state: TaskState,
    payload: Dict[str, Any],
    agent_id: str,
    hook_ctx: Dict[str, Any],
    result: Dict[str, Any],
    extract_evidence_summary_fn: Any,
    on_task_completed_fn: Any,
    on_task_failed_fn: Any,
    notify_verification_fn: Any,
    save_context_fn: Any,
    auto_start_fn: Any,
) -> Dict[str, Any]:
    """Process a 'completed' event through the verification gate.

    This is the core verification gate logic extracted from
    ``_apply_task_event_inner``.
    """
    duration_seconds = int(payload.get("duration_seconds") or 0)
    changed_files = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
    evidence_summary = extract_evidence_summary_fn(payload)
    attempt_id = str(payload.get("attempt_id") or "").strip()

    if state.status in (
        WorkflowTaskStatus.COMPLETED,
        WorkflowTaskStatus.FAILED,
        WorkflowTaskStatus.BLOCKED,
        WorkflowTaskStatus.ARCHIVED,
    ):
        result["reason"] = f"terminal_state:{state.status.value}"
        return result

    if state.status == WorkflowTaskStatus.READY:
        result["accepted"] = False
        result["reason"] = (
            f"task_still_ready task_id={task_id} — task was registered but never approved/assigned. "
            f"Was auto_process=True used in workflow submit? "
            f"Task must pass through approve→assign before completion can be processed."
        )
        logger.warning("apply_task_event rejected: task %s still in READY (not approved)", task_id)
        return result

    if state.status == WorkflowTaskStatus.ASSIGNED:
        state = auto_start_fn(
            task_id=task_id,
            state=state,
            payload_agent_id=str(payload.get("agent_id") or "").strip(),
            result=result,
            hook_ctx=hook_ctx,
        )
        if state is None:
            return result

    if state.status != WorkflowTaskStatus.RUNNING:
        result["accepted"] = False
        result["reason"] = f"task_not_running status={state.status.value}"
        return result

    engine.report_worker_completion(
        task_id,
        {
            "agent_id": agent_id,
            "duration_seconds": duration_seconds,
            "changed_files": list(changed_files),
            "idempotency_key": str(payload.get("idempotency_key") or "").strip(),
        },
        hook_ctx=hook_ctx,
        attempt_id=attempt_id,
    )

    try:
        verification = ralph_service.verify_completion(
            task_id,
            list(changed_files),
            workflow_id=state.workflow_id,
            task_ref=state.task,
        )
    except Exception as e:
        verification = VerificationResult(
            verification_id=f"ver-error-{task_id}",
            workflow_id=state.workflow_id,
            task_id=task_id,
            overall_outcome="failed",
            checks=[],
            summary=f"verification_error: {e}",
        )

    engine.record_verification_result(task_id, verification, hook_ctx=hook_ctx)
    result["verification_outcome"] = verification.overall_outcome

    if verification.overall_outcome == "agent_pending":
        # RA-3: agent verification — task stays in VERIFYING, just notify
        notification_outcome = "agent_pending"
        context_error = ""
    elif verification.overall_outcome == "passed":
        on_task_completed_fn(
            task_id=task_id,
            agent_id=agent_id,
            duration_seconds=duration_seconds,
            changed_files=list(changed_files),
            workflow_id=payload.get("workflow_id") or state.workflow_id,
            verification=verification,
        )
        notification_outcome = "passed"
        context_error = ""
    elif verification.overall_outcome == "skipped":
        error_msg = (
            "Verification skipped: no commands configured. "
            "Add verification commands or use force_complete_unverified()."
        )
        on_task_failed_fn(
            task_id=task_id,
            error_message=error_msg,
            agent_name=agent_id,
            verification=verification,
        )
        notification_outcome = "skipped"
        context_error = error_msg
    else:
        on_task_failed_fn(
            task_id=task_id,
            error_message=verification.summary or "Verification failed",
            agent_name=agent_id,
            verification=verification,
        )
        notification_outcome = "failed"
        context_error = verification.summary or "Verification failed"

    try:
        notify_verification_fn(
            task_id=task_id,
            verification_outcome=notification_outcome,
            evidence_summary=evidence_summary,
            changed_files=list(changed_files),
        )
    except Exception:
        logger.warning(
            "Failed to send verification notification to foreman for task %s",
            task_id,
            exc_info=True,
        )

    save_context_fn(
        task_id=task_id,
        task=state.task,
        changed_files=list(changed_files),
        last_error=context_error,
    )
    return result


def process_failed_event(
    *,
    engine: Any,
    task_id: str,
    state: TaskState,
    payload: Dict[str, Any],
    agent_id: str,
    hook_ctx: Dict[str, Any],
    result: Dict[str, Any],
    on_task_failed_fn: Any,
    save_context_fn: Any,
) -> Dict[str, Any]:
    """Process a 'failed' event."""
    error_message = str(payload.get("error_message") or "").strip()
    suggestion = str(payload.get("suggestion") or "").strip()
    agent_name = str(payload.get("agent_name") or "").strip() or agent_id
    changed_files = payload.get("changed_files") if isinstance(payload.get("changed_files"), list) else []
    if state.status == WorkflowTaskStatus.ASSIGNED:
        engine.report_worker_started(task_id, agent_id, hook_ctx=hook_ctx)
        state = engine.get_task(task_id) or state
    if state.status == WorkflowTaskStatus.RUNNING:
        engine.report_worker_failed(
            task_id,
            {"error_message": error_message, "suggestion": suggestion, "agent_name": agent_name},
            hook_ctx=hook_ctx,
        )
    on_task_failed_fn(
        task_id=task_id,
        error_message=error_message,
        suggestion=suggestion,
        agent_name=agent_name,
    )
    save_context_fn(
        task_id=task_id,
        task=state.task,
        changed_files=list(changed_files),
        last_error=error_message,
    )
    return result
