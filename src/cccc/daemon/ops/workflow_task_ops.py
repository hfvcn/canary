"""Canonical workflow task state-change operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from cccc.contracts.v1.ralph_ipc import TaskEvent, VerificationResult
from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator
from cccc.kernel.workflow_state import WorkflowTaskStatus
from cccc.ralph.agent import build_error_envelope

ResultDict = Dict[str, Any]

DEFAULT_DURATION_SECONDS = 0


def _success(result: ResultDict) -> ResultDict:
    return {"ok": True, "result": dict(result), "error": {}}


def _failure(code: str, message: str) -> ResultDict:
    return {"ok": False, "result": {}, "error": {"code": str(code or ""), "message": str(message or "")}}


def _normalize_text(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _normalize_changed_files(changed_files: Any) -> list[str]:
    if not isinstance(changed_files, list):
        return []
    return [str(path or "").strip() for path in changed_files if str(path or "").strip()]


def _classify_error(exc: Exception) -> ResultDict:
    message = str(exc).strip() or exc.__class__.__name__
    if message.startswith("task not found:"):
        return _failure("task_not_found", message)
    if message.startswith("workflow_id mismatch"):
        return _failure("workflow_id_mismatch", message)
    if " is required" in message:
        return _failure("missing_field", message)
    if message.startswith("task not ") or "status=" in message:
        return _failure("invalid_state_transition", message)
    if message.startswith("orchestrator not found"):
        return _failure("orchestrator_not_found", message)
    result = _failure("workflow_task_op_error", message)
    result["error"] = build_error_envelope(stage="ipc", exception=exc)
    return result


def _wrap_event_result(result: ResultDict) -> ResultDict:
    if result.get("accepted", True):
        return _success(result)
    return {
        "ok": False,
        "result": dict(result),
        "error": {
            "code": "invalid_state_transition",
            "message": str(result.get("reason") or "task event rejected"),
        },
    }


def _get_orchestrator_or_raise(
    group_id: str,
    project_root: str,
    daemon_request_fn: Callable[..., Any] | None,
):
    orchestrator = get_orchestrator(
        _normalize_text("group_id", group_id),
        project_root=Path(_normalize_text("project_root", project_root)),
        daemon_request_fn=daemon_request_fn,
    )
    if orchestrator is None:
        raise ValueError(f"orchestrator not found for group: {group_id}")
    if daemon_request_fn and not getattr(orchestrator, "_daemon_request_fn", None):
        orchestrator._daemon_request_fn = daemon_request_fn
    return orchestrator


def _get_state_or_raise(orchestrator: Any, task_id: str, workflow_id: str) -> Any:
    normalized_task_id = _normalize_text("task_id", task_id)
    normalized_workflow_id = _normalize_text("workflow_id", workflow_id)
    state = orchestrator.engine.get_task(normalized_task_id)
    if state is None:
        raise ValueError(f"task not found: {normalized_task_id}")
    actual_workflow_id = str(getattr(state, "workflow_id", "") or "").strip()
    if actual_workflow_id and actual_workflow_id != normalized_workflow_id:
        raise ValueError(
            f"workflow_id mismatch for task {normalized_task_id}: "
            f"expected {normalized_workflow_id}, got {actual_workflow_id}"
        )
    return state


def _build_verification_error(task_id: str, workflow_id: str, exc: Exception) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-error-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="failed",
        checks=[],
        summary=f"verification_error: {exc}",
    )


def complete_task(group_id, task_id, agent_id, changed_files, evidence, workflow_id, project_root, daemon_request_fn, *, assignment_id="", actor_run_id=""):
    try:
        orchestrator = _get_orchestrator_or_raise(group_id, project_root, daemon_request_fn)
        _get_state_or_raise(orchestrator, task_id, workflow_id)
        event = TaskEvent(
            event_type="completed",
            task_id=_normalize_text("task_id", task_id),
            payload={
                "agent_id": _normalize_text("agent_id", agent_id),
                "workflow_id": _normalize_text("workflow_id", workflow_id),
                "duration_seconds": DEFAULT_DURATION_SECONDS,
                "changed_files": _normalize_changed_files(changed_files),
                "evidence": evidence,
                "assignment_id": str(assignment_id or "").strip(),
                "actor_run_id": str(actor_run_id or "").strip(),
            },
        )
        result = orchestrator.apply_task_event(event)
        result["workflow_id"] = _normalize_text("workflow_id", workflow_id)
        return _wrap_event_result(result)
    except Exception as exc:
        return _classify_error(exc)


def fail_task(group_id, task_id, agent_id, message, workflow_id, project_root, daemon_request_fn, *, assignment_id="", actor_run_id=""):
    try:
        orchestrator = _get_orchestrator_or_raise(group_id, project_root, daemon_request_fn)
        _get_state_or_raise(orchestrator, task_id, workflow_id)
        normalized_agent_id = _normalize_text("agent_id", agent_id)
        event = TaskEvent(
            event_type="failed",
            task_id=_normalize_text("task_id", task_id),
            payload={
                "agent_id": normalized_agent_id,
                "agent_name": normalized_agent_id,
                "workflow_id": _normalize_text("workflow_id", workflow_id),
                "error_message": _normalize_text("message", message),
                "assignment_id": str(assignment_id or "").strip(),
                "actor_run_id": str(actor_run_id or "").strip(),
            },
        )
        result = orchestrator.apply_task_event(event)
        result["workflow_id"] = _normalize_text("workflow_id", workflow_id)
        return _wrap_event_result(result)
    except Exception as exc:
        return _classify_error(exc)


def retry_task(group_id, task_id, workflow_id, project_root, daemon_request_fn):
    try:
        orchestrator = _get_orchestrator_or_raise(group_id, project_root, daemon_request_fn)
        _get_state_or_raise(orchestrator, task_id, workflow_id)
        result = orchestrator.retry_task(_normalize_text("task_id", task_id))
        return _success(result)
    except Exception as exc:
        return _classify_error(exc)


def block_task(group_id, task_id, reason, workflow_id, project_root, daemon_request_fn):
    try:
        orchestrator = _get_orchestrator_or_raise(group_id, project_root, daemon_request_fn)
        _get_state_or_raise(orchestrator, task_id, workflow_id)
        result = orchestrator.block_task(
            _normalize_text("task_id", task_id),
            _normalize_text("reason", reason),
        )
        return _success(result)
    except Exception as exc:
        return _classify_error(exc)


def start_task(group_id, task_id, agent_id, workflow_id, project_root, daemon_request_fn):
    try:
        orchestrator = _get_orchestrator_or_raise(group_id, project_root, daemon_request_fn)
        state = _get_state_or_raise(orchestrator, task_id, workflow_id)
        normalized_task_id = _normalize_text("task_id", task_id)
        normalized_agent_id = _normalize_text("agent_id", agent_id)
        orchestrator.engine.report_worker_started(normalized_task_id, normalized_agent_id)
        return _success(
            {
                "accepted": True,
                "task_id": normalized_task_id,
                "workflow_id": str(getattr(state, "workflow_id", "") or "").strip(),
                "agent_id": normalized_agent_id,
                "status": WorkflowTaskStatus.RUNNING.value,
            }
        )
    except Exception as exc:
        return _classify_error(exc)


def verify_task(group_id, task_id, workflow_id, project_root, daemon_request_fn):
    try:
        orchestrator = _get_orchestrator_or_raise(group_id, project_root, daemon_request_fn)
        state = _get_state_or_raise(orchestrator, task_id, workflow_id)
        if state.status != WorkflowTaskStatus.VERIFYING:
            raise ValueError(f"task not verifying: {task_id} status={state.status.value}")

        normalized_task_id = _normalize_text("task_id", task_id)
        changed_files: list[str] = []
        agent_id = str(getattr(state, "agent_id", "") or "").strip()
        try:
            verification = orchestrator.ralph.verify_completion(
                normalized_task_id,
                changed_files,
                workflow_id=state.workflow_id,
                task_ref=state.task,
            )
        except Exception as exc:
            verification = _build_verification_error(normalized_task_id, state.workflow_id, exc)

        orchestrator.engine.record_verification_result(normalized_task_id, verification)
        notification_error = ""
        if verification.overall_outcome in ("passed", "skipped"):
            orchestrator.on_task_completed(
                task_id=normalized_task_id,
                agent_id=agent_id,
                duration_seconds=DEFAULT_DURATION_SECONDS,
                changed_files=changed_files,
                workflow_id=state.workflow_id,
                verification=verification,
            )
            notification_outcome = verification.overall_outcome  # preserves "passed" or "skipped"
        else:
            orchestrator.on_task_failed(
                task_id=normalized_task_id,
                error_message=verification.summary or "Verification failed",
                agent_name=agent_id,
                verification=verification,
            )
            notification_outcome = "failed"
        try:
            orchestrator._notify_foreman_verification_result(
                task_id=normalized_task_id,
                verification_outcome=notification_outcome,
                evidence_summary="",
                changed_files=changed_files,
            )
        except Exception as exc:
            notification_error = str(exc)

        return _success(
            {
                "accepted": True,
                "task_id": normalized_task_id,
                "workflow_id": state.workflow_id,
                "verification": verification.model_dump(),
                "verification_outcome": verification.overall_outcome,
                "notification_error": notification_error,
            }
        )
    except Exception as exc:
        return _classify_error(exc)


__all__ = [
    "complete_task",
    "fail_task",
    "retry_task",
    "block_task",
    "start_task",
    "verify_task",
]
