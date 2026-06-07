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
        description: User-provided description of the model
        best_for: Best use cases for this model
        foreman_rating: Foreman's rating (1-5) based on workflow performance
        foreman_notes: Notes from Foreman about the model's performance
        foreman_sample_count: Number of workflows the rating is based on
        last_rated_at: Timestamp of last Foreman rating
        cost_tier: Relative model cost tier for scoring

    Example:
        ModelCapability(
            runtime="claude",
            model_id="claude-sonnet-4",
            strengths=["complex_logic", "long_context", "code_refactoring"],
            weaknesses=["realtime_info"],
            context_window="200k",
            description="擅长复杂后端逻辑和代码重构",
            best_for="后端开发、架构设计"
        )
    """

    v: int = 1
    runtime: str  # Agent CLI runtime (e.g., "claude", "gemini", "codex")
    model_id: str = ""  # Specific model identifier
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    context_window: str = "128k"
    tags: List[str] = Field(default_factory=list)

    # User-editable description fields
    description: str = ""  # User-provided model description
    best_for: str = ""  # Best use cases

    # Visibility control
    enabled: bool = True  # Whether to show in model picker (for hiding unused models)
    is_custom: bool = False  # Whether this is a user-added custom model
    cost_tier: Optional[str] = None  # "budget" | "standard" | "premium"

    # Foreman rating fields (only populated when user requests evaluation)
    foreman_rating: Optional[float] = None  # Rating from 1-5
    foreman_notes: str = ""  # Rating explanation
    foreman_sample_count: int = 0  # Number of workflows rated
    last_rated_at: Optional[str] = None  # Last rating timestamp

    model_config = ConfigDict(extra="ignore", protected_namespaces=())


class Agent(BaseModel):
    """A dynamically created agent with specific model, role, and capabilities.

    Agents are created by Foreman based on task requirements and model
    capabilities. They can be saved and reused across sessions.

    Attributes:
        id: Unique identifier for the agent (e.g., "claude-backend-dev")
        name: Human-readable display name
        created_by: Who created this agent (usually "foreman")
        model_runtime: Agent CLI runtime (e.g., "codex", "claude", "gemini")
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
    model_runtime: str = "codex"  # Agent CLI runtime
    model_id: str = ""  # Specific model identifier
    role_type: AgentRoleType = "worker"
    capabilities: List[str] = Field(default_factory=list)
    prompt: str = ""  # Custom system prompt
    task_affinity: List[str] = Field(default_factory=list)  # Preferred task types
    enabled: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(extra="ignore", protected_namespaces=())


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
