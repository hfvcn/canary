from dataclasses import dataclass


@dataclass(frozen=True)
class AssignmentPolicy:
    mode: str  # "auto" | "explicit" | "role_pool"
    explicit_actor_id: str = ""
    required_role: str = "worker"
    required_capabilities: tuple = ()
    preferred_model_key: str = ""


@dataclass(frozen=True)
class AgentAcquireRequest:
    run_id: str
    workflow_id: str
    node_id: str
    task: object  # TaskRef
    attempt_id: str
    group_id: str
    project_root: str
    assignment_policy: object  # AssignmentPolicy


@dataclass(frozen=True)
class AgentLease:
    lease_id: str
    agent_id: str
    actor_id: str
    model_runtime: str
    model_id: str
    model_key: str
    is_new_actor: bool
    assignment_reason: str
    task_id: str = ""
    node_id: str = ""
    attempt_id: str = ""
