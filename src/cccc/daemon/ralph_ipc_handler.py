"""
Ralph IPC endpoint handler for CCCC Daemon.

Provides daemon operations for Ralph-Foreman communication:
- ralph_batch_suggest: Ralph suggests a batch of ready tasks
- ralph_verification_result: Ralph reports verification outcome
- ralph_restart_suggest: Ralph suggests task restart
- ralph_batch_decision: Foreman decides on batch suggestion
- ralph_actor_status: Actor status update

Uses existing daemon IPC infrastructure (Unix socket + JSON line protocol).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from ..contracts.v1 import DaemonError, DaemonResponse
from ..contracts.v1.ralph_ipc import (
    ActorStatus,
    BatchDecision,
    ReadyBatchSuggestion,
    RestartSuggestion,
    VerificationResult,
    parse_ralph_message,
)
from ..util.time import utc_now_iso

logger = logging.getLogger("cccc.daemon.ralph_ipc")

# In-memory store for Ralph IPC state (can be extended to persistent storage)
_RALPH_STATE: Dict[str, Any] = {
    "pending_suggestions": {},  # suggestion_id -> ReadyBatchSuggestion
    "pending_restarts": {},     # suggestion_id -> RestartSuggestion
    "decisions": {},            # decision_id -> BatchDecision
    "verifications": {},        # verification_id -> VerificationResult
    "actor_statuses": {},       # actor_id -> ActorStatus
}


def _error(code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> DaemonResponse:
    """Create an error response."""
    return DaemonResponse(ok=False, error=DaemonError(code=code, message=message, details=(details or {})))


def _success(result: Optional[Dict[str, Any]] = None) -> DaemonResponse:
    """Create a success response."""
    return DaemonResponse(ok=True, result=(result or {}))


def _validate_required(args: Dict[str, Any], *fields: str) -> Optional[DaemonResponse]:
    """Validate required fields, return error response if missing."""
    for field in fields:
        if not args.get(field):
            return _error("missing_field", f"Missing required field: {field}")
    return None


def handle_ralph_batch_suggest(args: Dict[str, Any], *, daemon_request_fn: Any = None) -> DaemonResponse:
    """
    Handle ralph_batch_suggest operation.

    Ralph submits a batch of tasks suggested for parallel execution.

    Args:
        workflow_id: Workflow identifier
        tasks: List of task references [{id, title, type}]
        rationale: Why these tasks are suggested together
        estimated_parallelism: Expected parallelism degree
        auto_process: If true, automatically trigger workflow processing
        group_id: Required if auto_process is true
        project_root: Required if auto_process is true
    """
    err = _validate_required(args, "workflow_id", "tasks")
    if err:
        return err

    tasks = args.get("tasks", [])
    if not isinstance(tasks, list) or len(tasks) == 0:
        return _error("invalid_tasks", "Tasks must be a non-empty list")

    suggestion_id = str(args.get("suggestion_id") or uuid4())
    suggestion = ReadyBatchSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=str(args["workflow_id"]),
        tasks=[{"id": t.get("id", ""), "title": t.get("title", ""), "type": t.get("type", "general")} for t in tasks],
        rationale=str(args.get("rationale", "")),
        estimated_parallelism=int(args.get("estimated_parallelism", len(tasks))),
    )

    _RALPH_STATE["pending_suggestions"][suggestion_id] = suggestion.model_dump()
    logger.info(f"Ralph batch suggestion created: {suggestion_id} with {len(tasks)} tasks")

    result: Dict[str, Any] = {
        "suggestion_id": suggestion_id,
        "task_count": len(tasks),
        "created_at": suggestion.created_at,
    }

    # Optionally trigger workflow processing
    if args.get("auto_process"):
        process_result = _try_process_batch(suggestion, args, daemon_request_fn=daemon_request_fn)
        if process_result:
            result["processing"] = process_result

    return _success(result)


def _try_process_batch(
    suggestion: ReadyBatchSuggestion,
    args: Dict[str, Any],
    *,
    daemon_request_fn: Any = None,
) -> Optional[Dict[str, Any]]:
    """Try to process batch through workflow orchestrator."""
    from pathlib import Path

    group_id = str(args.get("group_id") or "").strip()
    project_root = str(args.get("project_root") or "").strip()

    if not group_id or not project_root:
        return {"status": "skipped", "reason": "missing group_id or project_root"}

    try:
        from .foreman.workflow_orchestrator import get_orchestrator

        orchestrator = get_orchestrator(
            group_id,
            project_root=Path(project_root),
            feishu_chat_id=args.get("feishu_chat_id"),
            daemon_request_fn=daemon_request_fn,
        )

        if orchestrator is None:
            return {"status": "skipped", "reason": "orchestrator not available"}

        # Update daemon_request_fn on cached orchestrator (may have been created without it)
        if daemon_request_fn and not orchestrator._daemon_request_fn:
            orchestrator._daemon_request_fn = daemon_request_fn

        result = orchestrator.process_batch_suggestion(
            suggestion,
            auto_start_agents=bool(args.get("auto_start_agents", True)),
        )

        return {
            "status": "processed",
            "decision": result.decision,
            "approved_count": len(result.approved_tasks),
            "rejected_count": len(result.rejected_tasks),
        }
    except Exception as e:
        logger.warning(f"Failed to process batch: {e}")
        return {"status": "error", "error": str(e)}


def handle_ralph_verification_result(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_verification_result operation.

    Ralph reports the outcome of verification (build/test/lint).

    Args:
        workflow_id: Workflow identifier
        task_id: Optional task that triggered verification
        overall_outcome: passed/failed/skipped/timeout
        checks: List of individual check results
        summary: Human-readable summary
    """
    err = _validate_required(args, "workflow_id", "overall_outcome")
    if err:
        return err

    outcome = str(args["overall_outcome"])
    if outcome not in ("passed", "failed", "skipped", "timeout"):
        return _error("invalid_outcome", f"Invalid verification outcome: {outcome}")

    verification_id = str(args.get("verification_id") or uuid4())
    checks = args.get("checks", [])

    verification = VerificationResult(
        verification_id=verification_id,
        workflow_id=str(args["workflow_id"]),
        task_id=args.get("task_id"),
        overall_outcome=outcome,  # type: ignore
        checks=[{
            "name": str(c.get("name", "")),
            "outcome": str(c.get("outcome", "skipped")),
            "message": str(c.get("message", "")),
            "duration_ms": int(c.get("duration_ms", 0)),
            "details": c.get("details", {}),
        } for c in checks],
        summary=str(args.get("summary", "")),
    )

    _RALPH_STATE["verifications"][verification_id] = verification.model_dump()
    logger.info(f"Ralph verification result: {verification_id} - {outcome}")

    return _success({
        "verification_id": verification_id,
        "overall_outcome": outcome,
        "check_count": len(checks),
        "created_at": verification.created_at,
    })


def handle_ralph_restart_suggest(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_restart_suggest operation.

    Ralph suggests restarting a failed or stuck task.

    Args:
        workflow_id: Workflow identifier
        task_id: Task to restart
        task_title: Task title
        task_type: frontend/backend/general
        reason: Why restart is suggested
        previous_attempts: Number of previous attempts
        files_to_adopt: Files from previous attempt to adopt
    """
    err = _validate_required(args, "workflow_id", "task_id")
    if err:
        return err

    suggestion_id = str(args.get("suggestion_id") or uuid4())
    suggestion = RestartSuggestion(
        suggestion_id=suggestion_id,
        workflow_id=str(args["workflow_id"]),
        task={
            "id": str(args["task_id"]),
            "title": str(args.get("task_title", "")),
            "type": args.get("task_type", "general"),
        },
        reason=str(args.get("reason", "")),
        previous_attempts=int(args.get("previous_attempts", 0)),
        files_to_adopt=list(args.get("files_to_adopt", [])),
    )

    _RALPH_STATE["pending_restarts"][suggestion_id] = suggestion.model_dump()
    logger.info(f"Ralph restart suggestion: {suggestion_id} for task {args['task_id']}")

    return _success({
        "suggestion_id": suggestion_id,
        "task_id": str(args["task_id"]),
        "created_at": suggestion.created_at,
    })


def handle_ralph_batch_decision(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_batch_decision operation.

    Foreman decides on a batch suggestion from Ralph.

    Args:
        suggestion_id: ID of the suggestion being decided
        workflow_id: Workflow identifier
        decision: approved/modified/rejected/deferred
        approved_tasks: List of approved task IDs
        rejected_tasks: List of rejected task IDs
        reason: Reason for the decision
    """
    err = _validate_required(args, "suggestion_id", "workflow_id", "decision")
    if err:
        return err

    decision_type = str(args["decision"])
    if decision_type not in ("approved", "modified", "rejected", "deferred"):
        return _error("invalid_decision", f"Invalid decision type: {decision_type}")

    suggestion_id = str(args["suggestion_id"])

    # Check if suggestion exists
    if suggestion_id not in _RALPH_STATE["pending_suggestions"]:
        return _error("suggestion_not_found", f"Suggestion not found: {suggestion_id}")

    decision_id = str(uuid4())
    decision = BatchDecision(
        decision_id=decision_id,
        suggestion_id=suggestion_id,
        workflow_id=str(args["workflow_id"]),
        decision=decision_type,  # type: ignore
        approved_tasks=list(args.get("approved_tasks", [])),
        rejected_tasks=list(args.get("rejected_tasks", [])),
        reason=str(args.get("reason", "")),
    )

    _RALPH_STATE["decisions"][decision_id] = decision.model_dump()

    # Remove from pending if approved or rejected
    if decision_type in ("approved", "rejected"):
        _RALPH_STATE["pending_suggestions"].pop(suggestion_id, None)

    logger.info(f"Batch decision: {decision_id} - {decision_type} for suggestion {suggestion_id}")

    return _success({
        "decision_id": decision_id,
        "decision": decision_type,
        "created_at": decision.created_at,
    })


def handle_ralph_actor_status(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_actor_status operation.

    Actor (Ralph, Foreman, or worker) reports its current status.

    Args:
        actor_id: Unique actor identifier
        actor_type: ralph/foreman/worker/other
        workflow_id: Optional workflow identifier
        status: idle/analyzing/executing/waiting/blocked/completed
        current_task_id: Optional current task
        message: Status message
        progress_pct: Optional progress percentage (0-100)
    """
    err = _validate_required(args, "actor_id", "status")
    if err:
        return err

    status_type = str(args["status"])
    valid_statuses = ("idle", "analyzing", "executing", "waiting", "blocked", "completed")
    if status_type not in valid_statuses:
        return _error("invalid_status", f"Invalid status: {status_type}. Must be one of: {valid_statuses}")

    actor_type = str(args.get("actor_type", "other"))
    if actor_type not in ("ralph", "foreman", "worker", "other"):
        actor_type = "other"

    progress = args.get("progress_pct")
    if progress is not None:
        try:
            progress = max(0, min(100, int(progress)))
        except (ValueError, TypeError):
            progress = None

    actor_status = ActorStatus(
        actor_id=str(args["actor_id"]),
        actor_type=actor_type,  # type: ignore
        workflow_id=args.get("workflow_id"),
        status=status_type,  # type: ignore
        current_task_id=args.get("current_task_id"),
        message=str(args.get("message", "")),
        progress_pct=progress,
    )

    _RALPH_STATE["actor_statuses"][actor_status.actor_id] = actor_status.model_dump()
    logger.debug(f"Actor status update: {actor_status.actor_id} - {status_type}")

    return _success({
        "actor_id": actor_status.actor_id,
        "status": status_type,
        "updated_at": actor_status.updated_at,
    })


def handle_ralph_get_pending(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_get_pending operation.

    Get pending suggestions and verifications for a workflow.

    Args:
        workflow_id: Workflow identifier
        include_decisions: Whether to include past decisions
    """
    workflow_id = str(args.get("workflow_id", ""))

    pending_suggestions = [
        s for s in _RALPH_STATE["pending_suggestions"].values()
        if not workflow_id or s.get("workflow_id") == workflow_id
    ]

    pending_restarts = [
        r for r in _RALPH_STATE["pending_restarts"].values()
        if not workflow_id or r.get("workflow_id") == workflow_id
    ]

    result: Dict[str, Any] = {
        "pending_suggestions": pending_suggestions,
        "pending_restarts": pending_restarts,
    }

    if args.get("include_decisions"):
        decisions = [
            d for d in _RALPH_STATE["decisions"].values()
            if not workflow_id or d.get("workflow_id") == workflow_id
        ]
        result["decisions"] = decisions

    return _success(result)


def handle_ralph_get_actors(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_get_actors operation.

    Get current status of all actors in a workflow.

    Args:
        workflow_id: Optional workflow filter
        actor_type: Optional actor type filter
    """
    workflow_id = args.get("workflow_id")
    actor_type = args.get("actor_type")

    actors = list(_RALPH_STATE["actor_statuses"].values())

    if workflow_id:
        actors = [a for a in actors if a.get("workflow_id") == workflow_id]

    if actor_type:
        actors = [a for a in actors if a.get("actor_type") == actor_type]

    return _success({"actors": actors})


def handle_ralph_clear_workflow(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_clear_workflow operation.

    Clear all Ralph IPC state for a completed workflow.

    Args:
        workflow_id: Workflow identifier to clear
    """
    err = _validate_required(args, "workflow_id")
    if err:
        return err

    workflow_id = str(args["workflow_id"])
    cleared = {"suggestions": 0, "restarts": 0, "decisions": 0, "verifications": 0, "actors": 0}

    # Clear pending suggestions
    to_remove = [k for k, v in _RALPH_STATE["pending_suggestions"].items() if v.get("workflow_id") == workflow_id]
    for k in to_remove:
        _RALPH_STATE["pending_suggestions"].pop(k, None)
        cleared["suggestions"] += 1

    # Clear pending restarts
    to_remove = [k for k, v in _RALPH_STATE["pending_restarts"].items() if v.get("workflow_id") == workflow_id]
    for k in to_remove:
        _RALPH_STATE["pending_restarts"].pop(k, None)
        cleared["restarts"] += 1

    # Clear decisions
    to_remove = [k for k, v in _RALPH_STATE["decisions"].items() if v.get("workflow_id") == workflow_id]
    for k in to_remove:
        _RALPH_STATE["decisions"].pop(k, None)
        cleared["decisions"] += 1

    # Clear verifications
    to_remove = [k for k, v in _RALPH_STATE["verifications"].items() if v.get("workflow_id") == workflow_id]
    for k in to_remove:
        _RALPH_STATE["verifications"].pop(k, None)
        cleared["verifications"] += 1

    # Clear actor statuses
    to_remove = [k for k, v in _RALPH_STATE["actor_statuses"].items() if v.get("workflow_id") == workflow_id]
    for k in to_remove:
        _RALPH_STATE["actor_statuses"].pop(k, None)
        cleared["actors"] += 1

    logger.info(f"Cleared Ralph state for workflow {workflow_id}: {cleared}")

    return _success({"workflow_id": workflow_id, "cleared": cleared})


def handle_ralph_process_pending(args: Dict[str, Any], *, daemon_request_fn: Any = None) -> DaemonResponse:
    """
    Handle ralph_process_pending operation.

    Explicitly process a pending batch suggestion through the workflow.

    Args:
        suggestion_id: ID of pending suggestion to process
        group_id: CCCC group ID
        project_root: Project root directory
        feishu_chat_id: Optional Feishu chat ID for notifications
        auto_start_agents: Whether to auto-start assigned agents (default true)
    """
    from pathlib import Path

    err = _validate_required(args, "suggestion_id", "group_id", "project_root")
    if err:
        return err

    suggestion_id = str(args["suggestion_id"])
    group_id = str(args["group_id"])
    project_root = Path(str(args["project_root"]))

    # Find pending suggestion
    suggestion_data = _RALPH_STATE["pending_suggestions"].get(suggestion_id)
    if not suggestion_data:
        return _error("suggestion_not_found", f"Pending suggestion not found: {suggestion_id}")

    # Reconstruct suggestion object
    suggestion = ReadyBatchSuggestion(
        suggestion_id=suggestion_data["suggestion_id"],
        workflow_id=suggestion_data["workflow_id"],
        tasks=suggestion_data["tasks"],
        rationale=suggestion_data.get("rationale", ""),
        estimated_parallelism=suggestion_data.get("estimated_parallelism", 1),
    )

    try:
        from .foreman.workflow_orchestrator import get_orchestrator

        orchestrator = get_orchestrator(
            group_id,
            project_root=project_root,
            feishu_chat_id=args.get("feishu_chat_id"),
            daemon_request_fn=daemon_request_fn,
        )

        if orchestrator is None:
            return _error("orchestrator_unavailable", "Failed to initialize workflow orchestrator")

        # Update daemon_request_fn on cached orchestrator
        if daemon_request_fn and not orchestrator._daemon_request_fn:
            orchestrator._daemon_request_fn = daemon_request_fn

        result = orchestrator.process_batch_suggestion(
            suggestion,
            auto_start_agents=bool(args.get("auto_start_agents", True)),
        )

        # Generate batch decision
        decision = orchestrator.get_batch_decision(result)

        # Store decision
        _RALPH_STATE["decisions"][decision.decision_id] = decision.model_dump()

        # Remove from pending if approved or rejected
        if result.decision in ("approved", "rejected"):
            _RALPH_STATE["pending_suggestions"].pop(suggestion_id, None)

        logger.info(f"Processed pending suggestion {suggestion_id}: {result.decision}")

        return _success({
            "suggestion_id": suggestion_id,
            "decision_id": decision.decision_id,
            "decision": result.decision,
            "approved_tasks": [t.id for t in result.approved_tasks],
            "rejected_tasks": [t.id for t in result.rejected_tasks],
            "reason": result.reason,
        })

    except Exception as e:
        logger.error(f"Failed to process pending suggestion {suggestion_id}: {e}")
        return _error("processing_failed", f"Failed to process suggestion: {e}")


def handle_ralph_workflow_progress(args: Dict[str, Any]) -> DaemonResponse:
    """
    Handle ralph_workflow_progress operation.

    Get workflow progress from the orchestrator.

    Args:
        workflow_id: Workflow identifier
        group_id: CCCC group ID
    """
    workflow_id = str(args.get("workflow_id") or "").strip()
    group_id = str(args.get("group_id") or "").strip()

    if not group_id:
        return _error("missing_group_id", "Missing group_id")

    try:
        from .foreman.workflow_orchestrator import get_orchestrator

        orchestrator = get_orchestrator(group_id)
        if orchestrator is None:
            return _error("orchestrator_not_found", "No active orchestrator for group")

        state = orchestrator.get_workflow_state(workflow_id)
        return _success(state)

    except Exception as e:
        logger.warning(f"Failed to get workflow progress: {e}")
        return _error("progress_error", f"Failed to get progress: {e}")


# Operation dispatcher
_RALPH_OPS = {
    "ralph_batch_suggest": handle_ralph_batch_suggest,
    "ralph_verification_result": handle_ralph_verification_result,
    "ralph_restart_suggest": handle_ralph_restart_suggest,
    "ralph_batch_decision": handle_ralph_batch_decision,
    "ralph_actor_status": handle_ralph_actor_status,
    "ralph_get_pending": handle_ralph_get_pending,
    "ralph_get_actors": handle_ralph_get_actors,
    "ralph_clear_workflow": handle_ralph_clear_workflow,
    "ralph_process_pending": handle_ralph_process_pending,
    "ralph_workflow_progress": handle_ralph_workflow_progress,
}


def try_handle_ralph_op(
    op: str,
    args: Dict[str, Any],
    *,
    daemon_request_fn: Any = None,
) -> Optional[DaemonResponse]:
    """
    Try to handle a Ralph IPC operation.

    Returns None if the operation is not a Ralph operation.
    Returns DaemonResponse if handled.

    Args:
        daemon_request_fn: Optional callback to dispatch daemon requests
            (used to register foreman agents as real group actors).
    """
    handler = _RALPH_OPS.get(op)
    if handler is None:
        return None
    # Inject daemon_request_fn for handlers that need it
    if op in ("ralph_batch_suggest", "ralph_process_pending"):
        return handler(args, daemon_request_fn=daemon_request_fn)
    return handler(args)
