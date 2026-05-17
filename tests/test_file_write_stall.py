from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.workflow_monitor import MonitorAlert
from cccc.kernel.workflow_state import WorkflowTaskStatus


WORKFLOW_ID = "wf-file-write-stall"
TASK_ID = "T-progress"
AGENT_ID = "worker-progress"
THRESHOLD_SECONDS = 300


@pytest.fixture()
def orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CCCC_HOME", str(home))
    project_root = tmp_path / "project"
    _write_model_registry(project_root)

    from cccc.daemon.foreman.workflow_orchestrator import (
        WorkflowOrchestrator,
        clear_orchestrator,
    )
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    registry = load_registry()
    group = create_group(registry, title="file-write-stall", topic="")
    group = attach_scope_to_group(registry, group, detect_scope(project_root), set_active=True)
    try:
        yield WorkflowOrchestrator(project_root=project_root, group_id=group.group_id)
    finally:
        clear_orchestrator(group.group_id)


def _write_model_registry(project_root: Path) -> None:
    models_dir = project_root / ".cccc" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "agents").mkdir(parents=True, exist_ok=True)
    (project_root / ".cccc" / "capabilities").mkdir(parents=True, exist_ok=True)
    (models_dir / "registry.yaml").write_text(
        "\n".join(
            [
                "models:",
                "  codex:",
                "    runtime: codex",
                "    model_id: codex-latest",
                "    strengths: [backend, general]",
                "    weaknesses: []",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _task_ref() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Progress stall task",
        type="backend",
        claimed_paths=["src/progress.py"],
        verification=VerificationSpec(command="echo ok"),
    )


def _register_running_task(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    started_at: float = 900.0,
) -> None:
    monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: started_at)
    orchestrator.register_and_suggest(
        [_task_ref().model_dump()],
        WORKFLOW_ID,
        auto_dispatch=True,
        stall_auto_reassign=False,
        assignment_map={TASK_ID: AGENT_ID},
        auto_start_agents=False,
    )
    state = orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.ASSIGNED
    orchestrator.engine.report_worker_started(TASK_ID, AGENT_ID)


def _record_heartbeat(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    heartbeat_at: float,
    progress_pct: Optional[int],
) -> None:
    monkeypatch.setattr("cccc.kernel.workflow_state_engine.time.time", lambda: heartbeat_at)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: heartbeat_at)
    orchestrator.on_heartbeat(TASK_ID, progress_pct, "working")


def _capture_stall_outputs(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, Any]], list[MonitorAlert]]:
    notifications: list[dict[str, Any]] = []
    alerts: list[MonitorAlert] = []
    monkeypatch.setattr(
        orchestrator,
        "_notify_foreman_task_update",
        lambda **kwargs: notifications.append(kwargs) or True,
    )
    monkeypatch.setattr(orchestrator, "_record_violation", alerts.append)
    return notifications, alerts


def test_progress_pct_stagnant_with_recent_heartbeats_alerts(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch)
    for heartbeat_at in (1000.0, 1060.0, 1120.0, 1180.0, 1240.0):
        _record_heartbeat(orchestrator, monkeypatch, heartbeat_at=heartbeat_at, progress_pct=40)
    notifications, alerts = _capture_stall_outputs(orchestrator, monkeypatch)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1301.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)

    assert stalled == [TASK_ID]
    assert notifications[0]["new_status"] == "stalled"
    assert alerts[0].alert_type == "progress_stall"
    assert alerts[0].evidence["heartbeat_count"] == 5
    assert alerts[0].evidence["progress_pct"] == 40


def test_progress_pct_change_resets_stall_window(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch)
    for heartbeat_at, progress_pct in (
        (1000.0, 10),
        (1060.0, 10),
        (1120.0, 10),
        (1180.0, 20),
        (1240.0, 20),
    ):
        _record_heartbeat(
            orchestrator,
            monkeypatch,
            heartbeat_at=heartbeat_at,
            progress_pct=progress_pct,
        )
    notifications, alerts = _capture_stall_outputs(orchestrator, monkeypatch)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1301.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)

    assert stalled == []
    assert notifications == []
    assert alerts == []


def test_none_progress_pct_skips_progress_stall_detection(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch)
    for heartbeat_at in (1000.0, 1060.0, 1120.0, 1180.0, 1240.0):
        _record_heartbeat(orchestrator, monkeypatch, heartbeat_at=heartbeat_at, progress_pct=None)
    notifications, alerts = _capture_stall_outputs(orchestrator, monkeypatch)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1301.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)

    assert stalled == []
    assert notifications == []
    assert alerts == []


def test_no_heartbeat_uses_silent_agent_without_duplicate_progress_alert(
    orchestrator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register_running_task(orchestrator, monkeypatch, started_at=1000.0)
    notifications, alerts = _capture_stall_outputs(orchestrator, monkeypatch)
    monkeypatch.setattr("cccc.daemon.foreman.workflow_orchestrator.time.time", lambda: 1301.0)

    stalled = orchestrator.check_stalled_tasks(threshold_seconds=THRESHOLD_SECONDS)

    assert stalled == [TASK_ID]
    assert notifications[0]["new_status"] == "stalled"
    assert [alert.alert_type for alert in alerts] == ["silent_agent"]
