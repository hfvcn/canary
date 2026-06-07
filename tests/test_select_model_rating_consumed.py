"""Regression: select_model_for_task consumes foreman_rating (read-end of the
model-evaluation loop).

Ratings written via `cccc model rate` were previously never read by the selector,
so the evaluation loop only ever wrote, never guided selection. These tests lock
that the rating now acts as the final routing signal among equally-matching models.
"""

from __future__ import annotations

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.daemon.ops.agent_ops import select_model_for_task


def _model(runtime: str, *, rating=None, strengths=None) -> ModelCapability:
    return ModelCapability(
        runtime=runtime,
        model_id=runtime,
        strengths=strengths or ["backend_implementation"],
        weaknesses=[],
        enabled=True,
        foreman_rating=rating,
    )


def test_higher_foreman_rating_wins_among_equal_matches():
    # Two enabled models match "backend" at the same tier/score; the higher-rated
    # one must win — proving the rating is actually consumed.
    registry = ModelRegistry(models={
        "low": _model("codex", rating=2.0),
        "high": _model("claude", rating=5.0),
    })
    assert select_model_for_task("backend", registry) == "high"

    # Flip the ratings -> the other one wins (not a fixed/iteration-order result).
    registry2 = ModelRegistry(models={
        "low": _model("codex", rating=5.0),
        "high": _model("claude", rating=2.0),
    })
    assert select_model_for_task("backend", registry2) == "low"


def test_unrated_model_treated_as_lowest():
    registry = ModelRegistry(models={
        "unrated": _model("codex", rating=None),
        "rated": _model("claude", rating=3.0),
    })
    assert select_model_for_task("backend", registry) == "rated"


def test_rating_does_not_override_capability_match():
    # A high rating must NOT make a non-matching model win: "frontend" does not
    # match a backend-only strength, so a high-rated backend model is not selected
    # for it.
    registry = ModelRegistry(models={
        "backend_only": _model("codex", rating=5.0, strengths=["backend_implementation"]),
    })
    assert select_model_for_task("frontend", registry) is None


def test_project_registry_routes_execution_to_codex():
    # Integration with the real project registry: execution task types route to the
    # codex runtime, review/aesthetic types route to claude.
    from pathlib import Path
    from cccc.daemon.ops.agent_ops import load_model_registry

    reg_path = Path(__file__).resolve().parents[1] / ".cccc" / "models" / "registry.yaml"
    if not reg_path.exists():
        return  # project registry not present in this checkout; skip silently
    reg = load_model_registry(reg_path)
    for execution_type in ("backend", "general", "api", "database", "testing"):
        key = select_model_for_task(execution_type, reg)
        assert key is not None and reg.models[key].runtime == "codex", (
            f"{execution_type} should route to codex runtime, got {key}"
        )
    for review_type in ("code_review", "security"):
        key = select_model_for_task(review_type, reg)
        assert key is not None and reg.models[key].runtime == "claude", (
            f"{review_type} should route to claude runtime, got {key}"
        )
