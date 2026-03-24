"""Model management API routes.

Provides endpoints for:
- Listing available models for each runtime
- Updating model descriptions
- Recording Foreman ratings
- Managing model visibility (enable/disable)
- Adding custom models
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ....daemon.ops.model_ops import (
    list_models_for_runtime,
    list_all_models,
    get_model_info,
    update_model_description,
    rate_model_by_foreman,
    request_model_review,
    toggle_model_enabled,
    add_custom_model,
    delete_custom_model,
    get_supported_runtimes,
    detect_runtime_availability,
)
from ..schemas import RouteContext, require_user


# Request/Response models

class ModelInfoResponse(BaseModel):
    """Model information response."""

    model_key: str
    model_id: str
    runtime: str
    display_name: str
    context_window: str = "128k"
    description: str = ""
    best_for: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    enabled: bool = True
    is_custom: bool = False
    foreman_rating: Optional[float] = None
    foreman_notes: str = ""
    foreman_sample_count: int = 0
    last_rated_at: Optional[str] = None


class UpdateModelRequest(BaseModel):
    """Request to update model description."""

    description: Optional[str] = None
    best_for: Optional[str] = None
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None


class ToggleModelRequest(BaseModel):
    """Request to toggle model enabled status."""

    enabled: bool


class AddCustomModelRequest(BaseModel):
    """Request to add a custom model."""

    runtime: str
    model_id: str
    display_name: str = ""
    description: str = ""
    context_window: str = "128k"
    strengths: List[str] = Field(default_factory=list)


class RateModelRequest(BaseModel):
    """Request to rate a model."""

    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    notes: str = ""
    workflow_id: Optional[str] = None  # Optional workflow reference


class ModelsListResponse(BaseModel):
    """Response for models list."""

    ok: bool = True
    models: List[ModelInfoResponse] = Field(default_factory=list)
    runtimes: List[str] = Field(default_factory=list)
    runtime_availability: Dict[str, bool] = Field(default_factory=dict)


class ModelUpdateResponse(BaseModel):
    """Response for model update."""

    ok: bool
    model_key: str = ""
    error: str = ""


class ModelRateResponse(BaseModel):
    """Response for model rating."""

    ok: bool
    model_key: str = ""
    new_rating: Optional[float] = None
    sample_count: int = 0
    error: str = ""


class ModelReviewResponse(BaseModel):
    """Response for model review (Foreman comment)."""

    ok: bool
    model_key: str = ""
    comment: str = ""
    status: str = ""  # "sent" when request sent to foreman
    error: str = ""


class ModelReviewRequest(BaseModel):
    """Request to review a model."""

    group_id: str = ""  # Group where foreman is running


class AddCustomModelResponse(BaseModel):
    """Response for adding custom model."""

    ok: bool
    model_key: str = ""
    error: str = ""


def create_routers(ctx: RouteContext) -> list[APIRouter]:
    """Create model-related routers."""

    router = APIRouter(
        prefix="/api/v1/models",
        tags=["models"],
        dependencies=[Depends(require_user)],
    )

    def _get_registry_path() -> Path:
        """Get the models registry path from context."""
        # Use home directory's default location
        return ctx.home / ".cccc" / "models" / "registry.yaml"

    @router.get("", response_model=ModelsListResponse)
    async def list_models(
        runtime: Optional[str] = Query(None, description="Filter by runtime (claude, gemini, codex)"),
        include_disabled: bool = Query(False, description="Include disabled models"),
    ) -> ModelsListResponse:
        """List available models.

        If runtime is specified, only models for that runtime are returned.
        Otherwise, all models are returned.
        """
        registry_path = _get_registry_path()
        runtimes = get_supported_runtimes()

        # Get runtime availability
        availability = detect_runtime_availability()

        if runtime:
            if runtime not in runtimes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown runtime: {runtime}. Supported: {runtimes}",
                )
            model_infos = list_models_for_runtime(
                runtime,
                registry_path,
                include_disabled=include_disabled,
            )
        else:
            model_infos = list_all_models(
                registry_path,
                include_disabled=include_disabled,
            )

        models = [
            ModelInfoResponse(**info.to_dict())
            for info in model_infos
        ]

        return ModelsListResponse(
            ok=True,
            models=models,
            runtimes=runtimes,
            runtime_availability=availability,
        )

    @router.get("/{model_key}", response_model=ModelInfoResponse)
    async def get_model(model_key: str) -> ModelInfoResponse:
        """Get information about a specific model."""
        registry_path = _get_registry_path()

        info = get_model_info(model_key, registry_path)
        if info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Model not found: {model_key}",
            )

        return ModelInfoResponse(**info.to_dict())

    @router.put("/{model_key}", response_model=ModelUpdateResponse)
    async def update_model(model_key: str, body: UpdateModelRequest) -> ModelUpdateResponse:
        """Update model description and metadata.

        Users can add descriptions, best-for text, and customize
        strengths/weaknesses for any model.
        """
        registry_path = _get_registry_path()

        # Ensure parent directory exists
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        success = update_model_description(
            model_key,
            registry_path,
            description=body.description,
            best_for=body.best_for,
            strengths=body.strengths,
            weaknesses=body.weaknesses,
        )

        if not success:
            return ModelUpdateResponse(
                ok=False,
                model_key=model_key,
                error="Failed to update model",
            )

        return ModelUpdateResponse(ok=True, model_key=model_key)

    @router.post("/{model_key}/toggle", response_model=ModelUpdateResponse)
    async def toggle_model(model_key: str, body: ToggleModelRequest) -> ModelUpdateResponse:
        """Enable or disable a model.

        Disabled models won't appear in the model picker, but their
        configuration is preserved.
        """
        registry_path = _get_registry_path()
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        success = toggle_model_enabled(
            model_key,
            registry_path,
            enabled=body.enabled,
        )

        if not success:
            return ModelUpdateResponse(
                ok=False,
                model_key=model_key,
                error="Failed to toggle model",
            )

        return ModelUpdateResponse(ok=True, model_key=model_key)

    @router.post("/{model_key}/rate", response_model=ModelRateResponse)
    async def rate_model(model_key: str, body: RateModelRequest) -> ModelRateResponse:
        """Record a Foreman rating for a model.

        This endpoint should only be called when the user explicitly
        requests a model evaluation. Foreman analyzes workflow history
        to generate ratings.
        """
        registry_path = _get_registry_path()

        # Ensure parent directory exists
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            success = rate_model_by_foreman(
                model_key,
                registry_path,
                rating=body.rating,
                notes=body.notes,
            )
        except ValueError as e:
            return ModelRateResponse(
                ok=False,
                model_key=model_key,
                error=str(e),
            )

        if not success:
            return ModelRateResponse(
                ok=False,
                model_key=model_key,
                error="Failed to save rating",
            )

        # Get updated info
        info = get_model_info(model_key, registry_path)
        new_rating = info.foreman_rating if info else None
        sample_count = info.foreman_sample_count if info else 0

        return ModelRateResponse(
            ok=True,
            model_key=model_key,
            new_rating=new_rating,
            sample_count=sample_count,
        )

    @router.post("/{model_key}/review", response_model=ModelReviewResponse)
    async def review_model(model_key: str, body: ModelReviewRequest) -> ModelReviewResponse:
        """Request Foreman to generate a brief comment about a model.

        This sends a request to Foreman to evaluate the model based on
        its usage history. The evaluation is asynchronous - Foreman will
        save its comment when complete.
        """
        registry_path = _get_registry_path()
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Check model exists and has usage history
        info = get_model_info(model_key, registry_path)
        if info is None:
            return ModelReviewResponse(
                ok=False,
                model_key=model_key,
                error=f"Model not found: {model_key}",
            )

        if info.foreman_sample_count == 0:
            return ModelReviewResponse(
                ok=False,
                model_key=model_key,
                error="No usage history. Run tasks with this model first.",
            )

        # If already has a comment, return it
        if info.foreman_notes:
            return ModelReviewResponse(
                ok=True,
                model_key=model_key,
                comment=info.foreman_notes,
            )

        # Need to request evaluation from Foreman
        group_id = body.group_id
        if not group_id:
            return ModelReviewResponse(
                ok=False,
                model_key=model_key,
                error="group_id required to send request to Foreman",
            )

        # Build evaluation prompt for Foreman
        usage_tags = [t for t in (info.tags or []) if t.startswith("usage:")]
        usage_summary = []
        for tag in usage_tags[-5:]:
            parts = tag.split(":")
            if len(parts) >= 4:
                _, task_id, duration, files = parts[:4]
                usage_summary.append(f"- Task {task_id}: {duration}s, {files} files")

        prompt = f"""[Model Evaluation Request]

Please evaluate model: {model_key}

Usage statistics:
- Total tasks completed: {info.foreman_sample_count}

Recent task history:
{chr(10).join(usage_summary) if usage_summary else "No detailed history available"}

Current description (user-provided):
{info.description or "None"}

Please provide a brief, objective comment (1-2 sentences) about this model's performance based on the usage data. Focus on practical observations.

After writing your comment, save it using:
cccc_memory(action="set", key="model_comment:{model_key}", value="<your comment>")
"""

        try:
            # Send message to Foreman via daemon
            result = await ctx.daemon(
                op="chat_send",
                args={
                    "group_id": group_id,
                    "to": "foreman",
                    "text": prompt,
                    "sender": "system",
                },
            )
            if result.get("ok"):
                return ModelReviewResponse(
                    ok=True,
                    model_key=model_key,
                    status="sent",
                )
            else:
                return ModelReviewResponse(
                    ok=False,
                    model_key=model_key,
                    error=result.get("error", "Failed to send to Foreman"),
                )
        except Exception as e:
            return ModelReviewResponse(
                ok=False,
                model_key=model_key,
                error=f"Failed to send evaluation request: {e}",
            )

    @router.delete("/{model_key}", response_model=ModelUpdateResponse)
    async def delete_model(model_key: str) -> ModelUpdateResponse:
        """Delete a custom model.

        Only custom models can be deleted. Predefined models can only be disabled.
        """
        registry_path = _get_registry_path()

        success = delete_custom_model(model_key, registry_path)

        if not success:
            return ModelUpdateResponse(
                ok=False,
                model_key=model_key,
                error="Cannot delete: model not found or is not a custom model",
            )

        return ModelUpdateResponse(ok=True, model_key=model_key)

    @router.post("/custom", response_model=AddCustomModelResponse)
    async def add_model(body: AddCustomModelRequest) -> AddCustomModelResponse:
        """Add a custom model.

        Use this when the predefined model list doesn't include a model
        that you want to use.
        """
        registry_path = _get_registry_path()
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        runtimes = get_supported_runtimes()
        if body.runtime not in runtimes:
            return AddCustomModelResponse(
                ok=False,
                error=f"Unknown runtime: {body.runtime}. Supported: {runtimes}",
            )

        model_key = add_custom_model(
            body.runtime,
            body.model_id,
            registry_path,
            display_name=body.display_name,
            description=body.description,
            context_window=body.context_window,
            strengths=body.strengths,
        )

        if not model_key:
            return AddCustomModelResponse(
                ok=False,
                error="Failed to add custom model",
            )

        return AddCustomModelResponse(ok=True, model_key=model_key)

    # Separate router for runtime-related endpoints
    runtime_router = APIRouter(
        prefix="/api/v1/runtimes",
        tags=["models"],
        dependencies=[Depends(require_user)],
    )

    @runtime_router.get("/models")
    async def get_models_by_runtime(
        runtime: str = Query(..., description="Runtime name (claude, gemini, codex)"),
        include_disabled: bool = Query(False, description="Include disabled models"),
    ) -> Dict[str, Any]:
        """Get models for a specific runtime."""
        registry_path = _get_registry_path()
        runtimes = get_supported_runtimes()

        if runtime not in runtimes:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown runtime: {runtime}. Supported: {runtimes}",
            )

        model_infos = list_models_for_runtime(
            runtime,
            registry_path,
            include_disabled=include_disabled,
        )
        models = [info.to_dict() for info in model_infos]

        return {
            "ok": True,
            "runtime": runtime,
            "models": models,
        }

    @runtime_router.get("/availability")
    async def get_runtime_availability() -> Dict[str, Any]:
        """Check which runtimes are available on the system."""
        availability = detect_runtime_availability()
        runtimes = get_supported_runtimes()

        return {
            "ok": True,
            "runtimes": runtimes,
            "availability": availability,
        }

    return [router, runtime_router]
