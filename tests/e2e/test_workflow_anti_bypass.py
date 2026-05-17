from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


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
        (root / ".cccc" / "models").mkdir(parents=True, exist_ok=True)
        (root / ".cccc" / "models" / "registry.yaml").write_text(
            "\n".join(
                [
                    "models:",
                    "  codex:",
                    "    runtime: codex",
                    "    model_id: codex-latest",
                    "    strengths: [backend, frontend, general]",
                    "    weaknesses: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        yield root


@pytest.fixture()
def temp_group(temp_home: Path, temp_project_dir: Path):  # noqa: ARG001
    from cccc.kernel.group import attach_scope_to_group, create_group
    from cccc.kernel.registry import load_registry
    from cccc.kernel.scope import detect_scope

    reg = load_registry()
    group = create_group(reg, title="workflow-anti-bypass", topic="")
    scope = detect_scope(temp_project_dir)
    return attach_scope_to_group(reg, group, scope, set_active=True)


def _local_call_daemon(req: dict) -> dict:
    from cccc.contracts.v1 import DaemonRequest
    from cccc.daemon.server import handle_request

    request = DaemonRequest.model_validate(req)
    resp, _ = handle_request(request)
    return resp.model_dump(exclude_none=True)


@pytest.fixture()
def client(temp_home: Path):  # noqa: ARG001
    from cccc.ports.web.app import create_app

    with patch("cccc.ports.web.app.call_daemon", side_effect=_local_call_daemon):
        with TestClient(create_app()) as test_client:
            yield test_client


def _count_kind(ledger_path: Path, *, kind: str) -> int:
    count = 0
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if str(event.get("kind") or "") == kind:
            count += 1
    return count


def test_message_send_does_not_complete_task(client: TestClient, temp_group) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    group_id = temp_group.group_id
    workflow_id = "wf-anti-bypass"
    task_id = "T1"
    agent_id = "codex-backend-1"

    suggest = client.post(
        f"/api/v1/groups/{group_id}/workflow/batch/suggest",
        json={
            "workflow_id": workflow_id,
            "tasks": [
                {
                    "id": task_id,
                    "title": "backend-1",
                    "type": "backend",
                    "depends_on": [],
                    "claimed_paths": ["src/a.py"],
                    "verification": {"command": "echo ok"},
                }
            ],
            "auto_process": True,
            "auto_start_agents": False,
        },
    )
    assert suggest.status_code == 200
    suggest_body = suggest.json()
    assert bool(suggest_body.get("ok"))
    processing = ((suggest_body.get("result") or {}).get("processing")) or {}
    assert processing.get("status") == "processed"

    orchestrator = get_orchestrator(group_id)
    assert orchestrator is not None
    task_state = orchestrator.engine.get_task(task_id)
    assert task_state is not None
    assert task_state.status == WorkflowTaskStatus.ASSIGNED

    before_completion_events = _count_kind(
        temp_group.ledger_path,
        kind="workflow.task_reported_completed",
    )

    message = client.post(
        f"/api/v1/groups/{group_id}/send",
        json={
            "by": agent_id,
            "to": ["user"],
            "text": "I'm done. completed.",
        },
    )
    assert message.status_code == 200
    message_body = message.json()
    assert bool(message_body.get("ok"))

    task_state = orchestrator.engine.get_task(task_id)
    assert task_state is not None
    assert task_state.status in {
        WorkflowTaskStatus.ASSIGNED,
        WorkflowTaskStatus.RUNNING,
    }
    assert (
        _count_kind(temp_group.ledger_path, kind="workflow.task_reported_completed")
        == before_completion_events
    )

    progress = client.get(
        f"/api/v1/groups/{group_id}/workflow/progress",
        params={"workflow_id": workflow_id},
    )
    assert progress.status_code == 200
    progress_body = progress.json()
    assert bool(progress_body.get("ok"))
    snapshot = ((progress_body.get("result") or {}).get("snapshot")) or {}
    assignments = snapshot.get("assignments") or []
    task_snapshot = next((item for item in assignments if item.get("task_id") == task_id), None)
    assert task_snapshot is not None
    assert str(task_snapshot.get("status") or "") != "completed"

    completed = client.post(
        f"/api/v1/groups/{group_id}/workflow/task/completed",
        json={
            "task_id": task_id,
            "agent_id": agent_id,
            "duration_seconds": 0,
            "changed_files": [],
            "workflow_id": workflow_id,
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert bool(completed_body.get("ok"))
    assert (((completed_body.get("result") or {}).get("accepted")) or False) is True

    task_state = orchestrator.engine.get_task(task_id)
    assert task_state is not None
    # With verification configured (command="echo ok"), the proper completion API
    # triggers verification which passes, so the task reaches COMPLETED.
    # The anti-bypass invariant (message_send doesn't complete) is tested above.
    assert task_state.status == WorkflowTaskStatus.COMPLETED
    assert (
        _count_kind(temp_group.ledger_path, kind="workflow.task_reported_completed")
        == before_completion_events + 1
    )
