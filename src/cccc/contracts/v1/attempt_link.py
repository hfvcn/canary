from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class AttemptLink:
    """Trace index linking a task attempt to its execution context."""

    run_id: str
    workflow_id: str
    node_id: str
    task_id: str
    attempt_id: str
    actor_id: str
    agent_id: str
    model_key: str
    prompt_version: str
    trace_path: str  # relative path to trace file

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AttemptLink":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
