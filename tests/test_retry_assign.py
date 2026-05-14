from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.kernel.workflow_state import WorkflowTaskStatus


WORKFLOW_ID = "wf-retry-assign"
TASK_ID = "T1"
ORIGINAL_AGENT_ID = "agent-old"
NEW_AGENT_ID = "agent-new"


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "models:\n  codex:\n    runtime: codex\n    model_id: codex-latest\n    strengths: [general]\n    weaknesses: []\n",
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def orchestrator(temp_home, temp_project_dir):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator, clear_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="retry-assign", topic="")
    group = attach_scope_to_group(reg, group, detect_scope(temp_project_dir), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    finally:
        clear_orchestrator(group.group_id)


def _task() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="retry assign",
        type="backend",
        depends_on=[],
        claimed_paths=["src/retry_assign.py"],
    )


def _register_running_task(orchestrator, assigned_agent: str = ORIGINAL_AGENT_ID) -> None:
    assignment_map = {TASK_ID: assigned_agent}
    orchestrator.register_and_suggest(
        [_task().model_dump()],
        WORKFLOW_ID,
        auto_dispatch=True,
        assignment_map=assignment_map,
        auto_start_agents=False,
    )
    orchestrator.engine.set_workflow_meta(
        WORKFLOW_ID,
        auto_dispatch=True,
        assignment_map=assignment_map,
    )
    state = orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == assigned_agent
    orchestrator.engine.report_worker_started(TASK_ID, assigned_agent)
    running = orchestrator.engine.get_task(TASK_ID)
    assert running is not None
    assert running.status == WorkflowTaskStatus.RUNNING


def _active_assignment_map(orchestrator) -> dict[str, str]:
    workflow_data = orchestrator._active_workflows[WORKFLOW_ID]
    return dict(workflow_data.get("assignment_map") or {})


def _meta_assignment_map(orchestrator) -> dict[str, str]:
    meta = orchestrator.engine.get_workflow_meta(WORKFLOW_ID)
    assert meta is not None
    return dict(meta.assignment_map)


def test_retry_with_assign_updates_assignment_map(orchestrator) -> None:
    _register_running_task(orchestrator)

    result = orchestrator.retry_task(TASK_ID, assign_agent_id=NEW_AGENT_ID)
    state = orchestrator.engine.get_task(TASK_ID)

    assert result["accepted"] is True
    assert _active_assignment_map(orchestrator)[TASK_ID] == NEW_AGENT_ID
    assert _meta_assignment_map(orchestrator)[TASK_ID] == NEW_AGENT_ID
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == NEW_AGENT_ID


def test_retry_without_assign_unchanged(orchestrator) -> None:
    _register_running_task(orchestrator)

    result = orchestrator.retry_task(TASK_ID)
    state = orchestrator.engine.get_task(TASK_ID)

    assert result["accepted"] is True
    assert _active_assignment_map(orchestrator)[TASK_ID] == ORIGINAL_AGENT_ID
    assert _meta_assignment_map(orchestrator)[TASK_ID] == ORIGINAL_AGENT_ID
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == ORIGINAL_AGENT_ID


def test_retry_assign_returns_assigned_to(orchestrator, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_running_task(orchestrator)
    monkeypatch.setattr(orchestrator, "_resuggest_ready_tasks", lambda workflow_id: None)

    result = orchestrator.retry_task(TASK_ID, assign_agent_id=NEW_AGENT_ID)
    state = orchestrator.engine.get_task(TASK_ID)

    assert result["accepted"] is True
    assert result["action"] == "retry_requested"
    assert result["workflow_id"] == WORKFLOW_ID
    assert result["task_id"] == TASK_ID
    assert result["assigned_to"] == NEW_AGENT_ID
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY
