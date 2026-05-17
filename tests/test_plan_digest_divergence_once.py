from __future__ import annotations

import json
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.kernel.group import Group
from cccc.kernel.workflow_state import WorkflowEngine
from cccc.kernel.workflow_state_types import (
    KIND_PLAN_DIGEST_DIVERGENCE,
    KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC,
    PreTransitionVetoed,
)


def test_divergence_emitted_once_per_workflow(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _setup_assigned_task(engine, task_id="T1", workflow_id="wf-1", batch_id="b1")
    calls = _register_blocking_hook(engine)

    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T1", "agent-1")
    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T1", "agent-1")

    assert calls == ["workflow.task_started", "workflow.task_started"]
    assert _count_kind(engine, KIND_PLAN_DIGEST_DIVERGENCE) == 1


def test_divergence_different_workflows_emit_separately(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _setup_assigned_task(engine, task_id="T1", workflow_id="wf-1", batch_id="b1")
    _setup_assigned_task(engine, task_id="T2", workflow_id="wf-2", batch_id="b2")
    _register_blocking_hook(engine)

    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T1", "agent-1")
    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T2", "agent-2")

    assert _count_kind(engine, KIND_PLAN_DIGEST_DIVERGENCE) == 2


def test_complete_workflow_resets_dedup(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _setup_assigned_task(engine, task_id="T1", workflow_id="wf-1", batch_id="b1")
    _register_blocking_hook(engine)

    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T1", "agent-1")
    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T1", "agent-1")
    engine.emit_workflow_terminal("wf-1", completed_count=0, failed_count=1, total=1)
    with pytest.raises(PreTransitionVetoed):
        engine.report_worker_started("T1", "agent-1")

    assert _count_kind(engine, KIND_PLAN_DIGEST_DIVERGENCE) == 2


def test_post_hoc_event_not_deduped(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    data = {
        "workflow_id": "wf-1",
        "task_id": "T1",
        "code": "plan_digest_divergence_post_hoc",
        "message": "post-hoc advisory",
    }

    engine._append(kind=KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC, data=data)
    engine._append(kind=KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC, data=data)

    assert _count_kind(engine, KIND_PLAN_DIGEST_DIVERGENCE_POST_HOC) == 2


def _engine(tmp_path: Path) -> WorkflowEngine:
    group_path = tmp_path / "group"
    group_path.mkdir()
    group = Group(group_id="group-1", path=group_path, doc={"active_scope_key": ""})
    return WorkflowEngine(group)


def _setup_assigned_task(
    engine: WorkflowEngine,
    *,
    task_id: str,
    workflow_id: str,
    batch_id: str,
) -> None:
    engine.register_task(TaskRef(id=task_id, title=task_id), workflow_id)
    engine.register_batch(batch_id, [task_id])
    engine.approve_batch(batch_id, [{"task_id": task_id, "agent_id": f"agent-{task_id}", "claimed_paths": []}])


def _register_blocking_hook(engine: WorkflowEngine) -> list[str]:
    calls: list[str] = []

    def hook(kind, data, workflow_engine) -> None:  # noqa: ANN001, ARG001
        calls.append(kind)
        raise PreTransitionVetoed(code="plan_digest_divergence", message="stale plan")

    engine.register_pre_transition_hook(hook)
    return calls


def _count_kind(engine: WorkflowEngine, kind: str) -> int:
    return sum(1 for event in _events(engine) if event.get("kind") == kind)


def _events(engine: WorkflowEngine) -> list[dict]:
    path = engine._group.ledger_path
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]
