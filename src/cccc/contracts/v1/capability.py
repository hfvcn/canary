"""Capability contract definitions for prompt template management.

A Capability represents a reusable set of prompt fragments that can be
composed into actor system prompts based on their role and context.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# HTTP method for API endpoints
HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class APIEndpoint(BaseModel):
    """Describes an API endpoint that a capability exposes or requires.

    Used for documenting API surfaces and generating tool definitions.
    """

    path: str
    method: HTTPMethod = "GET"
    summary: str = ""
    description: str = ""
    request_schema: Optional[Dict] = None
    response_schema: Optional[Dict] = None
    tags: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class Capability(BaseModel):
    """A capability that provides prompt fragments and API endpoints.

    Capabilities are the primary unit for managing reusable prompt templates
    and documenting API surfaces that agents can use.

    Attributes:
        id: Unique identifier for the capability (e.g., "task_management")
        title: Human-readable name
        description: Detailed description of what this capability provides
        version: Semantic version string (e.g., "1.0.0")
        prompt_fragments: Role-keyed prompt template snippets
            - Keys: "foreman", "peer", "common", or custom role names
            - Values: Prompt text to inject into system prompt
            - "common" fragments are included for all roles
        api_endpoints: List of API endpoints this capability exposes
        tags: Categorization tags for search/filtering
        requires: List of capability IDs this capability depends on
        enabled: Whether this capability is active

    Example prompt_fragments:
        {
            "common": "You have access to task management tools.",
            "foreman": "As the foreman, you can assign tasks to peers.",
            "peer": "Report task progress to the foreman."
        }
    """

    v: int = 1
    id: str
    title: str = ""
    description: str = ""
    version: str = "1.0.0"
    prompt_fragments: Dict[str, str] = Field(default_factory=dict)
    api_endpoints: List[APIEndpoint] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    enabled: bool = True

    model_config = ConfigDict(extra="ignore")

    def get_prompt_for_role(self, role: str) -> str:
        """Get combined prompt fragments for a given role.

        Combines "common" fragment (if any) with role-specific fragment.

        Args:
            role: Actor role (e.g., "foreman", "peer")

        Returns:
            Combined prompt text, or empty string if no fragments match
        """
        parts = []

        # Include common fragment first
        common = self.prompt_fragments.get("common", "").strip()
        if common:
            parts.append(common)

        # Include role-specific fragment
        role_specific = self.prompt_fragments.get(role, "").strip()
        if role_specific:
            parts.append(role_specific)

        return "\n\n".join(parts)


class CapabilitySet(BaseModel):
    """A collection of capabilities with metadata.

    Used for exporting/importing capability configurations.
    """

    kind: Literal["cccc.capability_set"] = "cccc.capability_set"
    v: int = 1
    title: str = ""
    description: str = ""
    capabilities: List[Capability] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        """Find a capability by ID."""
        for cap in self.capabilities:
            if cap.id == capability_id:
                return cap
        return None

    def enabled_capabilities(self) -> List[Capability]:
        """Return list of enabled capabilities."""
        return [cap for cap in self.capabilities if cap.enabled]
