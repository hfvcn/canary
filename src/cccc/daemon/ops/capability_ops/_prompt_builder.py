"""Prompt template assembly from capabilities.

This module provides functions to build actor system prompts by composing
prompt fragments from enabled capabilities based on the actor's role.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import yaml

from ....contracts.v1.capability import Capability

if TYPE_CHECKING:
    from ....contracts.v1 import Actor


def _load_capability_yaml(path: Path) -> Optional[Capability]:
    """Load a Capability from a YAML file.

    Args:
        path: Path to the capability YAML file

    Returns:
        Capability instance, or None if file doesn't exist or is invalid
    """
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None
        return Capability(**data)
    except Exception:
        return None


def _load_capabilities_from_dir(capabilities_dir: Path) -> List[Capability]:
    """Load all capabilities from a directory.

    Args:
        capabilities_dir: Path to directory containing .yaml capability files

    Returns:
        List of loaded Capability instances
    """
    capabilities = []
    if not capabilities_dir.exists():
        return capabilities

    for yaml_file in capabilities_dir.glob("*.yaml"):
        cap = _load_capability_yaml(yaml_file)
        if cap is not None and cap.enabled:
            capabilities.append(cap)

    return capabilities


def _resolve_actor_role(actor: "Actor", actors: List["Actor"]) -> str:
    """Determine actor's effective role based on position.

    First enabled actor in list is "foreman", rest are "peer".

    Args:
        actor: The actor to check
        actors: Full list of actors in the group

    Returns:
        "foreman" or "peer"
    """
    enabled_actors = [a for a in actors if a.enabled]
    if not enabled_actors:
        return "peer"

    # First enabled actor is the foreman
    if enabled_actors[0].id == actor.id:
        return "foreman"
    return "peer"


def build_actor_prompt(
    actor: "Actor",
    capabilities: List[Capability],
    *,
    actors: Optional[List["Actor"]] = None,
    base_prompt: str = "",
) -> str:
    """Build a complete system prompt for an actor by composing capability fragments.

    This function assembles a prompt from:
    1. Base prompt (if provided)
    2. Common fragments from all enabled capabilities
    3. Role-specific fragments based on actor's role

    Args:
        actor: The actor for which to build the prompt
        capabilities: List of capabilities to include
        actors: Optional list of all actors (for role determination)
        base_prompt: Optional base prompt to include first

    Returns:
        Complete assembled prompt string

    Example:
        >>> from cccc.contracts.v1 import Actor
        >>> actor = Actor(id="agent-1", title="Primary Agent")
        >>> caps = [
        ...     Capability(
        ...         id="task_mgmt",
        ...         prompt_fragments={
        ...             "common": "You have task tools.",
        ...             "foreman": "Assign tasks to peers.",
        ...         }
        ...     )
        ... ]
        >>> prompt = build_actor_prompt(actor, caps)
        >>> "task tools" in prompt
        True
    """
    parts: List[str] = []

    # Start with base prompt if provided
    if base_prompt and base_prompt.strip():
        parts.append(base_prompt.strip())

    # Determine actor role
    if actors:
        role = _resolve_actor_role(actor, actors)
    else:
        # Default to peer if we can't determine
        role = actor.role or "peer"

    # Collect prompt fragments from each capability
    for cap in capabilities:
        if not cap.enabled:
            continue

        fragment = cap.get_prompt_for_role(role)
        if fragment:
            parts.append(fragment)

    return "\n\n".join(parts)


def build_actor_prompt_from_ids(
    actor: "Actor",
    capability_ids: List[str],
    capabilities_dir: Path,
    *,
    actors: Optional[List["Actor"]] = None,
    base_prompt: str = "",
) -> str:
    """Build actor prompt from capability IDs by loading from directory.

    Args:
        actor: The actor for which to build the prompt
        capability_ids: List of capability IDs to load
        capabilities_dir: Directory containing capability YAML files
        actors: Optional list of all actors
        base_prompt: Optional base prompt

    Returns:
        Complete assembled prompt string
    """
    capabilities = []
    for cap_id in capability_ids:
        # Try loading from capabilities_dir/<cap_id>.yaml
        cap_path = capabilities_dir / f"{cap_id}.yaml"
        cap = _load_capability_yaml(cap_path)
        if cap is not None:
            capabilities.append(cap)

    return build_actor_prompt(actor, capabilities, actors=actors, base_prompt=base_prompt)


def get_capability_api_endpoints(capabilities: List[Capability]) -> List[Dict[str, Any]]:
    """Collect all API endpoints from a list of capabilities.

    Args:
        capabilities: List of capabilities to extract endpoints from

    Returns:
        List of endpoint dictionaries with capability_id added
    """
    endpoints = []
    for cap in capabilities:
        if not cap.enabled:
            continue
        for endpoint in cap.api_endpoints:
            ep_dict = endpoint.model_dump()
            ep_dict["capability_id"] = cap.id
            endpoints.append(ep_dict)
    return endpoints
