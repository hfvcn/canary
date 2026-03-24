"""Web routes for Ralph-Foreman workflow operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..schemas import RouteContext, require_group, require_user


class BatchSuggestRequest(BaseModel):
    workflow_id: str
    tasks: List[Dict[str, Any]]
    rationale: str = ""
    estimated_parallelism: int = 1
    auto_process: bool = False
    feishu_chat_id: Optional[str] = None
    auto_start_agents: bool = True


class ProcessPendingRequest(BaseModel):
    suggestion_id: str
    feishu_chat_id: Optional[str] = None
    auto_start_agents: bool = True


class WorkflowProgressRequest(BaseModel):
    workflow_id: str = ""


class TaskCompletedRequest(BaseModel):
    task_id: str
    agent_id: str
    duration_seconds: int = 0
    changed_files: List[str] = []
    workflow_id: Optional[str] = None


class TaskFailedRequest(BaseModel):
    task_id: str
    error_message: str
    suggestion: str = ""
    agent_name: str = ""


def create_routers(ctx: RouteContext) -> list[APIRouter]:
    """Create workflow-related routers."""

    # Global workflow router
    global_router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

    # Group-scoped workflow router
    group_router = APIRouter(
        prefix="/api/v1/groups/{group_id}/workflow",
        dependencies=[Depends(require_group)],
        tags=["workflow"],
    )

    # ------------------------------------------------------------------ #
    # Global workflow routes
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Group-scoped workflow routes
    # ------------------------------------------------------------------ #

    @group_router.post("/batch/suggest")
    async def submit_batch_suggestion(
        group_id: str,
        req: BatchSuggestRequest,
    ) -> Dict[str, Any]:
        """Submit a batch of tasks for processing."""
        from pathlib import Path
        from ....paths import ensure_home

        # Try to get project root from group scope
        group_resp = await ctx.daemon({"op": "group_show", "args": {"group_id": group_id}})
        project_root = ""
        if group_resp.get("ok"):
            result = group_resp.get("result", {})
            scopes = result.get("scopes", [])
            active_scope = result.get("active_scope_key", "")
            for scope in scopes:
                if scope.get("scope_key") == active_scope:
                    project_root = scope.get("url", "")
                    break

        return await ctx.daemon({
            "op": "ralph_batch_suggest",
            "args": {
                "workflow_id": req.workflow_id,
                "tasks": req.tasks,
                "rationale": req.rationale,
                "estimated_parallelism": req.estimated_parallelism,
                "auto_process": req.auto_process,
                "group_id": group_id,
                "project_root": project_root,
                "feishu_chat_id": req.feishu_chat_id,
                "auto_start_agents": req.auto_start_agents,
            },
        })

    @group_router.post("/batch/process")
    async def process_pending_batch(
        group_id: str,
        req: ProcessPendingRequest,
    ) -> Dict[str, Any]:
        """Process a pending batch suggestion through the workflow."""
        # Get project root from group scope
        group_resp = await ctx.daemon({"op": "group_show", "args": {"group_id": group_id}})
        project_root = ""
        if group_resp.get("ok"):
            result = group_resp.get("result", {})
            scopes = result.get("scopes", [])
            active_scope = result.get("active_scope_key", "")
            for scope in scopes:
                if scope.get("scope_key") == active_scope:
                    project_root = scope.get("url", "")
                    break

        return await ctx.daemon({
            "op": "ralph_process_pending",
            "args": {
                "suggestion_id": req.suggestion_id,
                "group_id": group_id,
                "project_root": project_root,
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
        return await ctx.daemon({
            "op": "ralph_workflow_progress",
            "args": {
                "workflow_id": workflow_id,
                "group_id": group_id,
            },
        })

    @group_router.post("/task/completed")
    async def report_task_completed(
        group_id: str,
        req: TaskCompletedRequest,
    ) -> Dict[str, Any]:
        """Report a task as completed."""
        return await ctx.daemon({
            "op": "ralph_actor_status",
            "args": {
                "actor_id": req.agent_id,
                "actor_type": "worker",
                "workflow_id": req.workflow_id,
                "status": "completed",
                "current_task_id": req.task_id,
                "message": f"Task {req.task_id} completed in {req.duration_seconds}s",
            },
        })

    @group_router.post("/task/failed")
    async def report_task_failed(
        group_id: str,
        req: TaskFailedRequest,
    ) -> Dict[str, Any]:
        """Report a task as failed."""
        return await ctx.daemon({
            "op": "ralph_verification_result",
            "args": {
                "workflow_id": "",
                "task_id": req.task_id,
                "overall_outcome": "failed",
                "summary": req.error_message,
            },
        })

    return [global_router, group_router]
