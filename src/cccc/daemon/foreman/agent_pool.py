"""Agent Pool management for Foreman.

Provides functionality to evaluate existing agents, find matches for tasks,
and decide whether to create new agents or reuse existing ones.
"""

from __future__ import annotations

import logging
import math
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml

from ...contracts.v1.agent import Agent, ModelCapability, ModelRegistry
from ...contracts.v1.agent_lease import (
    AgentAcquireRequest,
    AgentLease,
    AssignmentPolicy,
)
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
from ..ops.model_selection import match_model_for_task


# Default capability sets for different task types
DEFAULT_WORKER_CAPABILITIES = ["task_execution", "code_modification", "memory_access"]
DEFAULT_REVIEWER_CAPABILITIES = ["code_review", "memory_access"]
LARGE_CONTEXT_WINDOW = 200_000
MULTI_FILE_TASK_PATH_COUNT = 5
FOREMAN_RATING_MULTIPLIER = 2
COMPLEX_TASK_TYPES = {"architecture_design", "security_review", "complex_logic"}
COST_TIER_BONUS = {"budget": 8, "standard": 4, "premium": 0}
DEFAULT_COST_TIER_BONUS = 4
SIMPLE_TASK_CAPABILITY_LIMIT = 2
PATH_DOMAIN_AFFINITY_BONUS = 25
PATH_DOMAIN_RELATED_BONUS = 10
FRONTEND_PATH_SIGNALS = (
    "frontend/",
    "components/",
    "pages/",
    "styles/",
    ".tsx",
    ".jsx",
    ".css",
    ".vue",
)
BACKEND_PATH_SIGNALS = (
    "backend/",
    "api/",
    "server/",
    "models/",
    "database/",
    ".go",
    ".rs",
)
TESTING_PATH_SIGNALS = ("test", "spec")
DEFAULT_AGENT_PROFILE_ROLE = "executor"
REVIEWER_AGENT_PROFILE_ROLE = "reviewer"
SECURITY_REVIEWER_AGENT_PROFILE_ROLE = "security-reviewer"
SECURITY_REVIEW_PEER_RUNTIMES = frozenset({"claude"})
logger = logging.getLogger(__name__)


def _parse_context_window(value: str | int) -> int:
    """Parse a model context window string into a token count."""
    normalized = str(value).strip().lower()
    if normalized.endswith("k"):
        return int(float(normalized[:-1]) * 1_000)
    if normalized.endswith("m"):
        return int(float(normalized[:-1]) * 1_000_000)
    return int(normalized)


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
        model_key: Registry model key (e.g., "codex-gpt-5.4")
    """

    task: TaskRef
    agent_id: str
    agent_name: str
    is_new_agent: bool = False
    assignment_reason: str = ""
    model_runtime: str = ""
    model_id: str = ""
    model_key: str = ""


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
        group_loader: Optional[callable] = None,
    ):
        """Initialize the agent pool manager.

        Args:
            agents_dir: Directory containing agent YAML files
            models_registry_path: Path to models/registry.yaml
            capabilities_dir: Directory containing capability YAML files
            group_loader: Optional callback returning list of enabled peer actor dicts
        """
        self.agents_dir = agents_dir
        self.models_registry_path = models_registry_path
        self.capabilities_dir = capabilities_dir
        self._group_loader = group_loader

        # Track active assignments (agent_id -> task_id)
        self._active_assignments: Dict[str, str] = {}
        self._assignment_lock = threading.Lock()
        self._active_leases: dict[str, AgentLease] = {}  # lease_id -> lease
        self._task_leases: dict[str, AgentLease] = {}  # task_id -> lease
        self._last_assignment_warning: str = ""

    def get_model_registry(self) -> ModelRegistry:
        """Load the current model registry."""
        return load_model_registry(self.models_registry_path)

    def list_available_agents(self) -> List[Agent]:
        """List all enabled agents that are currently available."""
        agents = list_agents(self.agents_dir, enabled_only=True)
        return [a for a in agents if a.id not in self._active_assignments]

    def acquire(self, request: AgentAcquireRequest) -> AgentLease:
        """Acquire an agent lease for task execution."""
        policy = self._normalize_assignment_policy(request.assignment_policy)
        task_id = getattr(request.task, "id", "")

        if policy.mode == "explicit":
            agent, reason, is_new_actor = self._acquire_explicit_agent(policy, task_id)
        elif policy.mode == "role_pool":
            agent, reason, is_new_actor = self._acquire_role_pool_agent(
                request,
                policy,
                task_id,
            )
        else:
            agent, reason, is_new_actor = self._acquire_auto_agent(request)

        lease = self._build_lease(request, agent, reason, is_new_actor)
        self._active_leases[lease.lease_id] = lease
        self._task_leases[lease.task_id] = lease
        return lease

    def release(self, lease: AgentLease, outcome: str) -> None:
        """Release a lease after task completion."""
        self._active_leases.pop(lease.lease_id, None)
        self._task_leases.pop(lease.task_id, None)
        self.release_agent(lease.agent_id)
        logger.info("Released lease %s with outcome=%s", lease.lease_id, outcome)

    def mark_failed(self, lease: AgentLease, reason: str) -> None:
        """Release a lease due to failure."""
        self._active_leases.pop(lease.lease_id, None)
        self._task_leases.pop(lease.task_id, None)
        self.release_agent(lease.agent_id)
        logger.info("Released failed lease %s: %s", lease.lease_id, reason)

    def get_lease_by_task(self, task_id: str) -> AgentLease | None:
        return self._task_leases.get(task_id)

    def _normalize_assignment_policy(self, policy: object) -> AssignmentPolicy:
        if isinstance(policy, AssignmentPolicy):
            return policy
        return AssignmentPolicy(mode="auto")

    def _acquire_explicit_agent(
        self,
        policy: AssignmentPolicy,
        task_id: str,
    ) -> tuple[Agent, str, bool]:
        agent = get_agent(policy.explicit_actor_id, self.agents_dir)
        if agent is None:
            raise ValueError(f"Explicit agent not found: {policy.explicit_actor_id}")
        if not agent.enabled:
            raise ValueError(f"Agent {policy.explicit_actor_id} is disabled")
        if agent.id in self._active_assignments:
            raise ValueError(f"Agent {policy.explicit_actor_id} is busy")
        if not self.assign_agent(agent.id, task_id):
            raise ValueError(f"Agent {policy.explicit_actor_id} is busy")
        return agent, f"Explicit assignment: {policy.explicit_actor_id}", False

    def _acquire_role_pool_agent(
        self,
        request: AgentAcquireRequest,
        policy: AssignmentPolicy,
        task_id: str,
    ) -> tuple[Agent, str, bool]:
        for evaluation in self.evaluate_for_task(request.task):
            agent = evaluation.agent
            if agent.role_type != policy.required_role:
                continue
            if not evaluation.is_suitable():
                continue
            if not self._has_required_capabilities(agent, policy):
                continue
            if not self.assign_agent(agent.id, task_id):
                raise ValueError(f"Agent {agent.id} is busy")
            return agent, f"Role pool selection for {policy.required_role}", False
        raise ValueError("No suitable agent in role pool")

    def _acquire_auto_agent(
        self,
        request: AgentAcquireRequest,
    ) -> tuple[Agent, str, bool]:
        result = self.create_or_reuse_agent(request.task)
        if not result.agent_id:
            raise ValueError(f"Failed to acquire agent: {result.assignment_reason}")

        agent = get_agent(result.agent_id, self.agents_dir)
        if agent is not None:
            return agent, result.assignment_reason, result.is_new_agent

        agent = Agent(
            id=result.agent_id,
            name=result.agent_name,
            model_runtime=result.model_runtime or "codex",
            model_id=result.model_id,
            role_type="worker",
        )
        return agent, result.assignment_reason, result.is_new_agent

    def _has_required_capabilities(
        self,
        agent: Agent,
        policy: AssignmentPolicy,
    ) -> bool:
        return all(
            capability in agent.capabilities
            for capability in policy.required_capabilities
        )

    def _build_lease(
        self,
        request: AgentAcquireRequest,
        agent: Agent,
        assignment_reason: str,
        is_new_actor: bool,
    ) -> AgentLease:
        task_id = getattr(request.task, "id", "")
        return AgentLease(
            lease_id=str(uuid.uuid4()),
            agent_id=agent.id,
            actor_id=agent.id,
            model_runtime=agent.model_runtime,
            model_id=agent.model_id,
            model_key=agent.model_id,
            is_new_actor=is_new_actor,
            assignment_reason=assignment_reason,
            task_id=task_id,
            node_id=request.node_id,
            attempt_id=request.attempt_id,
        )

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
        registry = self.get_model_registry()

        for agent in agents:
            _, model = self._resolve_registry_model(registry, agent.model_id)
            # FC-2 / T2-d: reuse-path candidates must honor the registry enabled gate.
            # Unknown model bindings are still allowed; only explicit disabled models skip reuse.
            if model and not model.enabled:
                continue
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
        - Model weakness penalty: -15 points
        - Large context window bonus: +5 points
        - Model best_for match: +10 points
        - Model description fallback: +1 point
        - Foreman rating bonus: floor(rating * 2) points
        - Cost tier bonus for simple non-complex tasks: +0 to +8 points

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
        if agent.role_type in ("worker", "peer"):
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
        _, model = self._resolve_registry_model(registry, agent.model_id)
        if model:
            model_score, model_reasons = self._score_model_for_task(model, task)
            score += model_score
            reasons.extend(model_reasons)

        inferred_domain = self._infer_domain_from_paths(task.claimed_paths or [])
        if inferred_domain != "general":
            if inferred_domain in agent.task_affinity:
                score += PATH_DOMAIN_AFFINITY_BONUS
                reasons.append(f"Path domain affinity: {inferred_domain}")
            else:
                related = self._get_related_types(inferred_domain)
                if any(t in agent.task_affinity for t in related):
                    score += PATH_DOMAIN_RELATED_BONUS
                    reasons.append(f"Path domain related affinity: {inferred_domain}")

        return score, reasons

    def _infer_domain_from_paths(self, paths: List[str]) -> str:
        """Infer a dominant task domain from claimed paths."""
        if not paths:
            return "general"

        counts = {"frontend": 0, "backend": 0, "testing": 0}
        for path in paths:
            normalized = path.lower()
            if any(signal in normalized for signal in FRONTEND_PATH_SIGNALS):
                counts["frontend"] += 1
            if any(signal in normalized for signal in BACKEND_PATH_SIGNALS):
                counts["backend"] += 1
            if any(signal in normalized for signal in TESTING_PATH_SIGNALS):
                counts["testing"] += 1

        if counts["frontend"] and counts["backend"]:
            return "general"

        dominant_domain = max(counts, key=counts.get)
        dominant_score = counts[dominant_domain]
        if dominant_score == 0:
            return "general"
        if list(counts.values()).count(dominant_score) > 1:
            return "general"
        return dominant_domain

    def _score_model_for_task(
        self,
        model: ModelCapability,
        task: TaskRef,
    ) -> tuple[int, List[str]]:
        """Score model-specific fitness for a task."""
        score = 0
        reasons: List[str] = []

        match = match_model_for_task(model, task.type)
        if match and match.source == "strengths":
            score += 10
            reasons.append(f"Model strength: {match.detail}")
        elif match and match.source == "best_for":
            score += 10
            reasons.append(f"Model best_for match: {match.detail}")
        elif match and match.source == "description":
            score += 1
            reasons.append(f"Model description match: {match.detail}")

        if task.type in model.weaknesses:
            score -= 15
            reasons.append(f"Model weakness: {task.type}")
        if (
            _parse_context_window(model.context_window) >= LARGE_CONTEXT_WINDOW
            and len(task.claimed_paths) >= MULTI_FILE_TASK_PATH_COUNT
        ):
            score += 5
            reasons.append("Large context window for multi-file task")
        if model.foreman_rating is not None:
            rating_points = math.floor(model.foreman_rating * FOREMAN_RATING_MULTIPLIER)
            score += rating_points
            reasons.append(
                f"Foreman rating: {model.foreman_rating:g}/5 (+{rating_points})"
            )
        if model.cost_tier and task.type not in COMPLEX_TASK_TYPES:
            required_caps = self._get_required_capabilities(task.type)
            if len(required_caps) <= SIMPLE_TASK_CAPABILITY_LIMIT:
                cost_bonus = COST_TIER_BONUS.get(
                    model.cost_tier, DEFAULT_COST_TIER_BONUS
                )
                if cost_bonus > 0:
                    score += cost_bonus
                    reasons.append(
                        f"Cost tier bonus: {model.cost_tier} (+{cost_bonus})"
                    )

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

    def _find_group_peer_agent(
        self,
        task: TaskRef,
        busy_agent_ids: Optional[set] = None,
    ) -> Optional[Agent]:
        """Find a matching group peer actor for a task.

        Checks group actors (created via cccc actor add) that are not in agents_dir YAMLs.
        Uses runtime matching and availability from engine/shadow state.
        """
        if not self._group_loader:
            return None

        busy = busy_agent_ids or set()
        try:
            peers = self._group_loader()
        except Exception:
            logger.debug("Failed to load group peers", exc_info=True)
            return None

        if not peers:
            return None

        best_agent: Optional[Agent] = None
        best_score = 0

        for peer in peers:
            actor_id = str(peer.get("id") or "").strip()
            if not actor_id or actor_id in busy or actor_id in self._active_assignments:
                continue

            peer_runtime = str(peer.get("runtime") or "").strip()
            if task.type == "security_review" and peer_runtime not in SECURITY_REVIEW_PEER_RUNTIMES:
                continue

            score = 0
            reasons: List[str] = []
            if task.type == "security_review":
                score += 50
                reasons.append(f"Runtime {peer_runtime} supports security review")

            inferred_domain = self._infer_domain_from_paths(task.claimed_paths or [])
            if inferred_domain != "general" and peer_runtime:
                runtime_domain_map = {
                    "codex": ["backend", "general"],
                    "claude": ["frontend", "backend", "general"],
                }
                domains = runtime_domain_map.get(peer_runtime, ["general"])
                if inferred_domain in domains:
                    score += 40
                    reasons.append(f"Runtime {peer_runtime} matches domain {inferred_domain}")

            if peer_runtime:
                score += 30
                reasons.append(f"Peer has runtime: {peer_runtime}")

            if score > best_score:
                best_score = score
                best_agent = Agent(
                    id=actor_id,
                    name=str(peer.get("title") or actor_id),
                    model_runtime=peer_runtime,
                    model_id=str(peer.get("model_id") or ""),
                    role_type="worker",
                )

        if best_agent and best_score >= 30:
            logger.info("Reusing group peer actor %s (score=%d)", best_agent.id, best_score)
            return best_agent

        return None

    def create_agent_for_task(
        self,
        task: TaskRef,
        *,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        suggested_model_key: Optional[str] = None,
    ) -> Optional[Agent]:
        """Create a new agent tailored for a specific task.

        Args:
            task: Task the agent will handle
            agent_id: Optional custom agent ID
            agent_name: Optional custom agent name
            suggested_model_key: Model key suggested by ralph (preferred if enabled)

        Returns:
            Created agent, or None if creation failed
        """
        self._last_assignment_warning = ""
        model_key, model = self.resolve_model_for_task(
            task,
            suggested_model_key=suggested_model_key,
        )

        if not model_key:
            self._last_assignment_warning = f"Warning: no registry model available for task type '{task.type}'"
            logger.warning(self._last_assignment_warning)
            return None

        if model is None:
            self._last_assignment_warning = f"Warning: registry key '{model_key}' not found for task type '{task.type}'"
            logger.warning(self._last_assignment_warning)
            return None

        model_runtime = model.runtime or "codex"
        model_id = model.model_id or model_key
        role_type = "worker"
        profile_role = self._profile_role_for_agent(role_type)

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
            role_type=role_type,
            capabilities=capabilities,
            task_affinity=[task.type],
            created_by="foreman",
            prompt=self._load_saved_worker_prompt(profile_role, model_runtime)
            or self._generate_worker_prompt(task.type),
        )

        return agent

    def resolve_model_for_task(
        self,
        task: TaskRef,
        *,
        suggested_model_key: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[ModelCapability]]:
        registry = self.get_model_registry()
        model_key: Optional[str] = None

        if suggested_model_key:
            suggested_model = registry.get_model(suggested_model_key)
            if suggested_model and suggested_model.enabled:
                model_key = suggested_model_key
                logger.info("Using ralph-suggested model %s for task %s", model_key, task.id)
            else:
                logger.warning(
                    "Ralph suggested model %s for task %s but it is %s; falling back to auto-select",
                    suggested_model_key,
                    task.id,
                    "disabled" if suggested_model else "not found",
                )

        if not model_key:
            model_key = select_model_for_task(task.type, registry)
        if not model_key:
            return None, None
        return model_key, registry.get_model(model_key)

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
        return f"""# Worker Contract

You are a {task_type} worker assigned by Foreman inside the Ralph workflow.

Rules:
- Execute the assigned scope.
- Do not renegotiate user scope or re-plan the workflow on your own.
- Work through the repo/task evidence first, then implement the smallest correct change.
- Report concrete evidence, changed files, and blockers back to Foreman.
- Raise risks or a better route early, with a specific recommendation.
- Do not spawn extra workers unless Foreman explicitly asks.

PROGRESS REPORTING:
- While working on long tasks, periodically report progress:
    cccc task heartbeat <task_id> --progress <0-100> --message "what you're doing"
- Send at least every 2-3 minutes for tasks expected to take >5 minutes.
- This prevents stall detection from flagging your task as stuck.

COMPLETION PROTOCOL (REQUIRED):
- After finishing ALL code changes, you MUST run:
    cccc task complete <task_id> --changed-file <path> --evidence "summary"
- This triggers the verification gate. Do NOT skip this step.
- Use `cccc send --to @foreman` ONLY for progress updates or blockers, NOT for completion.
"""

    def _profile_role_for_agent(self, role_type: str) -> str:
        if role_type == "reviewer":
            return REVIEWER_AGENT_PROFILE_ROLE
        if role_type == "specialist":
            return SECURITY_REVIEWER_AGENT_PROFILE_ROLE
        return DEFAULT_AGENT_PROFILE_ROLE

    def _load_saved_worker_prompt(self, role: str, runtime: str) -> Optional[str]:
        profile_path = self.agents_dir.parent / "agent_profiles" / role / f"{runtime}.yaml"
        if not profile_path.exists():
            return None
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Agent profile must contain a mapping: {profile_path}")
        worker_prompt = str(data.get("worker_prompt") or "")
        if not worker_prompt.strip():
            raise ValueError(f"Agent profile is missing worker_prompt: {profile_path}")
        logger.info("Using saved agent profile %s for runtime %s", role, runtime)
        return worker_prompt

    def assign_agent(self, agent_id: str, task_id: str) -> bool:
        """Mark an agent as assigned to a task.

        Args:
            agent_id: Agent ID
            task_id: Task ID

        Returns:
            True if assignment successful
        """
        return self._set_assignment_if_free(agent_id, task_id)

    def release_agent(self, agent_id: str) -> bool:
        """Release an agent from its current assignment.

        Args:
            agent_id: Agent ID

        Returns:
            True if release successful
        """
        return self._clear_assignment(agent_id)

    def get_active_assignments(self) -> Dict[str, str]:
        """Get all active agent assignments.

        Returns:
            Dict mapping agent_id to task_id
        """
        with self._assignment_lock:
            return dict(self._active_assignments)

    def _set_assignment_if_free(self, agent_id: str, task_id: str) -> bool:
        with self._assignment_lock:
            if agent_id in self._active_assignments:
                return False
            self._active_assignments[agent_id] = task_id
            return True

    def _clear_assignment(self, agent_id: str) -> bool:
        with self._assignment_lock:
            if agent_id not in self._active_assignments:
                return False
            del self._active_assignments[agent_id]
            return True

    def create_or_reuse_agent(
        self,
        task: TaskRef,
        *,
        min_score: int = 50,
        prefer_reuse: bool = True,
        busy_agent_ids: Optional[set] = None,
        suggested_model_key: Optional[str] = None,
    ) -> TaskAssignment:
        """Find or create an agent for a task.

        This is the main entry point for agent selection. It will:
        1. Try to find an existing suitable agent if prefer_reuse is True
        2. Try to find a matching group peer actor
        3. Create a new agent if no suitable agent found

        Args:
            task: Task to assign
            min_score: Minimum score for existing agent reuse
            prefer_reuse: Whether to prefer reusing existing agents
            busy_agent_ids: Set of agent IDs currently busy (from engine/shadow state)
            suggested_model_key: Model key suggested by ralph (preferred for new agents)

        Returns:
            TaskAssignment with the selected agent
        """
        assigned_agent: Optional[Agent] = None
        is_new = False
        reason = ""

        if prefer_reuse:
            # Try to find existing agent in agents_dir YAMLs
            assigned_agent = self.find_best_agent(task, min_score=min_score)
            if assigned_agent:
                reason = f"Reused existing agent with affinity for {task.type}"

        if not assigned_agent:
            # Try group peer actors before creating new
            assigned_agent = self._find_group_peer_agent(task, busy_agent_ids)
            if assigned_agent:
                reason = f"Reused group peer actor {assigned_agent.id}"

        if not assigned_agent:
            # Create new agent, passing ralph's model suggestion
            assigned_agent = self.create_agent_for_task(
                task, suggested_model_key=suggested_model_key,
            )
            is_new = True
            reason = self._last_assignment_warning or f"Created new agent for {task.type} task"

        if not assigned_agent:
            # Fallback: return a generic assignment
            return TaskAssignment(
                task=task,
                agent_id="",
                agent_name="",
                is_new_agent=False,
                assignment_reason=self._last_assignment_warning or "Failed to find or create agent",
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
            model_key=self._resolve_registry_model(
                self.get_model_registry(),
                assigned_agent.model_id,
            )[0] or assigned_agent.model_id,
        )

    def _resolve_registry_model(
        self,
        registry: ModelRegistry,
        model_id: str,
    ) -> tuple[Optional[str], Optional[ModelCapability]]:
        wanted = str(model_id or "").strip()
        if not wanted:
            return None, None
        for model_key, model in registry.models.items():
            if model_key == wanted or model.model_id == wanted:
                return model_key, model
        return None, None
