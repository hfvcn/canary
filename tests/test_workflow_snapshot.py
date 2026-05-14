from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def temp_home() -> Path:
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    reg = load_registry()
    return create_group(reg, title="workflow-snapshot", topic="")


def _register_task(engine, *, task_id: str, workflow_id: str, plan_path: Path | None = None) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef

    if plan_path is not None:
        engine.set_workflow_meta(workflow_id, plan_path=str(plan_path.resolve()))
    engine.register_task(
        TaskRef(
            id=task_id,
            title=f"task-{task_id}",
            type="backend",
            claimed_paths=[f"src/{task_id}.py"],
        ),
        workflow_id,
    )


def test_snapshot_round_trip_preserves_workflow_meta(group, tmp_path: Path) -> None:
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    plan_path = tmp_path / "plan.yaml"
    _register_task(engine, task_id="T1", workflow_id="wf-1", plan_path=plan_path)
    snapshot_path = tmp_path / "workflow-snapshot.json"

    WorkflowSnapshot(engine).take_snapshot(snapshot_path)
    snapshot_doc = json.loads(snapshot_path.read_text(encoding="utf-8"))

    restored_engine = WorkflowEngine(group)
    WorkflowSnapshot(restored_engine).restore_snapshot(snapshot_path)

    assert snapshot_doc["state"]["workflow_meta"] == [
        {
            "workflow_id": "wf-1",
            "plan_path": str(plan_path.resolve()),
            "plan_digest": "",
            "auto_dispatch": False,
            "stall_auto_reassign": False,
            "assignment_map": {},
        }
    ]
    meta = restored_engine.get_workflow_meta("wf-1")
    assert meta is not None
    assert meta.plan_path == str(plan_path.resolve())


def test_snapshot_state_hash_stable_across_workflow_meta(group, tmp_path: Path) -> None:
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    _register_task(engine, task_id="T2", workflow_id="wf-b", plan_path=tmp_path / "b.yaml")
    _register_task(engine, task_id="T1", workflow_id="wf-a", plan_path=tmp_path / "a.yaml")
    snapshotter = WorkflowSnapshot(engine)

    first = snapshotter.take_snapshot(tmp_path / "snapshot-1.json")
    second = snapshotter.take_snapshot(tmp_path / "snapshot-2.json")

    assert first.state_hash == second.state_hash


def test_legacy_snapshot_without_workflow_meta_restores(group, tmp_path: Path) -> None:
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine
    from cccc.kernel.workflow_state_types import WorkflowMeta

    engine = WorkflowEngine(group)
    snapshotter = WorkflowSnapshot(engine)
    snapshot_path = tmp_path / "legacy-snapshot.json"
    snapshotter.take_snapshot(snapshot_path)

    snapshot_doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_doc["state"].pop("workflow_meta", None)
    snapshot_doc["state_hash"] = snapshotter._state_hash(snapshot_doc["state"])
    snapshot_path.write_text(json.dumps(snapshot_doc), encoding="utf-8")

    restored_engine = WorkflowEngine(group)
    restored_engine._workflow_meta = {
        "wf-stale": WorkflowMeta(workflow_id="wf-stale", plan_path="/tmp/stale.yaml")
    }

    WorkflowSnapshot(restored_engine).restore_snapshot(snapshot_path)

    assert restored_engine._workflow_meta == {}


def test_multiple_workflows_meta_preserved(group, tmp_path: Path) -> None:
    from cccc.kernel.workflow_snapshot import WorkflowSnapshot
    from cccc.kernel.workflow_state import WorkflowEngine

    engine = WorkflowEngine(group)
    plan_a = tmp_path / "wf-a.yaml"
    plan_b = tmp_path / "wf-b.yaml"
    _register_task(engine, task_id="T1", workflow_id="wf-a", plan_path=plan_a)
    _register_task(engine, task_id="T2", workflow_id="wf-b", plan_path=plan_b)
    snapshot_path = tmp_path / "multi-workflow-snapshot.json"

    WorkflowSnapshot(engine).take_snapshot(snapshot_path)

    restored_engine = WorkflowEngine(group)
    WorkflowSnapshot(restored_engine).restore_snapshot(snapshot_path)

    meta_a = restored_engine.get_workflow_meta("wf-a")
    meta_b = restored_engine.get_workflow_meta("wf-b")
    assert meta_a is not None
    assert meta_b is not None
    assert meta_a.plan_path == str(plan_a.resolve())
    assert meta_b.plan_path == str(plan_b.resolve())
