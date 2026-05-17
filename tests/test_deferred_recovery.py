from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus


WORKFLOW_ID = "wf-deferred"


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

    return create_group(load_registry(), title="deferred-recovery", topic="")


@pytest.fixture()
def temp_project_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        yield root


@pytest.fixture()
def orchestrator(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    registry = load_registry()
    group = create_group(registry, title="deferred-orchestrator", topic="")
    attach_scope_to_group(registry, group, detect_scope(temp_project_dir), set_active=True)
    return WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)


def test_deferred_task_can_retry_to_running_worker(group) -> None:
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-retry", title="retry"), WORKFLOW_ID)
    engine.defer_task("T-retry", "single writer")

    engine.retry_after_verification("T-retry")
    engine.register_batch("retry-batch", ["T-retry"])
    engine.approve_batch("retry-batch", [{"task_id": "T-retry", "agent_id": "agent-1", "claimed_paths": []}])
    engine.report_worker_started("T-retry", "agent-1")

    state = engine.get_task("T-retry")
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING
    assert state.blocked_reason == ""


def test_deferred_task_can_complete_by_foreman_override(group) -> None:
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-override", title="override"), WORKFLOW_ID)
    engine.defer_task("T-override", "waiting")

    engine.foreman_override_task("T-override", "accepted", "verified externally")

    state = engine.get_task("T-override")
    assert state is not None
    assert state.status == WorkflowTaskStatus.COMPLETED_BY_OVERRIDE
    assert state.blocked_reason == ""


def test_deferred_task_can_cancel(group) -> None:
    engine = WorkflowEngine(group)
    engine.register_task(TaskRef(id="T-cancel", title="cancel"), WORKFLOW_ID)
    engine.defer_task("T-cancel", "blocked")

    engine.cancel_task("T-cancel", "no longer needed")

    state = engine.get_task("T-cancel")
    assert state is not None
    assert state.status == WorkflowTaskStatus.CANCELLED
    assert state.blocked_reason == "no longer needed"


def test_downstream_dependencies_accept_completed_by_override(orchestrator) -> None:
    upstream = TaskRef(id="T-up", title="upstream")
    downstream = TaskRef(id="T-down", title="downstream", depends_on=["T-up"])
    orchestrator.engine.register_task(upstream, WORKFLOW_ID)
    orchestrator.engine.register_task(downstream, WORKFLOW_ID)
    orchestrator.engine.foreman_override_task("T-up", "accepted", "manual evidence")

    suggestion = orchestrator.ralph.suggest_ready_batch([downstream], workflow_id=WORKFLOW_ID)

    assert suggestion is not None
    assert [task.id for task in suggestion.tasks] == ["T-down"]

