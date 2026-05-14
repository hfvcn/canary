from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.kernel.workflow_state import WorkflowTaskStatus


WORKFLOW_ID = "wf-retry-running"
TASK_ID = "T1"
AGENT_ID = "agent-a"


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
    group = create_group(reg, title="retry-running", topic="")
    group = attach_scope_to_group(reg, group, detect_scope(temp_project_dir), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    finally:
        clear_orchestrator(group.group_id)


def _task() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="running task",
        type="backend",
        depends_on=[],
        claimed_paths=["src/retry_running.py"],
    )


def _register_running_task(orchestrator) -> None:
    orchestrator.register_and_suggest(
        [_task().model_dump()],
        WORKFLOW_ID,
        auto_dispatch=True,
        assignment_map={TASK_ID: AGENT_ID},
        auto_start_agents=False,
    )
    state = orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == AGENT_ID

    orchestrator.engine.report_worker_started(TASK_ID, AGENT_ID)
    assert orchestrator.engine.get_task(TASK_ID).status == WorkflowTaskStatus.RUNNING  # type: ignore[union-attr]


def _ledger_events(path: Path, kind: str) -> list[dict]:
    events: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        event = json.loads(raw)
        if event.get("kind") == kind:
            events.append(event)
    return events


def test_retry_running_task_becomes_ready_before_resuggest(orchestrator, monkeypatch) -> None:
    _register_running_task(orchestrator)
    resuggest_states: list[WorkflowTaskStatus] = []

    def capture_resuggest(workflow_id: str) -> None:
        assert workflow_id == WORKFLOW_ID
        state = orchestrator.engine.get_task(TASK_ID)
        assert state is not None
        resuggest_states.append(state.status)

    monkeypatch.setattr(orchestrator, "_resuggest_ready_tasks", capture_resuggest)

    result = orchestrator.retry_task(TASK_ID)
    state = orchestrator.engine.get_task(TASK_ID)

    assert result["accepted"] is True
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY
    assert resuggest_states == [WorkflowTaskStatus.READY]


def test_retry_running_task_auto_dispatches_assignment_map(orchestrator) -> None:
    _register_running_task(orchestrator)

    result = orchestrator.retry_task(TASK_ID)
    state = orchestrator.engine.get_task(TASK_ID)
    failed = _ledger_events(orchestrator.group.ledger_path, "workflow.task_failed")
    retries = _ledger_events(orchestrator.group.ledger_path, "workflow.retry_requested")

    assert result["accepted"] is True
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == AGENT_ID
    assert failed[-1]["data"]["error"]["reason"] == "stalled - auto-retry requested"
    assert retries[-1]["data"]["task_id"] == TASK_ID
