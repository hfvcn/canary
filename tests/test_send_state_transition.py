from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cccc.cli import messaging_cmds
from cccc.cli.main import build_parser
from cccc.contracts.v1 import DaemonRequest
from cccc.contracts.v1.agent import ModelRegistry
from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.ops.agent_ops import save_model_registry
from cccc.kernel.workflow_state import WorkflowTaskStatus


def _call(op: str, args: dict):
    from cccc.daemon.server import handle_request

    return handle_request(DaemonRequest.model_validate({"op": op, "args": args}))


def _prepare_project_root(project_root: Path) -> Path:
    for rel_path in (".cccc/agents", ".cccc/models", ".cccc/capabilities"):
        (project_root / rel_path).mkdir(parents=True, exist_ok=True)
    save_model_registry(ModelRegistry(models={}), project_root / ".cccc" / "models" / "registry.yaml")
    return project_root


def _create_group_with_worker(worker_id: str = "worker-1") -> str:
    create, _ = _call("group_create", {"title": "send-state", "topic": "", "by": "user"})
    assert create.ok, getattr(create, "error", None)
    group_id = str((create.result or {}).get("group_id") or "").strip()
    assert group_id
    add_actor, _ = _call(
        "actor_add",
        {
            "group_id": group_id,
            "actor_id": worker_id,
            "title": "Worker",
            "runtime": "codex",
            "runner": "headless",
            "enabled": True,
            "by": "user",
        },
    )
    assert add_actor.ok, getattr(add_actor, "error", None)
    return group_id


def _make_orchestrator(tmp_path: Path, group_id: str) -> WorkflowOrchestrator:
    project_root = _prepare_project_root(tmp_path / "project")
    return WorkflowOrchestrator(project_root=project_root, group_id=group_id)


def _register_ready_task(orchestrator: WorkflowOrchestrator, task_id: str = "T1") -> TaskRef:
    task = TaskRef(id=task_id, title="Manual send task", claimed_paths=["src/demo.py"])
    orchestrator.engine.register_task(task, "wf-send")
    orchestrator.engine.register_batch(f"batch-{task_id}", [task_id])
    return task


def _register_running_task(orchestrator: WorkflowOrchestrator, task_id: str = "T1") -> TaskRef:
    task = _register_ready_task(orchestrator, task_id)
    orchestrator.engine.approve_batch(
        f"batch-{task_id}",
        [{"task_id": task_id, "agent_id": "worker-1", "claimed_paths": list(task.claimed_paths or [])}],
    )
    orchestrator.engine.report_worker_started(task_id, "worker-1")
    return task


def test_send_parser_accepts_task_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["send", "hello", "--task", "T123"])
    assert args.task == "T123"


def test_cmd_send_forwards_task_id() -> None:
    captured = {}
    args = argparse.Namespace(
        group="g-sync",
        to=["worker-1"],
        priority="normal",
        reply_required=False,
        by="foreman-main",
        text="hello",
        path="",
        task="T123",
    )

    def _fake_call(req):
        captured["req"] = req
        return {"ok": True, "result": {"event": {"id": "ev-1"}}}

    fake_group = SimpleNamespace(doc={})
    with (
        patch.object(messaging_cmds, "_resolve_group_id", return_value="g-sync"),
        patch.object(messaging_cmds, "load_group", return_value=fake_group),
        patch.object(messaging_cmds, "_ensure_daemon_running", return_value=True),
        patch.object(messaging_cmds, "call_daemon", side_effect=_fake_call),
        patch.object(messaging_cmds, "_print_json"),
    ):
        exit_code = messaging_cmds.cmd_send(args)

    assert exit_code == 0
    assert captured["req"]["args"]["task_id"] == "T123"


def test_send_with_task_flag_transitions_to_running(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    group_id = _create_group_with_worker()
    orchestrator = _make_orchestrator(tmp_path, group_id)
    _register_ready_task(orchestrator)

    with patch("cccc.daemon.messaging.chat_ops._get_group_orchestrator", return_value=orchestrator):
        resp, _ = _call(
            "send",
            {
                "group_id": group_id,
                "by": "service:workflow_orchestrator",
                "to": ["worker-1"],
                "text": "start task",
                "task_id": "T1",
            },
        )

    assert resp.ok, getattr(resp, "error", None)
    state = orchestrator.engine.get_task("T1")
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING
    assert state.agent_id == "worker-1"


def test_send_without_task_flag_no_state_change(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    group_id = _create_group_with_worker()
    orchestrator = _make_orchestrator(tmp_path, group_id)
    _register_ready_task(orchestrator)

    with patch("cccc.daemon.messaging.chat_ops._get_group_orchestrator", return_value=orchestrator):
        resp, _ = _call(
            "send",
            {
                "group_id": group_id,
                "by": "service:workflow_orchestrator",
                "to": ["worker-1"],
                "text": "message only",
            },
        )

    assert resp.ok, getattr(resp, "error", None)
    state = orchestrator.engine.get_task("T1")
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY


def test_send_untrusted_sender_no_transition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    group_id = _create_group_with_worker()
    orchestrator = _make_orchestrator(tmp_path, group_id)
    _register_ready_task(orchestrator)

    with patch("cccc.daemon.messaging.chat_ops._get_group_orchestrator", return_value=orchestrator):
        resp, _ = _call(
            "send",
            {
                "group_id": group_id,
                "by": "worker-2",
                "to": ["worker-1"],
                "text": "spoofed start",
                "task_id": "T1",
            },
        )

    assert resp.ok, getattr(resp, "error", None)
    state = orchestrator.engine.get_task("T1")
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY


def test_send_task_already_running_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    group_id = _create_group_with_worker()
    orchestrator = _make_orchestrator(tmp_path, group_id)
    _register_running_task(orchestrator)

    orchestrator.manual_assign_task("T1", "worker-1")

    state = orchestrator.engine.get_task("T1")
    assert state is not None
    assert state.status == WorkflowTaskStatus.RUNNING
    assert state.agent_id == "worker-1"


def test_send_task_not_found_no_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    group_id = _create_group_with_worker()
    orchestrator = _make_orchestrator(tmp_path, group_id)

    with patch("cccc.daemon.messaging.chat_ops._get_group_orchestrator", return_value=orchestrator):
        resp, _ = _call(
            "send",
            {
                "group_id": group_id,
                "by": "foreman-main",
                "to": ["worker-1"],
                "text": "best effort start",
                "task_id": "MISSING",
            },
        )

    assert resp.ok, getattr(resp, "error", None)
    event = (resp.result or {}).get("event") if isinstance(resp.result, dict) else {}
    assert isinstance(event, dict)
    assert str(event.get("id") or "").strip()
