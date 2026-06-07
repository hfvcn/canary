from dataclasses import FrozenInstanceError

import pytest

from cccc.contracts.v1.execution_bundle import (
    CCCCNodeMeta,
    ExecutionBundle,
    PromptProjection,
    VerificationSpec,
)
from cccc.contracts.v1.ralph_ipc import TaskRef


def _sample_meta(task: object = None) -> CCCCNodeMeta:
    return CCCCNodeMeta(
        task=task or {"id": "T15"},
        group_id="group-1",
        workflow_id="workflow-1",
        assignment_policy={"mode": "auto"},
        task_id="T15",
        verification_spec=VerificationSpec(level="unit", checks=("pytest",)),
        acceptance_criteria="contract can be serialized",
        critical_flows=("compile",),
        forbidden_flows=("silent fallback",),
        prompt_projection=PromptProjection(
            base_prompt="Implement T15",
            context_files=("plan.yaml",),
            instruction_overlay="Keep contracts decoupled",
        ),
    )


def test_execution_bundle_dataclasses_instantiate() -> None:
    prompt_projection = PromptProjection(
        base_prompt="Base prompt",
        context_files=("src/cccc/contracts/v1/execution_bundle.py",),
        instruction_overlay="Overlay",
    )
    verification_spec = VerificationSpec(level="integration", checks=("pytest",))
    meta = CCCCNodeMeta(
        task={"id": "T15"},
        group_id="group-1",
        workflow_id="workflow-1",
        assignment_policy={"mode": "auto"},
        task_id="T15",
        verification_spec=verification_spec,
        acceptance_criteria="passes",
        critical_flows=("happy-path",),
        forbidden_flows=("fallback",),
        prompt_projection=prompt_projection,
    )
    bundle = ExecutionBundle(
        run_id="run-1",
        workflow_id="workflow-1",
        pipeline={"nodes": [{"id": "node-1"}]},
        cccc_meta={"node-1": meta},
    )

    assert bundle.cccc_meta["node-1"] == meta
    assert meta.task_id == "T15"
    assert meta.verification_spec == verification_spec
    assert meta.prompt_projection == prompt_projection


@pytest.mark.parametrize(
    "instance,field_name,new_value",
    [
        (PromptProjection(base_prompt="base"), "base_prompt", "changed"),
        (VerificationSpec(level="unit"), "level", "integration"),
        (_sample_meta(), "group_id", "group-2"),
        (ExecutionBundle(run_id="run-1", workflow_id="workflow-1", pipeline={}), "run_id", "run-2"),
    ],
)
def test_execution_bundle_dataclasses_are_frozen(instance: object, field_name: str, new_value: object) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field_name, new_value)


def test_execution_bundle_to_dict_serializes_nested_dataclasses() -> None:
    meta = _sample_meta()
    bundle = ExecutionBundle(
        run_id="run-1",
        workflow_id="workflow-1",
        pipeline={"nodes": [{"id": "node-1"}], "edges": []},
        cccc_meta={"node-1": meta},
    )

    assert bundle.to_dict() == {
        "run_id": "run-1",
        "workflow_id": "workflow-1",
        "pipeline": {"nodes": [{"id": "node-1"}], "edges": []},
        "engine_preference": "auto",
        "warnings": [],
        "cccc_meta": {
            "node-1": {
                "task": {"id": "T15"},
                "group_id": "group-1",
                "workflow_id": "workflow-1",
                "assignment_policy": {"mode": "auto"},
                "task_id": "T15",
                "verification_spec": {
                    "level": "unit",
                    "checks": ("pytest",),
                    "covers_tasks": (),
                    "covers_paths": (),
                    "covers_flows": (),
                },
                "acceptance_criteria": "contract can be serialized",
                "critical_flows": ("compile",),
                "forbidden_flows": ("silent fallback",),
                "prompt_projection": {
                    "base_prompt": "Implement T15",
                    "context_files": ("plan.yaml",),
                    "instruction_overlay": "Keep contracts decoupled",
                },
            }
        },
    }


def test_execution_bundle_cccc_meta_is_keyed_by_node_id() -> None:
    meta = _sample_meta()
    bundle = ExecutionBundle(
        run_id="run-1",
        workflow_id="workflow-1",
        pipeline={"nodes": [{"id": "node-1"}]},
        cccc_meta={"node-1": meta},
    )

    assert list(bundle.cccc_meta) == ["node-1"]
    assert bundle.cccc_meta["node-1"] is meta


def test_prompt_projection_defaults() -> None:
    projection = PromptProjection(base_prompt="Base")

    assert projection.base_prompt == "Base"
    assert projection.context_files == ()
    assert projection.instruction_overlay == ""


def test_verification_spec_instantiation() -> None:
    spec = VerificationSpec(level="integration", checks=("pytest tests/e2e",))

    assert spec.level == "integration"
    assert spec.checks == ("pytest tests/e2e",)
    assert spec.covers_tasks == ()
    assert spec.covers_paths == ()
    assert spec.covers_flows == ()


def test_cccc_node_meta_stores_full_task_object() -> None:
    task = TaskRef(id="T15", title="ExecutionBundle schema", claimed_paths=["src/cccc/contracts/v1/execution_bundle.py"])
    meta = _sample_meta(task=task)

    assert meta.task is task
    assert meta.task.id == "T15"


def test_execution_bundle_import_path() -> None:
    from cccc.contracts.v1.execution_bundle import CCCCNodeMeta as ImportedCCCCNodeMeta
    from cccc.contracts.v1.execution_bundle import ExecutionBundle as ImportedExecutionBundle

    assert ImportedExecutionBundle is ExecutionBundle
    assert ImportedCCCCNodeMeta is CCCCNodeMeta
