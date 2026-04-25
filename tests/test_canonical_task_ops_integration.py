from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.ops import workflow_task_ops
from cccc.daemon.ralph_ipc_handler import handle_ralph_task_event
from cccc.kernel import workflow_state_types as wt
from cccc.kernel.workflow_state import WorkflowTaskStatus
from cccc.ports.web.routes import workflow as workflow_routes
from cccc.ports.web.schemas import RouteContext


GROUP_ID = "g-test"
WORKFLOW_ID = "wf-test"
TASK_ID = "T1"
AGENT_ID = "agent-1"
CLAIMED_PATH = "src/task.py"


def _make_orchestrator(tmp_path: Path) -> WorkflowOrchestrator:
    for rel in (".cccc/agents", ".cccc/capabilities", ".cccc/models"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    return WorkflowOrchestrator(project_root=tmp_path, group_id=GROUP_ID)


def _seed_task(orchestrator: WorkflowOrchestrator, status: WorkflowTaskStatus) -> None:
    task = TaskRef(id=TASK_ID, title="Canonical task", type="backend", claimed_paths=[CLAIMED_PATH])
    orchestrator.engine.register_task(task, WORKFLOW_ID)
    if status == WorkflowTaskStatus.PLANNED:
        return
    orchestrator.engine.register_batch("batch-1", [TASK_ID])
    if status == WorkflowTaskStatus.READY:
        return
    orchestrator.engine.approve_batch(
        "batch-1",
        [{"task_id": TASK_ID, "agent_id": AGENT_ID, "claimed_paths": [CLAIMED_PATH]}],
    )
    if status == WorkflowTaskStatus.ASSIGNED:
        return
    orchestrator.engine.report_worker_started(TASK_ID, AGENT_ID)
    if status == WorkflowTaskStatus.RUNNING:
        return
    if status == WorkflowTaskStatus.FAILED:
        orchestrator.engine.report_worker_failed(TASK_ID, {"error_message": "boom"})
        return
    raise AssertionError(f"unsupported seed status: {status}")


def _workflow_kinds(orchestrator: WorkflowOrchestrator) -> list[str]:
    kinds: list[str] = []
    for raw in orchestrator.group.ledger_path.read_text(encoding="utf-8").splitlines():
        if '"kind": "workflow.' not in raw:
            continue
        kinds.append(raw.split('"kind": "', 1)[1].split('"', 1)[0])
    return kinds


def _patch_canonical_orchestrator(orchestrator: WorkflowOrchestrator):
    orchestrator.ralph.verify_completion = Mock(
        return_value=VerificationResult(
            verification_id="ver-1",
            workflow_id=WORKFLOW_ID,
            task_id=TASK_ID,
            overall_outcome="passed",
            checks=[],
            summary="ok",
        )
    )
    orchestrator.on_task_completed = Mock(return_value=True)
    orchestrator.on_task_failed = Mock(return_value=True)
    orchestrator._notify_foreman_verification_result = Mock()
    return patch("cccc.daemon.ops.workflow_task_ops.get_orchestrator", return_value=orchestrator)


def test_complete_via_canonical_ops(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _seed_task(orchestrator, WorkflowTaskStatus.ASSIGNED)

    with _patch_canonical_orchestrator(orchestrator):
        result = workflow_task_ops.complete_task(
            GROUP_ID,
            TASK_ID,
            AGENT_ID,
            [CLAIMED_PATH],
            {"summary": "done"},
            WORKFLOW_ID,
            str(tmp_path),
            None,
        )

    assert result["ok"] is True
    assert result["result"]["verification_outcome"] == "passed"
    assert orchestrator.engine.get_task(TASK_ID).status == WorkflowTaskStatus.COMPLETED
    assert wt.KIND_TASK_REPORTED_COMPLETED in _workflow_kinds(orchestrator)
    assert _workflow_kinds(orchestrator)[-1] == wt.KIND_VERIFICATION_PASSED


def test_fail_via_canonical_ops(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _seed_task(orchestrator, WorkflowTaskStatus.ASSIGNED)

    with _patch_canonical_orchestrator(orchestrator):
        result = workflow_task_ops.fail_task(
            GROUP_ID,
            TASK_ID,
            AGENT_ID,
            "boom",
            WORKFLOW_ID,
            str(tmp_path),
            None,
        )

    assert result["ok"] is True
    assert result["result"]["event_type"] == "failed"
    assert orchestrator.engine.get_task(TASK_ID).status == WorkflowTaskStatus.FAILED
    assert _workflow_kinds(orchestrator)[-1] == wt.KIND_TASK_FAILED


def test_retry_via_canonical_ops(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _seed_task(orchestrator, WorkflowTaskStatus.FAILED)

    with patch("cccc.daemon.ops.workflow_task_ops.get_orchestrator", return_value=orchestrator):
        result = workflow_task_ops.retry_task(
            GROUP_ID,
            TASK_ID,
            WORKFLOW_ID,
            str(tmp_path),
            None,
        )

    assert result["ok"] is True
    assert result["result"]["action"] == "retry_requested"
    assert orchestrator.engine.get_task(TASK_ID).status == WorkflowTaskStatus.READY
    assert _workflow_kinds(orchestrator)[-1] == wt.KIND_RETRY_REQUESTED


def test_block_via_canonical_ops(tmp_path: Path) -> None:
    orchestrator = _make_orchestrator(tmp_path)
    _seed_task(orchestrator, WorkflowTaskStatus.PLANNED)

    with patch("cccc.daemon.ops.workflow_task_ops.get_orchestrator", return_value=orchestrator):
        result = workflow_task_ops.block_task(
            GROUP_ID,
            TASK_ID,
            "waiting on dependency",
            WORKFLOW_ID,
            str(tmp_path),
            None,
        )

    state = orchestrator.engine.get_task(TASK_ID)
    assert result["ok"] is True
    assert result["result"]["action"] == "blocked"
    assert state.status == WorkflowTaskStatus.BLOCKED
    assert state.blocked_reason == "waiting on dependency"
    assert _workflow_kinds(orchestrator)[-1] == wt.KIND_TASK_BLOCKED


def test_ipc_handler_delegates_to_canonical() -> None:
    canonical_result = {
        "ok": True,
        "result": {"accepted": True, "task_id": TASK_ID, "event_type": "completed"},
        "error": {},
    }
    with patch("cccc.daemon.ops.workflow_task_ops.complete_task", return_value=canonical_result) as complete_task:
        response = handle_ralph_task_event(
            {
                "group_id": GROUP_ID,
                "project_root": "/tmp/project",
                "task_id": TASK_ID,
                "event_type": "completed",
                "payload": {
                    "agent_id": AGENT_ID,
                    "workflow_id": WORKFLOW_ID,
                    "changed_files": [CLAIMED_PATH],
                    "evidence": {"summary": "done"},
                },
            }
        )

    assert response.ok is True
    assert response.result == canonical_result["result"]
    assert response.error is None
    complete_task.assert_called_once_with(
        group_id=GROUP_ID,
        task_id=TASK_ID,
        agent_id=AGENT_ID,
        changed_files=[CLAIMED_PATH],
        evidence={"summary": "done"},
        workflow_id=WORKFLOW_ID,
        project_root="/tmp/project",
        daemon_request_fn=None,
        assignment_id="",
        actor_run_id="",
    )


def test_no_direct_orchestrator_bypass() -> None:
    source = inspect.getsource(workflow_routes).replace("\r\n", "\n")
    ipc_source = inspect.getsource(handle_ralph_task_event).replace("\r\n", "\n")

    assert "from .ops.workflow_task_ops import complete_task, fail_task" in ipc_source
    assert "get_orchestrator(" not in ipc_source
    assert "direct_state_mutation" not in inspect.getsource(__import__("cccc.daemon.ralph_ipc_handler").daemon.ralph_ipc_handler)
    assert "from cccc.daemon.ops.workflow_task_ops import complete_task, fail_task, retry_task" in source


def test_http_route_completed_delegates_to_canonical(tmp_path: Path) -> None:
    async def fake_daemon(req):
        assert req["op"] == "group_show"
        return {
            "ok": True,
            "result": {
                "group": {
                    "active_scope_key": "scope-1",
                    "scopes": [{"scope_key": "scope-1", "url": str(tmp_path)}],
                }
            },
        }

    ctx = RouteContext(
        home=tmp_path,
        version="test",
        web_mode="normal",
        read_only=False,
        exhibit_cache_ttl_s=0.0,
        exhibit_allow_terminal=False,
        dist_dir=None,
        daemon=fake_daemon,
        cached_json=fake_daemon,
        apply_web_logging=lambda **_: None,
    )
    app = FastAPI()
    for router in workflow_routes.create_routers(ctx):
        app.include_router(router)

    canonical_result = {"ok": True, "result": {"accepted": True, "task_id": TASK_ID}, "error": {}}
    with (
        patch("cccc.ports.web.routes.workflow._require_task_state", return_value=SimpleNamespace(workflow_id=WORKFLOW_ID)),
        patch("cccc.ports.web.routes.workflow.complete_task", return_value=canonical_result) as complete_task,
        TestClient(app) as client,
    ):
        response = client.post(
            f"/api/v1/groups/{GROUP_ID}/workflow/task/completed",
            json={"task_id": TASK_ID, "agent_id": AGENT_ID, "changed_files": [CLAIMED_PATH]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "result": {"accepted": True, "task_id": TASK_ID, "event_type": "completed"},
        "error": {},
    }
    complete_task.assert_called_once()


def test_cli_complete_builds_canonical_task_event_request() -> None:
    from cccc.cli import workflow_cmds

    args = argparse.Namespace(
        group=GROUP_ID,
        task_id=TASK_ID,
        agent_id=AGENT_ID,
        changed_file=[CLAIMED_PATH],
        evidence='{"summary":"done"}',
        assignment_id="assign-1",
        actor_run_id="run-1",
        idempotency_key="idem-1",
        duration_seconds=0,
        workflow_id="",
    )

    with (
        patch("cccc.cli.workflow_cmds._ensure_daemon_running", return_value=True),
        patch("cccc.cli.workflow_cmds._resolve_group_id", return_value=GROUP_ID),
        patch("cccc.cli.workflow_cmds._resolve_project_root_for_group", return_value="/tmp/project"),
        patch("cccc.cli.workflow_cmds._resolve_task_workflow_id", return_value=WORKFLOW_ID),
        patch("cccc.cli.workflow_cmds.call_daemon", return_value={"ok": True, "result": {"accepted": True}}) as call_daemon,
        patch("cccc.cli.workflow_cmds._print_json"),
    ):
        exit_code = workflow_cmds.cmd_task_complete(args)

    assert exit_code == 0
    assert call_daemon.call_args.args[0] == {
        "op": "ralph_task_event",
        "args": {
            "group_id": GROUP_ID,
            "project_root": "/tmp/project",
            "event_type": "completed",
            "task_id": TASK_ID,
            "workflow_id": WORKFLOW_ID,
            "assignment_id": "assign-1",
            "actor_run_id": "run-1",
            "idempotency_key": "idem-1",
            "payload": {
                "agent_id": AGENT_ID,
                "workflow_id": WORKFLOW_ID,
                "duration_seconds": 0,
                "changed_files": [CLAIMED_PATH],
                "evidence": {"summary": "done"},
            },
            "agent_id": AGENT_ID,
            "changed_files": [CLAIMED_PATH],
            "evidence": {"summary": "done"},
            "override_stale_digest": False,
        },
    }
