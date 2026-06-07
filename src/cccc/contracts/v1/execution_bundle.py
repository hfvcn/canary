from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PromptProjection:
    base_prompt: str
    context_files: tuple = ()
    instruction_overlay: str = ""


@dataclass(frozen=True)
class VerificationSpec:
    level: str  # "unit" | "integration"
    checks: tuple = ()
    covers_tasks: tuple = ()
    covers_paths: tuple = ()
    covers_flows: tuple = ()


@dataclass(frozen=True)
class CCCCNodeMeta:
    """Per-node CCCC metadata sidecar for ExecutionBundle."""

    task: Any  # Full TaskRef object for AgentAcquireRequest construction
    group_id: str
    workflow_id: str
    assignment_policy: Any  # AssignmentPolicy from agent_lease
    task_id: str = ""
    verification_spec: Any = None  # VerificationSpec | None
    acceptance_criteria: str = ""
    critical_flows: tuple = ()
    forbidden_flows: tuple = ()
    prompt_projection: Any = None  # PromptProjection | None

    @property
    def task_role(self) -> Any:
        return self.task.role if hasattr(self.task, "role") else None

    @property
    def task_claimed_paths(self) -> Any:
        return self.task.claimed_paths if hasattr(self.task, "claimed_paths") else []


@dataclass(frozen=True)
class ExecutionBundle:
    """A complete execution package for one workflow run."""

    run_id: str
    workflow_id: str
    pipeline: dict  # AF PipelineSpec in native dict format
    engine_preference: str = "auto"  # "af" | "legacy" | "auto"
    warnings: list[str] = field(default_factory=list)
    cccc_meta: dict = field(default_factory=dict)  # node_id -> CCCCNodeMeta

    def to_dict(self) -> dict:
        return asdict(self)
