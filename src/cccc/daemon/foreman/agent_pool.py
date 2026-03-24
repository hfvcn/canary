"""Agent Pool management for Foreman.

Provides functionality to evaluate existing agents, find matches for tasks,
and decide whether to create new agents or reuse existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from ...contracts.v1.agent import Agent, ModelCapability, ModelRegistry
from ...contracts.v1.ralph_ipc import TaskRef
from ..ops.agent_ops import (
    create_agent,
    get_agent,
    list_agents,
    find_agents_by_affinity,
    load_model_registry,
    select_model_for_task,
    build_agent_prompt,
)


# Default capability sets for different task types
DEFAULT_WORKER_CAPABILITIES = ["task_execution", "code_modification", "memory_access"]
DEFAULT_REVIEWER_CAPABILITIES = ["code_review", "memory_access"]


@dataclass
class AgentEvaluation:
    """Result of evaluating an agent for a task.

    Attributes:
        agent: The evaluated agent
        score: Compatibility score (0-100)
        reasons: List of scoring reasons
        is_available: Whether agent is currently available
    """

    agent: Agent
    score: int
    reasons: List[str] = field(default_factory=list)
    is_available: bool = True

    def is_suitable(self, min_score: int = 50) -> bool:
        """Check if agent meets minimum suitability threshold."""
        return self.is_available and self.score >= min_score


@dataclass
class TaskAssignment:
    """Assignment of a task to an agent.

    Attributes:
        task: The task reference
        agent_id: ID of assigned agent
        agent_name: Display name of agent
        is_new_agent: Whether a new agent was created
        assignment_reason: Why this agent was chosen
        model_runtime: Agent CLI runtime (e.g., "claude", "gemini")
        model_id: Specific model identifier (e.g., "claude-sonnet-4")
    """

    task: TaskRef
    agent_id: str
    agent_name: str
    is_new_agent: bool = False
    assignment_reason: str = ""
    model_runtime: str = ""
    model_id: str = ""


class AgentPoolManager:
    """Manages the agent pool for Foreman.

    Responsibilities:
    - Evaluate existing agents for task compatibility
    - Decide between reusing or creating agents
    - Track agent availability and workload
    """

    def __init__(
        self,
        agents_dir: Path,
        models_registry_path: Path,
        capabilities_dir: Path,
    ):
        """Initialize the agent pool manager.

        Args:
            agents_dir: Directory containing agent YAML files
            models_registry_path: Path to models/registry.yaml
            capabilities_dir: Directory containing capability YAML files
        """
        self.agents_dir = agents_dir
        self.models_registry_path = models_registry_path
        self.capabilities_dir = capabilities_dir

        # Track active assignments (agent_id -> task_id)
        self._active_assignments: Dict[str, str] = {}

    def get_model_registry(self) -> ModelRegistry:
        """Load the current model registry."""
        return load_model_registry(self.models_registry_path)

    def list_available_agents(self) -> List[Agent]:
        """List all enabled agents that are currently available."""
        agents = list_agents(self.agents_dir, enabled_only=True)
        return [a for a in agents if a.id not in self._active_assignments]

    def evaluate_for_task(
        self,
        task: TaskRef,
        *,
        min_score: int = 50,
    ) -> List[AgentEvaluation]:
        """Evaluate all agents for a specific task.

        Args:
            task: The task to evaluate agents for
            min_score: Minimum score threshold for suitable agents

        Returns:
            List of evaluations, sorted by score descending
        """
        agents = list_agents(self.agents_dir, enabled_only=True)
        evaluations: List[AgentEvaluation] = []

        for agent in agents:
            score, reasons = self._score_agent_for_task(agent, task)
            is_available = agent.id not in self._active_assignments

            eval_result = AgentEvaluation(
                agent=agent,
                score=score,
                reasons=reasons,
                is_available=is_available,
            )
            evaluations.append(eval_result)

        # Sort by score descending, available agents first
        evaluations.sort(key=lambda e: (e.is_available, e.score), reverse=True)
        return evaluations

    def _score_agent_for_task(
        self, agent: Agent, task: TaskRef
    ) -> tuple[int, List[str]]:
        """Calculate compatibility score between an agent and a task.

        Scoring factors:
        - Task affinity match: +40 points
        - Role type match: +30 points
        - Has required capabilities: +20 points
        - Model suitability: +10 points

        Args:
            agent: Agent to evaluate
            task: Task to match against

        Returns:
            Tuple of (score, list of reasons)
        """
        score = 0
        reasons: List[str] = []

        # Task affinity match (0-40 points)
        if task.type in agent.task_affinity:
            score += 40
            reasons.append(f"Affinity match: {task.type}")
        elif agent.task_affinity:
            # Partial match for related types
            related = self._get_related_types(task.type)
            if any(t in agent.task_affinity for t in related):
                score += 20
                reasons.append(f"Related affinity: {related}")

        # Role type match (0-30 points)
        # For regular tasks, worker role is preferred
        if agent.role_type == "worker":
            score += 30
            reasons.append("Worker role")
        elif agent.role_type == "specialist":
            score += 25
            reasons.append("Specialist role")

        # Capabilities check (0-20 points)
        required_caps = self._get_required_capabilities(task.type)
        has_caps = all(c in agent.capabilities for c in required_caps)
        if has_caps:
            score += 20
            reasons.append("Has required capabilities")
        elif any(c in agent.capabilities for c in required_caps):
            score += 10
            reasons.append("Has some capabilities")

        # Model suitability (0-10 points)
        registry = self.get_model_registry()
        model = registry.get_model(agent.model_runtime)
        if model:
            if task.type in model.strengths:
                score += 10
                reasons.append(f"Model strength: {task.type}")

        return score, reasons

    def _get_related_types(self, task_type: str) -> List[str]:
        """Get related task types for partial matching."""
        related_map = {
            "frontend": ["ui", "web", "react", "vue"],
            "backend": ["api", "database", "server", "python"],
            "general": ["docs", "config", "build"],
        }
        return related_map.get(task_type, [])

    def _get_required_capabilities(self, task_type: str) -> List[str]:
        """Get required capabilities for a task type."""
        # All tasks need basic execution capability
        base = ["task_execution"]

        if task_type == "frontend":
            return base + ["code_modification"]
        elif task_type == "backend":
            return base + ["code_modification", "memory_access"]
        else:
            return base

    def find_best_agent(
        self,
        task: TaskRef,
        *,
        min_score: int = 50,
    ) -> Optional[Agent]:
        """Find the best available agent for a task.

        Args:
            task: Task to find agent for
            min_score: Minimum acceptable score

        Returns:
            Best matching agent, or None if no suitable agent found
        """
        evaluations = self.evaluate_for_task(task, min_score=min_score)

        for eval_result in evaluations:
            if eval_result.is_suitable(min_score):
                return eval_result.agent

        return None

    def create_agent_for_task(
        self,
        task: TaskRef,
        *,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> Optional[Agent]:
        """Create a new agent tailored for a specific task.

        Args:
            task: Task the agent will handle
            agent_id: Optional custom agent ID
            agent_name: Optional custom agent name

        Returns:
            Created agent, or None if creation failed
        """
        registry = self.get_model_registry()

        # Select best model for task type
        model_key = select_model_for_task(task.type, registry)
        if not model_key:
            # Fall back to first available model
            if registry.models:
                model_key = next(iter(registry.models))
            else:
                model_key = "claude"  # Ultimate fallback

        model = registry.get_model(model_key)
        model_runtime = model.runtime if model else "claude"
        model_id = model.model_id if model else ""

        # Generate agent ID and name
        if not agent_id:
            agent_id = self._generate_agent_id(model_runtime, task.type)
        if not agent_name:
            agent_name = f"{model_runtime.title()} {task.type.title()} Worker"

        # Determine capabilities based on task type
        capabilities = self._get_required_capabilities(task.type)
        if "code_modification" not in capabilities:
            capabilities.append("code_modification")

        # Create the agent
        agent = create_agent(
            agent_id=agent_id,
            name=agent_name,
            agents_dir=self.agents_dir,
            model_runtime=model_runtime,
            model_id=model_id,
            role_type="worker",
            capabilities=capabilities,
            task_affinity=[task.type],
            created_by="foreman",
            prompt=self._generate_worker_prompt(task.type),
        )

        return agent

    def _generate_agent_id(self, model_runtime: str, task_type: str) -> str:
        """Generate a unique agent ID for a task-scoped worker."""
        base_id = f"{model_runtime}-{task_type}-worker"
        candidate = base_id
        suffix = 1

        while (self.agents_dir / f"{candidate}.yaml").exists() or candidate in self._active_assignments:
            candidate = f"{base_id}-{suffix}"
            suffix += 1

        return candidate

    def _generate_worker_prompt(self, task_type: str) -> str:
        """Generate a system prompt for a worker based on task type."""
        prompts = {
            "frontend": """# Role: Frontend Developer

你是一个专注于前端开发的 Worker。你的职责是：
- 实现 UI 组件和页面
- 处理用户交互逻辑
- 优化前端性能
- 确保跨浏览器兼容性

遵循项目的代码规范和设计系统。""",
            "backend": """# Role: Backend Developer

你是一个专注于后端开发的 Worker。你的职责是：
- 实现 API 端点和业务逻辑
- 设计和优化数据库查询
- 处理认证和授权
- 确保代码安全性

遵循项目的架构模式和编码规范。""",
            "general": """# Role: General Developer

你是一个通用开发者 Worker。你的职责是：
- 执行分配的开发任务
- 编写文档和配置
- 修复 bug 和改进代码
- 协助其他专业任务

灵活适应各种开发需求。""",
        }
        return prompts.get(task_type, prompts["general"])

    def assign_agent(self, agent_id: str, task_id: str) -> bool:
        """Mark an agent as assigned to a task.

        Args:
            agent_id: Agent ID
            task_id: Task ID

        Returns:
            True if assignment successful
        """
        if agent_id in self._active_assignments:
            return False
        self._active_assignments[agent_id] = task_id
        return True

    def release_agent(self, agent_id: str) -> bool:
        """Release an agent from its current assignment.

        Args:
            agent_id: Agent ID

        Returns:
            True if release successful
        """
        if agent_id not in self._active_assignments:
            return False
        del self._active_assignments[agent_id]
        return True

    def get_active_assignments(self) -> Dict[str, str]:
        """Get all active agent assignments.

        Returns:
            Dict mapping agent_id to task_id
        """
        return dict(self._active_assignments)

    def create_or_reuse_agent(
        self,
        task: TaskRef,
        *,
        min_score: int = 50,
        prefer_reuse: bool = True,
    ) -> TaskAssignment:
        """Find or create an agent for a task.

        This is the main entry point for agent selection. It will:
        1. Try to find an existing suitable agent if prefer_reuse is True
        2. Create a new agent if no suitable agent found

        Args:
            task: Task to assign
            min_score: Minimum score for existing agent reuse
            prefer_reuse: Whether to prefer reusing existing agents

        Returns:
            TaskAssignment with the selected agent
        """
        assigned_agent: Optional[Agent] = None
        is_new = False
        reason = ""

        if prefer_reuse:
            # Try to find existing agent
            assigned_agent = self.find_best_agent(task, min_score=min_score)
            if assigned_agent:
                reason = f"Reused existing agent with affinity for {task.type}"

        if not assigned_agent:
            # Create new agent
            assigned_agent = self.create_agent_for_task(task)
            is_new = True
            reason = f"Created new agent for {task.type} task"

        if not assigned_agent:
            # Fallback: return a generic assignment
            return TaskAssignment(
                task=task,
                agent_id="",
                agent_name="",
                is_new_agent=False,
                assignment_reason="Failed to find or create agent",
            )

        # Mark agent as assigned. If this fails, the chosen agent is not actually usable
        # for this task, so surface a failed assignment instead of a misleading success.
        if not self.assign_agent(assigned_agent.id, task.id):
            return TaskAssignment(
                task=task,
                agent_id="",
                agent_name="",
                is_new_agent=False,
                assignment_reason=f"Agent {assigned_agent.id} is already assigned",
            )

        return TaskAssignment(
            task=task,
            agent_id=assigned_agent.id,
            agent_name=assigned_agent.name,
            is_new_agent=is_new,
            assignment_reason=reason,
            model_runtime=assigned_agent.model_runtime,
            model_id=assigned_agent.model_id,
        )
