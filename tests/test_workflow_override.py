from __future__ import annotations

import json
import os
import tempfile
from argparse import Namespace
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef
from cccc.kernel.workflow_state import WorkflowTaskStatus


WORKFLOW_ID = "wf-override"
TASK_ID = "T-override"


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
        yield root


@pytest.fixture()
def workflow_orchestrator(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator, get_orchestrator
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    registry = load_registry()
    group = create_group(registry, title="workflow-override", topic="")
    group = attach_scope_to_group(registry, group, detect_scope(temp_project_dir), set_active=True)
    orchestrator = get_orchestrator(group.group_id, project_root=temp_project_dir)
    assert orchestrator is not None
    try:
        yield group, orchestrator
    finally:
        clear_orchestrator(group.group_id)


def _ledger_events(path: Path, kind: str) -> list[dict]:
    return [
        json.loads(raw)
        for raw in path.read_text(encoding="utf-8", errors="strict").splitlines()
        if raw.strip() and json.loads(raw).get("kind") == kind
    ]


def test_workflow_override_parser_registers_command() -> None:
    from cccc.cli.main import build_parser
    from cccc.cli.workflow_cmds import cmd_workflow_override

    parser = build_parser()
    args = parser.parse_args(["workflow", "override", "--task", TASK_ID, "--reason", "accepted", "--evidence", "reviewed"])

    assert args.func is cmd_workflow_override
    assert args.task_id == TASK_ID


def test_cmd_workflow_override_sends_daemon_request(monkeypatch, capsys) -> None:
    from cccc.cli import workflow_cmds

    captured: dict[str, dict] = {}

    def fake_call_daemon(request):
        captured["request"] = request
        return {"ok": True, "result": {"status": "completed_by_override"}}

    monkeypatch.setattr(workflow_cmds, "_ensure_daemon_running", lambda: True)
    monkeypatch.setattr(workflow_cmds, "_task_request_context", lambda args: ("group-1", "/repo"))
    monkeypatch.setattr(workflow_cmds, "_resolve_task_workflow_id", lambda *args: WORKFLOW_ID)
    monkeypatch.setattr(workflow_cmds, "call_daemon", fake_call_daemon)

    code = workflow_cmds.cmd_workflow_override(
        Namespace(task_id=TASK_ID, reason="accepted", evidence="manual proof", workflow_id="", group="")
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output["ok"] is True
    assert captured["request"]["op"] == "workflow_override"
    assert captured["request"]["args"]["task_id"] == TASK_ID
    assert captured["request"]["args"]["evidence"] == "manual proof"


def test_workflow_override_op_sets_status_and_ledger_event(workflow_orchestrator) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    group, orchestrator = workflow_orchestrator
    orchestrator.engine.register_task(TaskRef(id=TASK_ID, title="Override task"), WORKFLOW_ID)

    response = try_handle_ralph_op(
        "workflow_override",
        {
            "group_id": group.group_id,
            "project_root": str(orchestrator.project_root),
            "workflow_id": WORKFLOW_ID,
            "task_id": TASK_ID,
            "reason": "Foreman accepted external evidence",
            "evidence": "unit test evidence",
        },
    )

    state = orchestrator.engine.get_task(TASK_ID)
    events = _ledger_events(group.ledger_path, "workflow.foreman_override")

    assert response is not None
    assert response.ok is True
    assert state is not None
    assert state.status == WorkflowTaskStatus.COMPLETED_BY_OVERRIDE
    assert events[-1]["data"]["reason"] == "Foreman accepted external evidence"
    assert events[-1]["data"]["evidence"] == "unit test evidence"
    assert isinstance(events[-1]["data"]["timestamp"], float)

