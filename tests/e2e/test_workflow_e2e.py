from __future__ import annotations

import os
import shlex
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _python_exit_command(code: int) -> str:
    script = f"import sys; sys.exit({code})"
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


@pytest.fixture(autouse=True)
def reset_workflow_globals() -> None:
    from cccc.daemon.foreman.workflow_orchestrator import _ORCHESTRATORS
    from cccc.daemon.ralph_ipc_handler import _RALPH_STATE

    _ORCHESTRATORS.clear()
    for value in _RALPH_STATE.values():
        if isinstance(value, dict):
            value.clear()


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
    group = create_group(reg, title="workflow-e2e", topic="")
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


def _submit_single_task_workflow(
    client: TestClient,
    *,
    group_id: str,
    workflow_id: str,
    verification_command: str,
) -> dict:
    response = client.post(
        f"/api/v1/groups/{group_id}/workflow/batch/suggest",
        json={
            "workflow_id": workflow_id,
            "tasks": [
                {
                    "id": "T1",
                    "title": "workflow-e2e-task",
                    "type": "backend",
                    "depends_on": [],
                    "claimed_paths": ["src/workflow_e2e.py"],
                    "verification_command": verification_command,
                }
            ],
            "auto_process": True,
            "auto_start_agents": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert bool(body.get("ok"))
    processing = ((body.get("result") or {}).get("processing")) or {}
    assert processing.get("status") == "processed"
    return body


def _get_workflow_progress(client: TestClient, *, group_id: str, workflow_id: str) -> dict:
    response = client.get(
        f"/api/v1/groups/{group_id}/workflow/progress",
        params={"workflow_id": workflow_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert bool(body.get("ok"))
    return (body.get("result") or {}).get("snapshot") or {}


def _get_assignment(snapshot: dict, task_id: str) -> dict:
    assignments = snapshot.get("assignments") or []
    assignment = next((item for item in assignments if item.get("task_id") == task_id), None)
    assert assignment is not None
    return assignment


def _install_verifying_probe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from cccc.kernel.workflow_state import WorkflowTaskStatus
    from cccc.kernel.workflow_state_engine import WorkflowEngine

    original = WorkflowEngine.record_verification_result
    seen_statuses: list[str] = []

    def wrapped(self: WorkflowEngine, task_id: str, result, **kwargs) -> None:
        task = self.get_task(task_id)
        assert task is not None
        seen_statuses.append(task.status.value)
        assert task.status == WorkflowTaskStatus.VERIFYING
        original(self, task_id, result, **kwargs)

    monkeypatch.setattr(WorkflowEngine, "record_verification_result", wrapped)
    return seen_statuses


def _get_engine_status(group_id: str, task_id: str) -> str:
    from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator

    orchestrator = get_orchestrator(group_id)
    assert orchestrator is not None
    task = orchestrator.engine.get_task(task_id)
    assert task is not None
    return task.status.value


def _set_task_verification_command(group_id: str, task_id: str, command: str) -> None:
    from cccc.daemon.foreman.workflow_orchestrator import get_orchestrator

    orchestrator = get_orchestrator(group_id)
    assert orchestrator is not None
    task = orchestrator.engine.get_task(task_id)
    assert task is not None
    updated_ref = task.task.model_copy(update={"verification_command": command})
    orchestrator.engine._tasks[task_id] = replace(task, task=updated_ref)


def test_workflow_positive_verify_pass(
    client: TestClient,
    temp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "wf-e2e-pass"
    seen_statuses = _install_verifying_probe(monkeypatch)

    _submit_single_task_workflow(
        client,
        group_id=temp_group.group_id,
        workflow_id=workflow_id,
        verification_command=_python_exit_command(0),
    )
    snapshot = _get_workflow_progress(client, group_id=temp_group.group_id, workflow_id=workflow_id)
    assignment = _get_assignment(snapshot, "T1")
    assert assignment.get("status") in ("pending", "assigned")
    assert str(assignment.get("agent_id") or "").strip()
    _set_task_verification_command(temp_group.group_id, "T1", _python_exit_command(0))

    completed = client.post(
        f"/api/v1/groups/{temp_group.group_id}/workflow/task/completed",
        json={
            "task_id": "T1",
            "agent_id": assignment["agent_id"],
            "duration_seconds": 0,
            "changed_files": [],
            "workflow_id": workflow_id,
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert bool(completed_body.get("ok"))
    result = completed_body.get("result") or {}
    assert result.get("accepted") is True
    assert result.get("verification_outcome") == "passed"
    assert seen_statuses == ["verifying"]

    final_snapshot = _get_workflow_progress(client, group_id=temp_group.group_id, workflow_id=workflow_id)
    final_assignment = _get_assignment(final_snapshot, "T1")
    assert final_assignment.get("status") == "completed"
    assert _get_engine_status(temp_group.group_id, "T1") == "completed"


def test_workflow_positive_verify_fail(
    client: TestClient,
    temp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = "wf-e2e-fail"
    seen_statuses = _install_verifying_probe(monkeypatch)

    _submit_single_task_workflow(
        client,
        group_id=temp_group.group_id,
        workflow_id=workflow_id,
        verification_command=_python_exit_command(1),
    )
    snapshot = _get_workflow_progress(client, group_id=temp_group.group_id, workflow_id=workflow_id)
    assignment = _get_assignment(snapshot, "T1")
    assert assignment.get("status") in ("pending", "assigned")
    _set_task_verification_command(temp_group.group_id, "T1", _python_exit_command(1))

    completed = client.post(
        f"/api/v1/groups/{temp_group.group_id}/workflow/task/completed",
        json={
            "task_id": "T1",
            "agent_id": assignment["agent_id"],
            "duration_seconds": 0,
            "changed_files": [],
            "workflow_id": workflow_id,
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert bool(completed_body.get("ok"))
    result = completed_body.get("result") or {}
    assert result.get("accepted") is True
    assert result.get("verification_outcome") == "failed"
    assert seen_statuses == ["verifying"]

    final_snapshot = _get_workflow_progress(client, group_id=temp_group.group_id, workflow_id=workflow_id)
    final_assignment = _get_assignment(final_snapshot, "T1")
    assert final_assignment.get("status") == "failed"
    assert _get_engine_status(temp_group.group_id, "T1") == "failed"
