from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class TunedAgentVersion:
    """A versioned candidate for agent prompt optimization."""

    agent_id: str
    version: str  # "v1", "v2", ...
    base_prompt: str
    tuned_prompt: str
    score_summary: dict
    created_at: str
    status: str  # "candidate" | "promoted" | "rejected"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TunedAgentVersion":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
