"""Focused tests for cost tier model scoring."""

from __future__ import annotations

from pathlib import Path

from cccc.contracts.v1.agent import ModelCapability
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import AgentPoolManager


def _make_manager(tmp_path: Path) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    return AgentPoolManager(
        agents_dir=agents_dir,
        models_registry_path=tmp_path / "registry.yaml",
        capabilities_dir=capabilities_dir,
    )


def _make_task(task_type: str = "general") -> TaskRef:
    task = TaskRef(id="T-cost-tier", title="Cost tier task")
    task.type = task_type  # type: ignore[assignment]
    return task


def _make_model(cost_tier: str | None = None) -> ModelCapability:
    return ModelCapability(
        runtime="codex",
        model_id="test-model",
        cost_tier=cost_tier,
    )


def test_budget_model_gets_bonus_on_simple_task(tmp_path):
    manager = _make_manager(tmp_path)

    score, reasons = manager._score_model_for_task(
        _make_model("budget"),
        _make_task(),
    )

    assert score == 8
    assert reasons == ["Cost tier bonus: budget (+8)"]


def test_premium_model_gets_no_bonus_on_simple_task(tmp_path):
    manager = _make_manager(tmp_path)

    score, reasons = manager._score_model_for_task(
        _make_model("premium"),
        _make_task(),
    )

    assert score == 0
    assert reasons == []


def test_missing_cost_tier_gets_no_bonus(tmp_path):
    manager = _make_manager(tmp_path)

    score, reasons = manager._score_model_for_task(_make_model(), _make_task())

    assert score == 0
    assert reasons == []


def test_complex_task_type_gets_no_cost_bonus(tmp_path):
    manager = _make_manager(tmp_path)

    score, reasons = manager._score_model_for_task(
        _make_model("budget"),
        _make_task("architecture_design"),
    )

    assert score == 0
    assert reasons == []


def test_standard_model_gets_bonus_on_simple_task(tmp_path):
    manager = _make_manager(tmp_path)

    score, reasons = manager._score_model_for_task(
        _make_model("standard"),
        _make_task(),
    )

    assert score == 4
    assert reasons == ["Cost tier bonus: standard (+4)"]


def test_model_capability_accepts_cost_tier_field():
    model = ModelCapability(
        runtime="codex",
        model_id="test-model",
        cost_tier="standard",
    )

    assert model.cost_tier == "standard"
    assert model.model_dump()["cost_tier"] == "standard"
