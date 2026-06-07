"""Regression tests for filtering disabled models during selection."""

from __future__ import annotations

from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import AgentPoolManager
from cccc.daemon.ops.agent_ops import create_agent, select_model_for_task


def _make_model(
    model_id: str,
    *,
    enabled: bool = True,
    strengths: list[str] | None = None,
    best_for: str = "",
    description: str = "",
) -> ModelCapability:
    return ModelCapability(
        runtime="codex",
        model_id=model_id,
        enabled=enabled,
        strengths=strengths or [],
        best_for=best_for,
        description=description,
    )


def _make_registry(models: dict[str, ModelCapability]) -> ModelRegistry:
    return ModelRegistry(models=models)


def _make_task(task_type: str = "backend") -> TaskRef:
    return TaskRef(id="T2", title="model-selection", type=task_type)


def _make_pool_manager(tmp_path, monkeypatch, registry: ModelRegistry) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    manager = AgentPoolManager(
        agents_dir=agents_dir,
        models_registry_path=tmp_path / "registry.yaml",
        capabilities_dir=capabilities_dir,
    )
    monkeypatch.setattr(manager, "get_model_registry", lambda: registry)
    return manager


def test_select_model_for_task_skips_disabled_highest_score_model():
    registry = _make_registry(
        {
            "claude-sonnet-4-6": _make_model(
                "claude-sonnet-4-6",
                enabled=False,
                strengths=["backend"],
            ),
            "codex-safe": _make_model("codex-safe", best_for="backend"),
        }
    )

    selected = select_model_for_task("backend", registry)

    assert selected == "codex-safe"
    assert selected != "claude-sonnet-4-6"


def test_select_model_for_task_returns_none_when_all_models_disabled():
    registry = _make_registry(
        {
            "claude-sonnet-4-6": _make_model(
                "claude-sonnet-4-6",
                enabled=False,
                strengths=["backend"],
            ),
            "codex-medium": _make_model(
                "codex-medium",
                enabled=False,
                best_for="backend",
            ),
        }
    )

    assert select_model_for_task("backend", registry) is None


def test_select_model_for_task_preserves_enabled_selection_behavior():
    registry = _make_registry(
        {
            "strength-model": _make_model("strength-model", strengths=["backend"]),
            "best-for-model": _make_model("best-for-model", best_for="backend"),
            "description-model": _make_model(
                "description-model",
                description="backend specialist for API work",
            ),
        }
    )

    assert select_model_for_task("backend", registry) == "strength-model"


def test_agent_pool_resolve_model_for_task_rejects_disabled_suggestion(
    tmp_path,
    monkeypatch,
):
    registry = _make_registry(
        {
            "claude-sonnet-4-6": _make_model(
                "claude-sonnet-4-6",
                enabled=False,
                strengths=["backend"],
            ),
            "codex-safe": _make_model("codex-safe", best_for="backend"),
        }
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, registry)

    model_key, model = manager.resolve_model_for_task(
        _make_task(),
        suggested_model_key="claude-sonnet-4-6",
    )

    assert model_key == "codex-safe"
    assert model == registry.get_model("codex-safe")


def test_evaluate_for_task_skips_agents_bound_to_disabled_registry_models(
    tmp_path,
    monkeypatch,
):
    registry = _make_registry(
        {
            "claude-sonnet-4-6": _make_model(
                "claude-sonnet-4-6",
                enabled=False,
                strengths=["backend"],
            ),
            "codex-safe": _make_model("codex-safe", best_for="backend"),
        }
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, registry)
    disabled_agent = create_agent(
        "disabled-backend-worker",
        "Disabled Backend Worker",
        manager.agents_dir,
        model_runtime="codex",
        model_id="claude-sonnet-4-6",
        role_type="worker",
        capabilities=["task_execution", "code_modification"],
        task_affinity=["backend"],
    )
    enabled_agent = create_agent(
        "enabled-backend-worker",
        "Enabled Backend Worker",
        manager.agents_dir,
        model_runtime="codex",
        model_id="codex-safe",
        role_type="worker",
        capabilities=["task_execution", "code_modification"],
        task_affinity=["backend"],
    )

    assert disabled_agent is not None
    assert enabled_agent is not None

    evaluations = manager.evaluate_for_task(_make_task())
    evaluated_agent_ids = [evaluation.agent.id for evaluation in evaluations]

    assert "disabled-backend-worker" not in evaluated_agent_ids
    assert "enabled-backend-worker" in evaluated_agent_ids

    best_agent = manager.find_best_agent(_make_task())

    assert best_agent is not None
    assert best_agent.id == "enabled-backend-worker"
