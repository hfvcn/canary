from __future__ import annotations

from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.agent_pool import AgentPoolManager
from cccc.daemon.ops.agent_ops import load_model_registry, select_model_for_task
from cccc.ralph.models import TaskSpec
from cccc.ralph.task_typing import infer_task_type


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / ".cccc" / "models" / "registry.yaml"


def _make_peer_manager(tmp_path: Path, peers: list[dict[str, str]]) -> AgentPoolManager:
    agents_dir = tmp_path / "agents"
    capabilities_dir = tmp_path / "capabilities"
    agents_dir.mkdir()
    capabilities_dir.mkdir()
    return AgentPoolManager(
        agents_dir=agents_dir,
        models_registry_path=tmp_path / "registry.yaml",
        capabilities_dir=capabilities_dir,
        group_loader=lambda: peers,
    )


def _make_peer(actor_id: str, runtime: str) -> dict[str, str]:
    return {
        "id": actor_id,
        "title": actor_id,
        "runtime": runtime,
        "model_id": f"{runtime}-model",
    }


@pytest.mark.parametrize("task_type", ["frontend", "backend", "general", "security_review"])
def test_task_contract_types_accept_supported_values(task_type: str) -> None:
    assert TaskRef(id="T1", type=task_type).type == task_type
    assert TaskSpec(id="T1", type=task_type).type == task_type


def test_infer_task_type_promotes_only_default_general() -> None:
    assert infer_task_type("independent security review", "", "general") == "security_review"
    assert infer_task_type("Plain task", "No audit here", "general") == "general"
    assert infer_task_type("independent security review", "", "backend") == "backend"


def test_security_review_task_routes_to_claude_in_new_agent_path() -> None:
    task = TaskSpec(
        id="T-sec",
        title="independent security review for auth boundary",
    )

    task_ref = task.to_task_ref()
    registry = load_model_registry(REGISTRY_PATH)
    model_key = select_model_for_task(task_ref.type, registry)

    assert task_ref.type == "security_review"
    assert model_key is not None
    resolved_model = registry.get_model(model_key)
    assert resolved_model is not None
    assert resolved_model.runtime == "claude"


def test_security_review_peer_reuse_skips_pure_codex_peer(tmp_path: Path) -> None:
    manager = _make_peer_manager(tmp_path, [_make_peer("peer-codex", "codex")])
    task = TaskRef(
        id="T-sec",
        title="Security review",
        type="security_review",
        claimed_paths=["src/api/review.py"],
    )

    assert manager._find_group_peer_agent(task) is None


def test_security_review_peer_reuse_prefers_claude_and_keeps_normal_scoring(
    tmp_path: Path,
) -> None:
    peers = [_make_peer("peer-codex", "codex"), _make_peer("peer-claude", "claude")]
    manager = _make_peer_manager(tmp_path, peers)
    security_task = TaskRef(
        id="T-sec",
        title="Security review",
        type="security_review",
        claimed_paths=["src/api/review.py"],
    )
    backend_task = TaskRef(
        id="T-back",
        title="Backend task",
        type="backend",
        claimed_paths=["src/api/review.py"],
    )

    security_peer = manager._find_group_peer_agent(security_task)
    backend_peer = manager._find_group_peer_agent(backend_task)

    assert security_peer is not None
    assert security_peer.id == "peer-claude"
    assert security_peer.model_runtime == "claude"
    assert backend_peer is not None
    assert backend_peer.id == "peer-codex"
    assert backend_peer.model_runtime == "codex"
