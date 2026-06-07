from __future__ import annotations

from cccc.agentflow.plan_compiler import PlanCompiler
from cccc.contracts.v1.agent import ModelCapability, ModelRegistry
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.af_gateway_bridge import task_ref_to_plan_task
from cccc.daemon.foreman.agent_pool import AgentPoolManager

BACKEND_TASK_ID = "t-backend"
GENERAL_TASK_ID = "t-gen"


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


def _make_registry() -> ModelRegistry:
    return ModelRegistry(
        models={
            "backend-model": ModelCapability(
                runtime="codex",
                model_id="backend-model",
                strengths=["backend"],
            ),
            "general-model": ModelCapability(
                runtime="codex",
                model_id="general-model",
                strengths=["general"],
            ),
        }
    )


def _compile_task(task_dict: dict) -> object:
    bundle = PlanCompiler().compile(
        {"tasks": [task_dict]},
        workflow_id="w",
        group_id="g",
    )
    return bundle.cccc_meta[task_dict["id"]].task


def test_task_ref_to_plan_task_preserves_type() -> None:
    task_dict = task_ref_to_plan_task(TaskRef(id=BACKEND_TASK_ID, type="backend"))

    assert "type" in task_dict
    assert task_dict["type"] == "backend"


def test_compiled_af_node_carries_task_type() -> None:
    task_dict = task_ref_to_plan_task(TaskRef(id=BACKEND_TASK_ID, type="backend"))

    bundle = PlanCompiler().compile(
        {"tasks": [task_dict]},
        workflow_id="w",
        group_id="g",
    )
    af_task = bundle.cccc_meta[BACKEND_TASK_ID].task

    assert af_task.type == "backend"


def test_af_selection_parity_with_control_plane(tmp_path, monkeypatch) -> None:
    pool = _make_pool_manager(tmp_path, monkeypatch, _make_registry())
    af_task = _compile_task(
        task_ref_to_plan_task(TaskRef(id=BACKEND_TASK_ID, type="backend"))
    )

    af_key, _ = pool.resolve_model_for_task(af_task, suggested_model_key=None)
    cp_key, _ = pool.resolve_model_for_task(
        TaskRef(id=BACKEND_TASK_ID, type="backend"),
        suggested_model_key=None,
    )
    gen_key, _ = pool.resolve_model_for_task(
        TaskRef(id=GENERAL_TASK_ID, type="general"),
        suggested_model_key=None,
    )

    assert cp_key != gen_key
    assert af_key == cp_key
    assert af_key != gen_key


def test_default_type_unchanged() -> None:
    task_dict = task_ref_to_plan_task(
        TaskRef(
            id="t-default",
            title="Default task",
            goal_behavior="Keep default routing behavior.",
            role="worker",
            depends_on=["t-setup"],
            claimed_paths=["src/cccc/daemon/foreman/af_gateway_bridge.py"],
            acceptance_criteria="Default task type remains general.",
        )
    )

    assert task_dict["id"] == "t-default"
    assert task_dict["type"] == "general"
    assert task_dict["title"] == "Default task"
    assert task_dict["goal_behavior"] == "Keep default routing behavior."
    assert task_dict["role"] == "worker"
    assert task_dict["depends_on"] == ["t-setup"]
    assert task_dict["claimed_paths"] == [
        "src/cccc/daemon/foreman/af_gateway_bridge.py"
    ]
    assert task_dict["acceptance_criteria"] == "Default task type remains general."
    assert "verification" not in task_dict
