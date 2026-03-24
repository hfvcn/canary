"""Model registry operations - list, update, rate models.

This module provides:
- Predefined model lists for each supported runtime (claude, gemini, codex)
- Functions to list, update, and rate models
- Integration with the model registry YAML file
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .agent_ops import load_model_registry, save_model_registry
from ...contracts.v1.agent import ModelCapability, ModelRegistry
from ...util.time import utc_now_iso


# Supported runtimes - models are manually added by users
SUPPORTED_RUNTIMES = ["claude", "gemini", "codex"]


@dataclass
class ModelInfo:
    """Information about a model."""

    model_key: str           # Unique key like "claude-sonnet-4-6"
    model_id: str            # Model identifier used by the CLI
    runtime: str             # Runtime (claude, gemini, codex)
    display_name: str        # Human-readable name
    context_window: str      # Context window size
    description: str = ""    # User-added description
    best_for: str = ""       # Best use cases (user-added)
    strengths: List[str] = None  # Model strengths
    weaknesses: List[str] = None # Model weaknesses
    enabled: bool = True     # Whether to show in model picker
    is_custom: bool = False  # Whether this is a user-added custom model
    foreman_rating: Optional[float] = None  # Foreman rating (1-5)
    foreman_notes: str = ""  # Foreman rating notes
    foreman_sample_count: int = 0  # Number of workflows rated
    last_rated_at: Optional[str] = None  # Last rating timestamp

    def __post_init__(self):
        if self.strengths is None:
            self.strengths = []
        if self.weaknesses is None:
            self.weaknesses = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_key": self.model_key,
            "model_id": self.model_id,
            "runtime": self.runtime,
            "display_name": self.display_name,
            "context_window": self.context_window,
            "description": self.description,
            "best_for": self.best_for,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "enabled": self.enabled,
            "is_custom": self.is_custom,
            "foreman_rating": self.foreman_rating,
            "foreman_notes": self.foreman_notes,
            "foreman_sample_count": self.foreman_sample_count,
            "last_rated_at": self.last_rated_at,
        }


def _generate_model_key(runtime: str, model_id: str) -> str:
    """Generate a unique model key from runtime and model_id."""
    # Normalize model_id to create a key
    # e.g., "claude-sonnet-4-6" -> "claude-sonnet-4-6"
    # e.g., "gpt-5.4" -> "codex-gpt-5.4"
    if model_id.startswith(runtime):
        return model_id
    return f"{runtime}-{model_id}"


def list_models_for_runtime(
    runtime: str,
    registry_path: Path,
    *,
    include_disabled: bool = False,
    include_all: bool = False,
) -> List[ModelInfo]:
    """Get available models for a specific runtime.

    Only returns user-added models from the registry.

    Args:
        runtime: The runtime (claude, gemini, codex)
        registry_path: Path to the models registry YAML file
        include_disabled: If True, include disabled models (for management UI)
        include_all: If True, include all models regardless of enabled status

    Returns:
        List of ModelInfo objects
    """
    registry = load_model_registry(registry_path)
    result = []

    # Only return user-added models from registry
    for model_key, reg_model in registry.models.items():
        if reg_model.runtime != runtime:
            continue

        # Check enabled status
        if not include_all and not include_disabled and not reg_model.enabled:
            continue

        info = ModelInfo(
            model_key=model_key,
            model_id=reg_model.model_id or model_key,
            runtime=runtime,
            display_name=reg_model.model_id or model_key,
            context_window=reg_model.context_window,
            description=reg_model.description,
            best_for=reg_model.best_for,
            strengths=reg_model.strengths or [],
            weaknesses=reg_model.weaknesses or [],
            enabled=reg_model.enabled,
            is_custom=True,
            foreman_rating=reg_model.foreman_rating,
            foreman_notes=reg_model.foreman_notes,
            foreman_sample_count=reg_model.foreman_sample_count,
            last_rated_at=reg_model.last_rated_at,
        )
        result.append(info)

    return result


def list_all_models(
    registry_path: Path,
    *,
    include_disabled: bool = False,
    include_all: bool = False,
) -> List[ModelInfo]:
    """List all available models across all runtimes.

    Args:
        registry_path: Path to the models registry YAML file
        include_disabled: If True, include disabled models
        include_all: If True, include all models regardless of status

    Returns:
        List of all ModelInfo objects
    """
    result = []
    for runtime in SUPPORTED_RUNTIMES:
        result.extend(list_models_for_runtime(
            runtime,
            registry_path,
            include_disabled=include_disabled,
            include_all=include_all,
        ))
    return result


def get_model_info(
    model_key: str,
    registry_path: Path,
) -> Optional[ModelInfo]:
    """Get information about a specific model.

    Args:
        model_key: The model key (e.g., "claude-sonnet-4-6")
        registry_path: Path to the models registry YAML file

    Returns:
        ModelInfo if found, None otherwise
    """
    # Find the runtime from the model key
    for runtime in SUPPORTED_RUNTIMES:
        models = list_models_for_runtime(runtime, registry_path, include_all=True)
        for model in models:
            if model.model_key == model_key:
                return model
    return None


def update_model_description(
    model_key: str,
    registry_path: Path,
    *,
    description: Optional[str] = None,
    best_for: Optional[str] = None,
    strengths: Optional[List[str]] = None,
    weaknesses: Optional[List[str]] = None,
) -> bool:
    """Update model description and metadata.

    Args:
        model_key: The model key to update
        registry_path: Path to the models registry YAML file
        description: New description (optional)
        best_for: New best_for text (optional)
        strengths: New strengths list (optional)
        weaknesses: New weaknesses list (optional)

    Returns:
        True if successful, False otherwise
    """
    registry = load_model_registry(registry_path)
    model = registry.get_model(model_key)

    if model is None:
        # Create new entry
        # Extract runtime from model_key
        runtime = model_key.split("-")[0] if "-" in model_key else "unknown"
        model = ModelCapability(runtime=runtime, model_id=model_key)

    # Update fields if provided
    if description is not None:
        model.description = description
    if best_for is not None:
        model.best_for = best_for
    if strengths is not None:
        model.strengths = strengths
    if weaknesses is not None:
        model.weaknesses = weaknesses

    registry.models[model_key] = model
    return save_model_registry(registry, registry_path)


def rate_model_by_foreman(
    model_key: str,
    registry_path: Path,
    *,
    rating: int,  # 1-5
    notes: str = "",
    sample_count: int = 1,
) -> bool:
    """Record a Foreman rating for a model.

    This should only be called when the user explicitly requests
    a model evaluation.

    Args:
        model_key: The model key to rate
        registry_path: Path to the models registry YAML file
        rating: Rating from 1-5
        notes: Optional notes about the rating
        sample_count: Number of workflows this rating is based on

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If rating is not 1-5
    """
    if not 1 <= rating <= 5:
        raise ValueError("Rating must be between 1 and 5")

    registry = load_model_registry(registry_path)
    model = registry.get_model(model_key)

    if model is None:
        # Create new entry
        runtime = model_key.split("-")[0] if "-" in model_key else "unknown"
        model = ModelCapability(runtime=runtime, model_id=model_key)

    # Calculate weighted average if existing rating
    if model.foreman_rating is not None and model.foreman_sample_count > 0:
        total_weight = model.foreman_sample_count + sample_count
        weighted_rating = (
            model.foreman_rating * model.foreman_sample_count +
            rating * sample_count
        ) / total_weight
        model.foreman_rating = round(weighted_rating, 1)
        model.foreman_sample_count = total_weight
    else:
        model.foreman_rating = float(rating)
        model.foreman_sample_count = sample_count

    model.foreman_notes = notes
    model.last_rated_at = utc_now_iso()

    registry.models[model_key] = model
    return save_model_registry(registry, registry_path)


def record_model_usage(
    model_key: str,
    registry_path: Path,
    *,
    task_id: str = "",
    duration_seconds: int = 0,
    files_changed: int = 0,
) -> bool:
    """Record model usage when a task completes (without generating comment).

    This increments the sample count and stores usage metrics.
    The actual comment is generated later when user requests evaluation.

    Args:
        model_key: The model key
        registry_path: Path to the models registry YAML file
        task_id: ID of the completed task
        duration_seconds: Task execution duration
        files_changed: Number of files modified

    Returns:
        True if successful, False otherwise
    """
    registry = load_model_registry(registry_path)
    model = registry.get_model(model_key)

    if model is None:
        runtime = model_key.split("-")[0] if "-" in model_key else "unknown"
        model = ModelCapability(runtime=runtime, model_id=model_key)

    # Increment usage count
    model.foreman_sample_count += 1

    # Store latest usage metrics in tags for later analysis
    # Format: "usage:task_id:duration:files"
    usage_tag = f"usage:{task_id}:{duration_seconds}:{files_changed}"
    if not model.tags:
        model.tags = []
    # Keep only last 10 usage records
    usage_tags = [t for t in model.tags if t.startswith("usage:")]
    other_tags = [t for t in model.tags if not t.startswith("usage:")]
    usage_tags.append(usage_tag)
    model.tags = other_tags + usage_tags[-10:]

    registry.models[model_key] = model
    return save_model_registry(registry, registry_path)


def request_model_review(
    model_key: str,
    registry_path: Path,
    group_id: str,
    send_message_fn,
) -> Optional[str]:
    """Request Foreman to generate a comment for a model.

    This sends a message to Foreman asking it to evaluate the model
    based on usage history. Foreman will analyze past task performance
    and generate a comment.

    Args:
        model_key: The model key to review
        registry_path: Path to the models registry YAML file
        group_id: The group ID where Foreman is running
        send_message_fn: Function to send message to Foreman

    Returns:
        A status message, or None if failed

    Raises:
        ValueError: If model not found or no usage history
    """
    registry = load_model_registry(registry_path)
    model = registry.get_model(model_key)

    if model is None:
        raise ValueError(f"Model not found: {model_key}")

    # Check if there's usage history
    if model.foreman_sample_count == 0:
        raise ValueError("No usage history. Run tasks with this model first.")

    # Build usage summary for Foreman
    usage_tags = [t for t in (model.tags or []) if t.startswith("usage:")]
    usage_summary = []
    for tag in usage_tags[-5:]:  # Last 5 tasks
        parts = tag.split(":")
        if len(parts) >= 4:
            _, task_id, duration, files = parts[:4]
            usage_summary.append(f"- Task {task_id}: {duration}s, {files} files")

    # Send evaluation request to Foreman
    prompt = f"""[Model Evaluation Request]

Please evaluate model: {model_key}

Usage statistics:
- Total tasks completed: {model.foreman_sample_count}

Recent task history:
{chr(10).join(usage_summary) if usage_summary else "No detailed history available"}

Current description (user-provided):
{model.description or "None"}

Please provide a brief, objective comment about this model's performance
based on the usage data. Focus on:
1. Speed/efficiency observations
2. Output quality patterns
3. Suitable use cases

Save your comment using the cccc_memory tool with key "model_comment:{model_key}".
"""

    try:
        # Find foreman actor and send message
        if send_message_fn:
            send_message_fn(group_id, "foreman", prompt)
            return "Evaluation request sent to Foreman"
        else:
            raise ValueError("Cannot send message to Foreman")
    except Exception as e:
        raise ValueError(f"Failed to send evaluation request: {e}")


def toggle_model_enabled(
    model_key: str,
    registry_path: Path,
    *,
    enabled: bool,
) -> bool:
    """Toggle whether a model is enabled/visible in the picker.

    Args:
        model_key: The model key to toggle
        registry_path: Path to the models registry YAML file
        enabled: Whether to enable or disable the model

    Returns:
        True if successful, False otherwise
    """
    registry = load_model_registry(registry_path)
    model = registry.get_model(model_key)

    if model is None:
        # Create new entry for predefined model
        runtime = model_key.split("-")[0] if "-" in model_key else "unknown"
        model = ModelCapability(runtime=runtime, model_id=model_key)

    model.enabled = enabled
    registry.models[model_key] = model
    return save_model_registry(registry, registry_path)


def add_custom_model(
    runtime: str,
    model_id: str,
    registry_path: Path,
    *,
    display_name: str = "",
    description: str = "",
    context_window: str = "128k",
    strengths: Optional[List[str]] = None,
) -> Optional[str]:
    """Add a custom model to the registry.

    Use this when the predefined model list doesn't include a model
    that the user wants to use.

    Args:
        runtime: The runtime (claude, gemini, codex)
        model_id: The model identifier (as used in CLI --model flag)
        registry_path: Path to the models registry YAML file
        display_name: Human-readable name (defaults to model_id)
        description: Optional description
        context_window: Context window size
        strengths: Optional list of strengths

    Returns:
        The model_key of the created model, or None if failed
    """
    model_key = _generate_model_key(runtime, model_id)

    registry = load_model_registry(registry_path)

    # Check if already exists
    if registry.get_model(model_key) is not None:
        # Update existing instead
        model = registry.get_model(model_key)
        if display_name:
            model.model_id = model_id  # Update model_id if provided
        if description:
            model.description = description
        if strengths:
            model.strengths = strengths
        model.context_window = context_window
        model.is_custom = True
        model.enabled = True
    else:
        # Create new
        model = ModelCapability(
            runtime=runtime,
            model_id=model_id,
            description=description,
            context_window=context_window,
            strengths=strengths or [],
            is_custom=True,
            enabled=True,
        )

    registry.models[model_key] = model

    if save_model_registry(registry, registry_path):
        return model_key
    return None


def delete_custom_model(
    model_key: str,
    registry_path: Path,
) -> bool:
    """Delete a model from the registry.

    Args:
        model_key: The model key to delete
        registry_path: Path to the models registry YAML file

    Returns:
        True if deleted, False if not found
    """
    registry = load_model_registry(registry_path)
    model = registry.get_model(model_key)

    if model is None:
        return False

    del registry.models[model_key]
    return save_model_registry(registry, registry_path)


def get_supported_runtimes() -> List[str]:
    """Get list of supported runtimes."""
    return list(SUPPORTED_RUNTIMES)


def detect_runtime_availability() -> Dict[str, bool]:
    """Detect which runtimes are available on the system.

    Returns:
        Dict mapping runtime name to availability status
    """
    availability = {}

    cli_commands = {
        "claude": ["claude", "--version"],
        "gemini": ["gemini", "--version"],
        "codex": ["codex", "--version"],
    }

    for runtime, cmd in cli_commands.items():
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=5,
            )
            availability[runtime] = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            availability[runtime] = False

    return availability
