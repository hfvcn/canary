"""Agent contract definitions for dynamic agent system.

An Agent represents a dynamically creatable AI agent with specific model,
role, and capabilities that can be created by Foreman and persisted for reuse.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ...util.time import utc_now_iso


# Agent role type determines responsibility level
AgentRoleType = Literal["worker", "reviewer", "specialist"]


class ModelCapability(BaseModel):
    """Describes a model's capabilities and limitations.

    Used in the model registry to help Foreman select appropriate
    models for different tasks based on their strengths and weaknesses.

    Attributes:
        runtime: Agent CLI runtime (e.g., "claude", "gemini", "codex")
        model_id: Specific model identifier (e.g., "claude-sonnet-4")
        strengths: List of task types this model excels at
        weaknesses: List of task types this model struggles with
        context_window: Maximum context window size (e.g., "200k", "1m")
        tags: Additional categorization tags

    Example:
        ModelCapability(
            runtime="claude",
            model_id="claude-sonnet-4",
            strengths=["complex_logic", "long_context", "code_refactoring"],
            weaknesses=["realtime_info"],
            context_window="200k"
        )
    """

    v: int = 1
    runtime: str  # Agent CLI runtime (e.g., "claude", "gemini", "codex")
    model_id: str = ""  # Specific model identifier
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    context_window: str = "128k"
    tags: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class Agent(BaseModel):
    """A dynamically created agent with specific model, role, and capabilities.

    Agents are created by Foreman based on task requirements and model
    capabilities. They can be saved and reused across sessions.

    Attributes:
        id: Unique identifier for the agent (e.g., "claude-backend-dev")
        name: Human-readable display name
        created_by: Who created this agent (usually "foreman")
        model_runtime: Agent CLI runtime (e.g., "claude", "gemini")
        model_id: Specific model identifier (e.g., "claude-sonnet-4")
        role_type: Agent's responsibility level (worker/reviewer/specialist)
        capabilities: List of capability IDs this agent has access to
        prompt: Custom system prompt for this agent
        task_affinity: List of task types this agent prefers (e.g., ["backend", "database"])
        enabled: Whether this agent is active
        created_at: ISO timestamp of creation
        updated_at: ISO timestamp of last update

    Example:
        Agent(
            id="claude-backend-dev",
            name="Claude Backend Developer",
            model_runtime="claude",
            model_id="claude-sonnet-4",
            role_type="worker",
            capabilities=["task_execution", "memory_access", "code_modification"],
            prompt="# Role: Backend Developer\\nYou are a backend developer...",
            task_affinity=["backend", "database", "api"]
        )
    """

    v: int = 1
    id: str
    name: str = ""
    created_by: str = "foreman"
    model_runtime: str = "claude"  # Agent CLI runtime
    model_id: str = ""  # Specific model identifier
    role_type: AgentRoleType = "worker"
    capabilities: List[str] = Field(default_factory=list)
    prompt: str = ""  # Custom system prompt
    task_affinity: List[str] = Field(default_factory=list)  # Preferred task types
    enabled: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="ignore")


class ModelRegistry(BaseModel):
    """Collection of available models with their capabilities.

    Used to track what models are available and their characteristics
    for intelligent agent creation.

    Attributes:
        kind: Document type identifier
        v: Schema version
        models: Dictionary mapping model key to ModelCapability
    """

    kind: Literal["cccc.model_registry"] = "cccc.model_registry"
    v: int = 1
    models: Dict[str, ModelCapability] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    def get_model(self, model_key: str) -> Optional[ModelCapability]:
        """Get a model capability by key."""
        return self.models.get(model_key)

    def find_by_strength(self, strength: str) -> List[str]:
        """Find model keys that have a specific strength."""
        return [
            key for key, model in self.models.items()
            if strength in model.strengths
        ]

    def find_by_runtime(self, runtime: str) -> List[str]:
        """Find model keys that use a specific runtime."""
        return [
            key for key, model in self.models.items()
            if model.runtime == runtime
        ]


class AgentSet(BaseModel):
    """A collection of agents with metadata.

    Used for exporting/importing agent configurations.
    """

    kind: Literal["cccc.agent_set"] = "cccc.agent_set"
    v: int = 1
    title: str = ""
    description: str = ""
    agents: List[Agent] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Find an agent by ID."""
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    def enabled_agents(self) -> List[Agent]:
        """Return list of enabled agents."""
        return [agent for agent in self.agents if agent.enabled]

    def find_by_affinity(self, task_type: str) -> List[Agent]:
        """Find agents that have affinity for a task type."""
        return [
            agent for agent in self.agents
            if agent.enabled and task_type in agent.task_affinity
        ]
