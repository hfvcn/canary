from __future__ import annotations

import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.kernel.workflow_state import WorkflowMeta, WorkflowTaskStatus


WORKFLOW_ID = "wf-stall-auto-reassign"
TASK_ID = "T1"
AGENT_ID = "agent-a"
STALE_SECONDS = 600
THRESHOLD_SECONDS = 300


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
        return
    os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def temp_project_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
        models = root / ".cccc" / "models"
        models.mkdir(parents=True, exist_ok=True)
        (models / "registry.yaml").write_text(
            "models:\n"
            "  codex:\n"
            "    runtime: codex\n"
            "    model_id: codex-latest\n"
            "    strengths: [general]\n"
            "    weaknesses: []\n",
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
    group = create_group(reg, title="stall-auto-reassign", topic="")
    group = attach_scope_to_group(reg, group, detect_scope(temp_project_dir), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    finally:
        clear_orchestrator(group.group_id)


def _task() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="stalled task",
        type="backend",
        depends_on=[],
        claimed_paths=["src/stalled.py"],
        verification=VerificationSpec(command="echo ok"),
    )


def _register_running_task(orchestrator: Any, *, stall_auto_reassign: bool = False) -> None:
    orchestrator.register_and_suggest(
        [_task().model_dump()],
        WORKFLOW_ID,
        auto_dispatch=True,
        stall_auto_reassign=stall_auto_reassign,
        assignment_map={TASK_ID: AGENT_ID},
        auto_start_agents=False,
    )
    state = orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    orchestrator.engine.report_worker_started(TASK_ID, AGENT_ID)


def _make_task_stalled(orchestrator: Any) -> None:
    state = orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    orchestrator.engine._tasks[TASK_ID] = replace(
        state,
        last_heartbeat=time.time() - STALE_SECONDS,
        progress_pct=25,
    )


def _capture_notifications(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    notifications: list[dict[str, Any]] = []

    def capture(**kwargs: Any) -> bool:
        notifications.append(kwargs)
        return True

    monkeypatch.setattr(orchestrator, "_notify_foreman_task_update", capture)
    return notifications


def test_workflow_meta_stall_auto_reassign_defaults_false() -> None:
    meta = WorkflowMeta(workflow_id=WORKFLOW_ID)

    assert meta.stall_auto_reassign is False


def test_register_and_suggest_persists_stall_auto_reassign(orchestrator: Any) -> None:
    _register_running_task(orchestrator, stall_auto_reassign=True)

    meta = orchestrator.engine.get_workflow_meta(WORKFLOW_ID)

    assert meta is not None
    assert meta.stall_auto_reassign is True


def test_check_stalled_tasks_only_notifies_by_default(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _register_running_task(orchestrator)
    _make_task_stalled(orchestrator)
    notifications = _capture_notifications(orchestrator, monkeypatch)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)
    state = orchestrator.engine.get_task(TASK_ID)

    assert stalled == [TASK_ID]
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING
    assert "auto-reassigned via stall_auto_reassign" not in notifications[0]["summary"]


def test_check_stalled_tasks_auto_reassigns_enabled_workflow(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, stall_auto_reassign=True)
    _make_task_stalled(orchestrator)
    notifications = _capture_notifications(orchestrator, monkeypatch)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)
    state = orchestrator.engine.get_task(TASK_ID)

    assert stalled == [TASK_ID]
    assert notifications[0]["new_status"] == "stalled"
    assert "auto-reassigned via stall_auto_reassign" in notifications[0]["summary"]
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert state.agent_id == AGENT_ID
