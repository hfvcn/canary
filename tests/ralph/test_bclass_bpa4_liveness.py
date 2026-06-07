from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_monitor import MonitorMode
from cccc.kernel.workflow_state import WorkflowTaskStatus
from cccc.kernel.workflow_state_types import KIND_MONITOR_VIOLATION, KIND_RETRY_REQUESTED


WORKFLOW_ID = "wf-bpa4-liveness"
TASK_ID = "T-bpa4"
AGENT_ID = "agent-bpa4"
THRESHOLD_SECONDS = 300
ASSIGNED_AT = 1_000.0


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
def temp_project_dir() -> Path:
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
def orchestrator(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator, clear_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    registry = load_registry()
    group = create_group(registry, title="bpa4-liveness", topic="")
    group = attach_scope_to_group(registry, group, detect_scope(temp_project_dir), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    finally:
        clear_orchestrator(group.group_id)


def _task() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="BPA-4 liveness task",
        type="backend",
        claimed_paths=["src/bpa4.py"],
        verification=VerificationSpec(command="echo ok"),
    )


def _events_of_kind(path: Path, kind: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if event.get("kind") == kind:
            events.append(event)
    return events


def _register_assigned_task(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: ASSIGNED_AT)
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


def _register_running_task(orchestrator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: ASSIGNED_AT)
    orchestrator.register_and_suggest(
        [_task().model_dump()],
        WORKFLOW_ID,
        auto_dispatch=False,
        auto_start_agents=False,
    )
    orchestrator.manual_assign_task(TASK_ID, AGENT_ID)
    state = orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING


def test_over_deadline_warn_emits_liveness_violation_and_preserves_stall_behavior(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_assigned_task(orchestrator, monkeypatch)
    notifications: list[dict[str, Any]] = []
    monkeypatch.setattr(
        orchestrator,
        "_notify_foreman_task_update",
        lambda **kwargs: notifications.append(kwargs) or True,
    )
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1_602.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)
    state = orchestrator.engine.get_task(TASK_ID)
    violations = [event["data"] for event in _events_of_kind(orchestrator.group.ledger_path, KIND_MONITOR_VIOLATION)]
    liveness = [event for event in violations if event["alert_type"] == "liveness"]

    assert stalled == [TASK_ID]
    assert notifications[0]["new_status"] == "stalled"
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    assert len(liveness) == 1
    assert liveness[0]["task_id"] == TASK_ID
    assert liveness[0]["monitor_mode"] == MonitorMode.WARN.value


def test_over_deadline_block_forces_escalation_out_of_stuck_state(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch)
    notifications: list[dict[str, Any]] = []
    orchestrator.engine.set_monitor_mode("liveness", MonitorMode.BLOCK)
    monkeypatch.setattr(
        orchestrator,
        "_notify_foreman_task_update",
        lambda **kwargs: notifications.append(kwargs) or True,
    )
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1_302.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)
    state = orchestrator.engine.get_task(TASK_ID)
    violations = [event["data"] for event in _events_of_kind(orchestrator.group.ledger_path, KIND_MONITOR_VIOLATION)]
    retries = _events_of_kind(orchestrator.group.ledger_path, KIND_RETRY_REQUESTED)
    liveness = [event for event in violations if event["alert_type"] == "liveness"]

    assert stalled == [TASK_ID]
    assert notifications[0]["new_status"] == "liveness_enforced"
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY
    assert retries[-1]["data"]["task_id"] == TASK_ID
    assert liveness[-1]["monitor_mode"] == MonitorMode.BLOCK.value


def test_under_deadline_does_not_emit_liveness_violation(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1_300.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)
    violations = [event["data"] for event in _events_of_kind(orchestrator.group.ledger_path, KIND_MONITOR_VIOLATION)]

    assert stalled == []
    assert [event for event in violations if event["alert_type"] == "liveness"] == []


def test_check_liveness_deadline_is_reachable_via_stall_patrol(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.daemon.foreman import workflow_orchestrator as orchestrator_module

    _register_assigned_task(orchestrator, monkeypatch)
    calls: list[tuple[str, float]] = []

    def spy(task, now, deadline_s):
        calls.append((task.task.id, deadline_s))
        return None

    monkeypatch.setattr(orchestrator_module, "check_liveness_deadline", spy)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1_100.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)

    assert stalled == []
    assert calls == [(TASK_ID, 601.0)]
