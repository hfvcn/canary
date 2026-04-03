"""Focused tests for AgentPoolManager scoring."""

from __future__ import annotations

import pytest

from cccc.contracts.v1.agent import Agent, ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import AgentPoolManager, _parse_context_window


def _make_pool_manager(tmp_path, monkeypatch, model: ModelCapability) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    manager = AgentPoolManager(
        agents_dir=agents_dir,
        models_registry_path=tmp_path / "registry.yaml",
        capabilities_dir=capabilities_dir,
    )
    registry = ModelRegistry(models={"test-model": model})
    monkeypatch.setattr(manager, "get_model_registry", lambda: registry)
    return manager


def _make_agent() -> Agent:
    return Agent(
        id="backend-worker",
        name="Backend Worker",
        model_runtime="claude",
        model_id="test-model",
        role_type="worker",
        capabilities=["task_execution", "code_modification", "memory_access"],
        task_affinity=["backend"],
    )


def _make_agent_with_affinity(agent_id: str, affinity: str) -> Agent:
    agent = _make_agent()
    agent.id = agent_id
    agent.name = f"{affinity.title()} Worker"
    agent.task_affinity = [affinity]
    return agent


def _make_task(
    *,
    task_type: str = "backend",
    claimed_paths: list[str] | None = None,
) -> TaskRef:
    return TaskRef(
        id="T1",
        title="Backend task",
        type=task_type,
        claimed_paths=claimed_paths or [],
    )


def test_weakness_penalty(tmp_path, monkeypatch):
    model = ModelCapability(
        runtime="claude",
        model_id="test-model",
        strengths=["backend"],
        weaknesses=["backend"],
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, model)

    score, reasons = manager._score_agent_for_task(_make_agent(), _make_task())

    assert score == 85
    assert "Model weakness: backend" in reasons


def test_foreman_rating_bonus(tmp_path, monkeypatch):
    model = ModelCapability(
        runtime="claude",
        model_id="test-model",
        strengths=["backend"],
        foreman_rating=5,
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, model)

    score, reasons = manager._score_agent_for_task(_make_agent(), _make_task())

    assert score == 110
    assert "Foreman rating: 5/5 (+10)" in reasons


def test_best_for_match(tmp_path, monkeypatch):
    model = ModelCapability(
        runtime="claude",
        model_id="test-model",
        strengths=["backend"],
        best_for="Backend development and API work",
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, model)

    score, reasons = manager._score_agent_for_task(_make_agent(), _make_task())

    assert score == 110
    assert "Model best_for match: Backend development and API work" in reasons


def test_context_window_bonus(tmp_path, monkeypatch):
    model = ModelCapability(
        runtime="claude",
        model_id="test-model",
        strengths=["backend"],
        context_window="200k",
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, model)
    task = _make_task(
        claimed_paths=[
            "src/a.py",
            "src/b.py",
            "src/c.py",
            "src/d.py",
            "src/e.py",
        ]
    )

    score, reasons = manager._score_agent_for_task(_make_agent(), task)

    assert score == 105
    assert "Large context window for multi-file task" in reasons


def test_backward_compat_no_rating(tmp_path, monkeypatch):
    model = ModelCapability(
        runtime="claude",
        model_id="test-model",
        strengths=["backend"],
    )
    manager = _make_pool_manager(tmp_path, monkeypatch, model)

    score, reasons = manager._score_agent_for_task(_make_agent(), _make_task())

    assert score == 100
    assert reasons == [
        "Affinity match: backend",
        "Worker role",
        "Has required capabilities",
        "Model strength: backend",
    ]


def test_path_domain_frontend(tmp_path, monkeypatch):
    model = ModelCapability(runtime="claude", model_id="test-model")
    manager = _make_pool_manager(tmp_path, monkeypatch, model)
    task = _make_task(
        task_type="general",
        claimed_paths=["src/frontend/App.tsx", "src/components/Nav.jsx"],
    )
    frontend_score, _ = manager._score_agent_for_task(
        _make_agent_with_affinity("frontend-worker", "frontend"),
        task,
    )
    backend_score, _ = manager._score_agent_for_task(
        _make_agent_with_affinity("backend-worker", "backend"),
        task,
    )

    assert frontend_score > backend_score
    assert frontend_score - backend_score == 25


def test_path_domain_backend(tmp_path, monkeypatch):
    model = ModelCapability(runtime="claude", model_id="test-model")
    manager = _make_pool_manager(tmp_path, monkeypatch, model)
    task = _make_task(
        task_type="general",
        claimed_paths=["src/api/handler.go", "src/server/router.rs"],
    )
    backend_score, _ = manager._score_agent_for_task(
        _make_agent_with_affinity("backend-worker", "backend"),
        task,
    )
    frontend_score, _ = manager._score_agent_for_task(
        _make_agent_with_affinity("frontend-worker", "frontend"),
        task,
    )

    assert backend_score > frontend_score
    assert backend_score - frontend_score == 25


def test_path_domain_mixed(tmp_path, monkeypatch):
    model = ModelCapability(runtime="claude", model_id="test-model")
    manager = _make_pool_manager(tmp_path, monkeypatch, model)
    task = _make_task(
        task_type="general",
        claimed_paths=["src/frontend/App.tsx", "src/backend/service.go"],
    )
    frontend_score, frontend_reasons = manager._score_agent_for_task(
        _make_agent_with_affinity("frontend-worker", "frontend"),
        task,
    )
    backend_score, backend_reasons = manager._score_agent_for_task(
        _make_agent_with_affinity("backend-worker", "backend"),
        task,
    )

    assert manager._infer_domain_from_paths(task.claimed_paths) == "general"
    assert frontend_score == backend_score
    assert not any("Path domain" in reason for reason in frontend_reasons)
    assert not any("Path domain" in reason for reason in backend_reasons)


def test_path_domain_empty(tmp_path, monkeypatch):
    model = ModelCapability(runtime="claude", model_id="test-model")
    manager = _make_pool_manager(tmp_path, monkeypatch, model)
    task = _make_task(task_type="general", claimed_paths=[])
    frontend_score, frontend_reasons = manager._score_agent_for_task(
        _make_agent_with_affinity("frontend-worker", "frontend"),
        task,
    )
    backend_score, backend_reasons = manager._score_agent_for_task(
        _make_agent_with_affinity("backend-worker", "backend"),
        task,
    )

    assert manager._infer_domain_from_paths(task.claimed_paths) == "general"
    assert frontend_score == backend_score
    assert not any("Path domain" in reason for reason in frontend_reasons)
    assert not any("Path domain" in reason for reason in backend_reasons)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("128k", 128_000),
        ("200k", 200_000),
        ("1m", 1_000_000),
        ("500000", 500_000),
    ],
)
def test_parse_context_window(value, expected):
    assert _parse_context_window(value) == expected
