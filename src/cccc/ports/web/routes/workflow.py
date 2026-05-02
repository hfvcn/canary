"""Web routes for Ralph-Foreman workflow operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator
from cccc.daemon.ops.workflow_task_ops import complete_task, fail_task, retry_task

from ..schemas import RouteContext, require_group


async def resolve_group_runtime_context(ctx: RouteContext, group_id: str) -> Dict[str, Any]:
    """Unified helper to extract group scope / project_root for workflow ops."""
    group_resp = await ctx.daemon({"op": "group_show", "args": {"group_id": group_id}})
    raw_result = (group_resp or {}).get("result", {})
    group_data = raw_result.get("group") if isinstance(raw_result, dict) else {}
    if not isinstance(group_data, dict):
        group_data = {}
    active_scope = str(group_data.get("active_scope_key") or "").strip()
    project_root = str(group_data.get("project_root") or "").strip()
    if not project_root:
        for scope in group_data.get("scopes", []):
            if isinstance(scope, dict) and scope.get("scope_key") == active_scope:
                project_root = str(scope.get("url") or "").strip()
                break
    return {"group_id": group_id, "project_root": project_root, "active_scope": active_scope}


def _require_task_state(group_id: str, project_root: str, task_id: str) -> Any:
    orchestrator = get_orchestrator(group_id, project_root=Path(project_root) if project_root else None)
    if orchestrator is None:
        raise ValueError("No active orchestrator for group")
    state = orchestrator.engine.get_task(str(task_id or "").strip())
    if state is None:
        raise ValueError(f"task not found: {task_id}")
    return state


def _format_workflow_op(result: Dict[str, Any], *, error_code: str, error_prefix: str, event_type: str = "") -> Dict[str, Any]:
    if result.get("ok"):
        payload = dict(result.get("result") or {})
        if event_type:
            payload["event_type"] = event_type
            payload.pop("workflow_id", None)
        return {"ok": True, "result": payload, "error": {}}
    raw = dict(result.get("error") or {})
    if raw.get("code") == "orchestrator_not_found" or str(raw.get("message") or "").strip() == "No active orchestrator for group":
        return {"ok": False, "result": {}, "error": {"code": "orchestrator_not_found", "message": "No active orchestrator for group"}}
    message = str(raw.get("message") or "").strip() or error_prefix
    return {"ok": False, "result": {}, "error": {"code": error_code, "message": f"{error_prefix}: {message}"}}


class BatchSuggestRequest(BaseModel):
    workflow_id: str
    tasks: List[Dict[str, Any]]
    rationale: str = ""
    estimated_parallelism: int = 1
    auto_process: bool = True
    feishu_chat_id: Optional[str] = None
    auto_start_agents: bool = True
    assignments: Dict[str, str] = {}  # ARCH-1: task_id → actor_id
    auto_dispatch: bool = False
    assignment_map: Dict[str, str] = {}


class ProcessPendingRequest(BaseModel):
    suggestion_id: str
    feishu_chat_id: Optional[str] = None
    auto_start_agents: bool = True

class TaskCompletedRequest(BaseModel):
    task_id: str
    agent_id: str
    assignment_id: str = ""
    actor_run_id: str = ""
    idempotency_key: str = ""
    duration_seconds: int = 0
    changed_files: List[str] = []
    workflow_id: Optional[str] = None


class TaskFailedRequest(BaseModel):
    task_id: str
    error_message: str
    assignment_id: str = ""
    actor_run_id: str = ""
    idempotency_key: str = ""
    suggestion: str = ""
    agent_name: str = ""

class TaskRetryRequest(BaseModel):
    task_id: str

class TaskBlockRequest(BaseModel):
    task_id: str
    reason: str

def create_routers(ctx: RouteContext) -> list[APIRouter]:
    """Create workflow-related routers."""
    global_router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])
    group_router = APIRouter(
        prefix="/api/v1/groups/{group_id}/workflow",
        dependencies=[Depends(require_group)],
        tags=["workflow"],
    )

    @global_router.get("/pending")
    async def get_pending_suggestions(
        workflow_id: str = "",
        include_decisions: bool = False,
    ) -> Dict[str, Any]:
        """Get all pending batch suggestions and decisions."""
        return await ctx.daemon({
            "op": "ralph_get_pending",
            "args": {
                "workflow_id": workflow_id,
                "include_decisions": include_decisions,
            },
        })

    @global_router.get("/actors")
    async def get_workflow_actors(
        workflow_id: str = "",
        actor_type: str = "",
    ) -> Dict[str, Any]:
        """Get actor statuses for a workflow."""
        return await ctx.daemon({
            "op": "ralph_get_actors",
            "args": {
                "workflow_id": workflow_id,
                "actor_type": actor_type,
            },
        })

    @global_router.post("/clear")
    async def clear_workflow(workflow_id: str) -> Dict[str, Any]:
        """Clear all state for a completed workflow."""
        return await ctx.daemon({
            "op": "ralph_clear_workflow",
            "args": {"workflow_id": workflow_id},
        })

    @group_router.post("/batch/suggest")
    async def submit_batch_suggestion(
        group_id: str,
        req: BatchSuggestRequest,
    ) -> Dict[str, Any]:
        """Submit a batch of tasks for processing."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)

        return await ctx.daemon({
            "op": "ralph_batch_suggest",
            "args": {
                "workflow_id": req.workflow_id,
                "tasks": req.tasks,
                "rationale": req.rationale,
                "estimated_parallelism": req.estimated_parallelism,
                "auto_process": req.auto_process,
                "group_id": group_id,
                "project_root": runtime_ctx["project_root"],
                "feishu_chat_id": req.feishu_chat_id,
                "auto_start_agents": req.auto_start_agents,
                "assignments": req.assignments,
                "auto_dispatch": req.auto_dispatch,
                "assignment_map": req.assignment_map,
            },
        })

    @group_router.post("/batch/process")
    async def process_pending_batch(
        group_id: str,
        req: ProcessPendingRequest,
    ) -> Dict[str, Any]:
        """Process a pending batch suggestion through the workflow."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)

        return await ctx.daemon({
            "op": "ralph_process_pending",
            "args": {
                "suggestion_id": req.suggestion_id,
                "group_id": group_id,
                "project_root": runtime_ctx["project_root"],
                "feishu_chat_id": req.feishu_chat_id,
                "auto_start_agents": req.auto_start_agents,
            },
        })

    @group_router.get("/progress")
    async def get_workflow_progress(
        group_id: str,
        workflow_id: str = "",
    ) -> Dict[str, Any]:
        """Get current workflow progress."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)
        return await ctx.daemon({
            "op": "ralph_workflow_progress",
            "args": {
                "workflow_id": workflow_id,
                "group_id": group_id,
                "project_root": runtime_ctx["project_root"],
            },
        })

    @group_router.get("/health")
    async def get_workflow_health(group_id: str) -> Dict[str, Any]:
        """Workflow wiring health (orchestrator + ledger)."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)
        return await ctx.daemon(
            {
                "op": "ralph_workflow_health",
                "args": {
                    "group_id": group_id,
                    "project_root": runtime_ctx["project_root"],
                },
            }
        )

    @group_router.post("/task/completed")
    async def report_task_completed(
        group_id: str,
        req: TaskCompletedRequest,
    ) -> Dict[str, Any]:
        """Report a task as completed via unified task event."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)
        try:
            workflow_id = str(req.workflow_id or "").strip() or str(_require_task_state(group_id, runtime_ctx["project_root"], req.task_id).workflow_id or "").strip()
            result = complete_task(group_id, req.task_id, req.agent_id, req.changed_files or [], {}, workflow_id, runtime_ctx["project_root"], None, assignment_id=req.assignment_id, actor_run_id=req.actor_run_id)
        except Exception as exc:
            result = {"ok": False, "result": {}, "error": {"message": str(exc)}}
        return _format_workflow_op(result, error_code="task_event_error", error_prefix="Failed to process task event", event_type="completed")

    @group_router.post("/task/failed")
    async def report_task_failed(
        group_id: str,
        req: TaskFailedRequest,
    ) -> Dict[str, Any]:
        """Report a task as failed via unified task event."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)
        try:
            state = _require_task_state(group_id, runtime_ctx["project_root"], req.task_id)
            result = fail_task(
                group_id,
                req.task_id,
                str(getattr(state, "agent_id", "") or req.agent_name),
                req.error_message,
                str(getattr(state, "workflow_id", "") or "").strip(),
                runtime_ctx["project_root"],
                None,
            )
        except Exception as exc:
            result = {"ok": False, "result": {}, "error": {"message": str(exc)}}
        return _format_workflow_op(result, error_code="task_event_error", error_prefix="Failed to process task event", event_type="failed")

    @group_router.post("/task/retry")
    async def request_task_retry(group_id: str, req: TaskRetryRequest) -> Dict[str, Any]:
        """Foreman decision: request retry for a task after verification failure."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)
        try:
            workflow_id = str(_require_task_state(group_id, runtime_ctx["project_root"], req.task_id).workflow_id or "").strip()
            result = retry_task(group_id, req.task_id, workflow_id, runtime_ctx["project_root"], None)
        except Exception as exc:
            result = {"ok": False, "result": {}, "error": {"message": str(exc)}}
        return _format_workflow_op(result, error_code="task_retry_error", error_prefix="Failed to request task retry")

    @group_router.post("/task/block")
    async def request_task_block(group_id: str, req: TaskBlockRequest) -> Dict[str, Any]:
        """Foreman decision: block a task with a reason."""
        runtime_ctx = await resolve_group_runtime_context(ctx, group_id)
        return await ctx.daemon(
            {
                "op": "ralph_task_block",
                "args": {
                    "group_id": group_id,
                    "project_root": runtime_ctx["project_root"],
                    "task_id": req.task_id,
                    "reason": req.reason,
                },
            }
        )

    return [global_router, group_router]
