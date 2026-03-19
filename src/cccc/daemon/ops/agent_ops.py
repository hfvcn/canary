"""Agent registry and lifecycle operation handlers.

This module provides functions to manage dynamic agents:
- Load and manage model capability registry
- Create, load, save, delete agents
- Build agent prompts by composing capability fragments
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ...contracts.v1.agent import Agent, AgentSet, ModelCapability, ModelRegistry
from ...contracts.v1.capability import Capability
from ...util.time import utc_now_iso

from .capability_ops import (
    build_actor_prompt,
    _load_capability_yaml,
    _load_capabilities_from_dir,
)


# Default paths relative to project root
DEFAULT_MODELS_REGISTRY_PATH = ".cccc/models/registry.yaml"
DEFAULT_AGENTS_DIR = ".cccc/agents"
DEFAULT_CAPABILITIES_DIR = ".cccc/capabilities"


def load_model_registry(registry_path: Path) -> ModelRegistry:
    """Load the model capability registry from YAML file.

    Args:
        registry_path: Path to the registry.yaml file

    Returns:
        ModelRegistry instance (empty if file doesn't exist)

    Example:
        >>> registry = load_model_registry(Path(".cccc/models/registry.yaml"))
        >>> claude_caps = registry.get_model("claude-sonnet")
        >>> claude_caps.strengths
        ['complex_logic', 'long_context', 'code_refactoring']
    """
    if not registry_path.exists():
        return ModelRegistry()

    try:
        content = registry_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return ModelRegistry()

        # Parse models section
        models_data = data.get("models", {})
        models = {}
        for key, model_data in models_data.items():
            if isinstance(model_data, dict):
                models[key] = ModelCapability(**model_data)

        return ModelRegistry(models=models)
    except Exception:
        return ModelRegistry()


def save_model_registry(registry: ModelRegistry, registry_path: Path) -> bool:
    """Save the model registry to YAML file.

    Args:
        registry: ModelRegistry to save
        registry_path: Path to write the registry.yaml file

    Returns:
        True if successful, False otherwise
    """
    try:
        registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to YAML-friendly format
        data = {
            "models": {
                key: model.model_dump(exclude_defaults=True)
                for key, model in registry.models.items()
            }
        }

        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        registry_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _load_agent_yaml(path: Path) -> Optional[Agent]:
    """Load an Agent from a YAML file.

    Args:
        path: Path to the agent YAML file

    Returns:
        Agent instance, or None if file doesn't exist or is invalid
    """
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None

        # Handle nested model structure from YAML
        if "model" in data and isinstance(data["model"], dict):
            model_data = data.pop("model")
            data["model_runtime"] = model_data.get("runtime", "claude")
            data["model_id"] = model_data.get("model_id", "")

        return Agent(**data)
    except Exception:
        return None


def _save_agent_yaml(agent: Agent, path: Path) -> bool:
    """Save an Agent to a YAML file.

    Args:
        agent: Agent to save
        path: Path to write the YAML file

    Returns:
        True if successful, False otherwise
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to YAML-friendly format with nested model structure
        data = agent.model_dump(exclude_defaults=True)

        # Restructure model fields for cleaner YAML
        if "model_runtime" in data or "model_id" in data:
            data["model"] = {
                "runtime": data.pop("model_runtime", "claude"),
                "model_id": data.pop("model_id", ""),
            }

        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def create_agent(
    agent_id: str,
    name: str,
    agents_dir: Path,
    *,
    model_runtime: str = "claude",
    model_id: str = "",
    role_type: str = "worker",
    capabilities: Optional[List[str]] = None,
    prompt: str = "",
    task_affinity: Optional[List[str]] = None,
    created_by: str = "foreman",
) -> Optional[Agent]:
    """Create a new agent and save to disk.

    Args:
        agent_id: Unique identifier for the agent
        name: Human-readable display name
        agents_dir: Directory to store agent YAML files
        model_runtime: Agent CLI runtime (e.g., "claude", "gemini")
        model_id: Specific model identifier
        role_type: Agent's responsibility level (worker/reviewer/specialist)
        capabilities: List of capability IDs
        prompt: Custom system prompt
        task_affinity: List of preferred task types
        created_by: Creator identifier (usually "foreman")

    Returns:
        Created Agent instance, or None if save failed

    Example:
        >>> agent = create_agent(
        ...     "claude-backend-dev",
        ...     "Claude Backend Developer",
        ...     Path(".cccc/agents"),
        ...     model_runtime="claude",
        ...     model_id="claude-sonnet-4",
        ...     role_type="worker",
        ...     capabilities=["task_execution", "code_modification"],
        ...     task_affinity=["backend", "database"]
        ... )
    """
    now = utc_now_iso()
    agent = Agent(
        id=agent_id,
        name=name,
        created_by=created_by,
        model_runtime=model_runtime,
        model_id=model_id,
        role_type=role_type,  # type: ignore
        capabilities=capabilities or [],
        prompt=prompt,
        task_affinity=task_affinity or [],
        enabled=True,
        created_at=now,
        updated_at=now,
    )

    agent_path = agents_dir / f"{agent_id}.yaml"
    if _save_agent_yaml(agent, agent_path):
        return agent
    return None


def get_agent(agent_id: str, agents_dir: Path) -> Optional[Agent]:
    """Get an agent by ID.

    Args:
        agent_id: Agent identifier
        agents_dir: Directory containing agent YAML files

    Returns:
        Agent instance, or None if not found
    """
    agent_path = agents_dir / f"{agent_id}.yaml"
    return _load_agent_yaml(agent_path)


def list_agents(agents_dir: Path, *, enabled_only: bool = False) -> List[Agent]:
    """List all agents in the agents directory.

    Args:
        agents_dir: Directory containing agent YAML files
        enabled_only: If True, only return enabled agents

    Returns:
        List of Agent instances
    """
    agents = []
    if not agents_dir.exists():
        return agents

    for yaml_file in agents_dir.glob("*.yaml"):
        agent = _load_agent_yaml(yaml_file)
        if agent is not None:
            if enabled_only and not agent.enabled:
                continue
            agents.append(agent)

    # Sort by name for consistent ordering
    return sorted(agents, key=lambda a: a.name or a.id)


def update_agent(
    agent_id: str,
    agents_dir: Path,
    **updates: Any,
) -> Optional[Agent]:
    """Update an existing agent.

    Args:
        agent_id: Agent identifier
        agents_dir: Directory containing agent YAML files
        **updates: Fields to update

    Returns:
        Updated Agent instance, or None if not found
    """
    agent = get_agent(agent_id, agents_dir)
    if agent is None:
        return None

    # Apply updates
    agent_data = agent.model_dump()
    for key, value in updates.items():
        if hasattr(agent, key):
            agent_data[key] = value

    agent_data["updated_at"] = utc_now_iso()

    updated_agent = Agent(**agent_data)
    agent_path = agents_dir / f"{agent_id}.yaml"
    if _save_agent_yaml(updated_agent, agent_path):
        return updated_agent
    return None


def delete_agent(agent_id: str, agents_dir: Path) -> bool:
    """Delete an agent by ID.

    Args:
        agent_id: Agent identifier
        agents_dir: Directory containing agent YAML files

    Returns:
        True if deleted, False if not found
    """
    agent_path = agents_dir / f"{agent_id}.yaml"
    if not agent_path.exists():
        return False

    try:
        agent_path.unlink()
        return True
    except Exception:
        return False


def find_agents_by_affinity(
    task_type: str,
    agents_dir: Path,
    *,
    enabled_only: bool = True,
) -> List[Agent]:
    """Find agents that have affinity for a specific task type.

    Args:
        task_type: Task type to search for (e.g., "backend", "frontend")
        agents_dir: Directory containing agent YAML files
        enabled_only: If True, only return enabled agents

    Returns:
        List of matching agents, sorted by affinity match quality
    """
    agents = list_agents(agents_dir, enabled_only=enabled_only)
    matching = [a for a in agents if task_type in a.task_affinity]
    return matching


def find_agents_by_capability(
    capability_id: str,
    agents_dir: Path,
    *,
    enabled_only: bool = True,
) -> List[Agent]:
    """Find agents that have a specific capability.

    Args:
        capability_id: Capability identifier
        agents_dir: Directory containing agent YAML files
        enabled_only: If True, only return enabled agents

    Returns:
        List of matching agents
    """
    agents = list_agents(agents_dir, enabled_only=enabled_only)
    return [a for a in agents if capability_id in a.capabilities]


def build_agent_prompt(
    agent: Agent,
    capabilities_dir: Path,
    *,
    base_prompt: str = "",
    include_agent_prompt: bool = True,
) -> str:
    """Build a complete system prompt for an agent.

    This function assembles a prompt from:
    1. Base prompt (if provided)
    2. Agent's custom prompt (if include_agent_prompt is True)
    3. Capability fragments based on agent's role_type

    Uses the prompt builder from capability_ops to compose capability fragments.

    Args:
        agent: The agent for which to build the prompt
        capabilities_dir: Directory containing capability YAML files
        base_prompt: Optional base prompt to include first
        include_agent_prompt: Whether to include agent's custom prompt

    Returns:
        Complete assembled prompt string

    Example:
        >>> agent = Agent(
        ...     id="claude-backend-dev",
        ...     role_type="worker",
        ...     capabilities=["task_execution", "memory_access"],
        ...     prompt="# Role: Backend Developer"
        ... )
        >>> prompt = build_agent_prompt(agent, Path(".cccc/capabilities"))
    """
    parts: List[str] = []

    # Start with base prompt if provided
    if base_prompt and base_prompt.strip():
        parts.append(base_prompt.strip())

    # Include agent's custom prompt
    if include_agent_prompt and agent.prompt and agent.prompt.strip():
        parts.append(agent.prompt.strip())

    # Load capabilities for this agent
    capabilities: List[Capability] = []
    for cap_id in agent.capabilities:
        cap_path = capabilities_dir / f"{cap_id}.yaml"
        cap = _load_capability_yaml(cap_path)
        if cap is not None:
            capabilities.append(cap)

    # Map agent role_type to actor role for capability prompt assembly
    # worker/specialist -> peer, reviewer -> peer (read-only reviewer)
    # For prompt purposes, we use "peer" as the role for workers
    role_mapping = {
        "worker": "peer",
        "reviewer": "peer",
        "specialist": "peer",
    }
    effective_role = role_mapping.get(agent.role_type, "peer")

    # Collect prompt fragments from each capability
    for cap in capabilities:
        if not cap.enabled:
            continue

        fragment = cap.get_prompt_for_role(effective_role)
        if fragment:
            parts.append(fragment)

    return "\n\n".join(parts)


def select_model_for_task(
    task_type: str,
    registry: ModelRegistry,
    *,
    required_strengths: Optional[List[str]] = None,
    avoid_weaknesses: Optional[List[str]] = None,
) -> Optional[str]:
    """Select the best model for a given task type.

    Args:
        task_type: Type of task (e.g., "backend", "frontend", "code_review")
        registry: Model capability registry
        required_strengths: Strengths the model must have
        avoid_weaknesses: Weaknesses to avoid

    Returns:
        Model key, or None if no suitable model found
    """
    required_strengths = required_strengths or []
    avoid_weaknesses = avoid_weaknesses or []

    candidates: List[tuple[str, int]] = []

    for key, model in registry.models.items():
        # Check required strengths
        has_required = all(s in model.strengths for s in required_strengths)
        if not has_required:
            continue

        # Check avoided weaknesses
        has_avoided = any(w in model.weaknesses for w in avoid_weaknesses)
        if has_avoided:
            continue

        # Score by number of matching strengths
        score = len([s for s in model.strengths if task_type in s.lower()])
        candidates.append((key, score))

    if not candidates:
        return None

    # Return highest scoring model
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]
