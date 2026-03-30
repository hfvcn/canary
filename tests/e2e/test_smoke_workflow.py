from __future__ import annotations

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
    group = create_group(reg, title="smoke-workflow", topic="")
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
        with TestClient(create_app()) as client:
            yield client


def test_smoke_task_event_reaches_orchestrator(client: TestClient, temp_group) -> None:
    """Phase 0 核心验证：task_event 必须进入 orchestrator 主路径。"""
    group_id = temp_group.group_id
    workflow_id = "wf-smoke"

    suggest = client.post(
        f"/api/v1/groups/{group_id}/workflow/batch/suggest",
        json={
            "workflow_id": workflow_id,
            "tasks": [
                {
                    "id": "T1",
                    "title": "backend-1",
                    "type": "backend",
                    "depends_on": [],
                    "claimed_paths": ["src/a.py"],
                },
                {
                    "id": "T2",
                    "title": "frontend-1",
                    "type": "frontend",
                    "depends_on": ["T1"],
                    "claimed_paths": ["web/a.tsx"],
                },
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

    completed = client.post(
        f"/api/v1/groups/{group_id}/workflow/task/completed",
        json={
            "task_id": "T1",
            "agent_id": "codex-backend-1",
            "duration_seconds": 0,
            "changed_files": [],
            "workflow_id": workflow_id,
        },
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert bool(completed_body.get("ok"))
    assert (((completed_body.get("result") or {}).get("accepted")) or False) is True

    progress = client.get(
        f"/api/v1/groups/{group_id}/workflow/progress",
        params={"workflow_id": workflow_id},
    )
    assert progress.status_code == 200
    progress_body = progress.json()
    assert bool(progress_body.get("ok"))

    snapshot = ((progress_body.get("result") or {}).get("snapshot")) or {}
    assignments = snapshot.get("assignments") or []
    t1 = next((a for a in assignments if a.get("task_id") == "T1"), None)
    assert t1 is not None
    assert str(t1.get("status") or "") != "pending"

