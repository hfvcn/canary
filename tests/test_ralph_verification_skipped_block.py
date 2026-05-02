from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import pytest


TASK_ID = "T-skip-block"
AGENT_ID = "worker-1"


def _agent_completed() -> subprocess.CompletedProcess[str]:
    payload = {
        "passed": True,
        "summary": "agent simulation passed",
        "checks": [{"name": "foreman_case", "outcome": "passed"}],
    }
    return subprocess.CompletedProcess(
        args=["gemini"],
        returncode=0,
        stdout=json.dumps({"response": json.dumps(payload)}),
        stderr="",
    )


@dataclass(frozen=True)
class Runtime:
    project_root: Path
    group_id: str
    workflow_id: str
    orchestrator: Any
    updates: list[dict[str, Any]]


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Runtime]:
    from cccc.daemon.foreman.workflow_orchestrator import clear_orchestrator, get_orchestrator

    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "project"
    project_root.mkdir()
    group_id = f"group-{uuid4().hex}"
    workflow_id = f"wf-{uuid4().hex}"
    clear_orchestrator(group_id)
    orchestrator = get_orchestrator(group_id, project_root=project_root)
    assert orchestrator is not None

    updates: list[dict[str, Any]] = []
    orchestrator._notify_foreman_task_update = lambda **kw: updates.append(dict(kw))
    try:
        yield Runtime(
            project_root=project_root,
            group_id=group_id,
            workflow_id=workflow_id,
            orchestrator=orchestrator,
            updates=updates,
        )
    finally:
        clear_orchestrator(group_id)


def _seed_assigned_task(
    runtime: Runtime,
    *,
    task_id: str = TASK_ID,
    verification_mode: str = "ralph",
) -> None:
    from cccc.contracts.v1.ralph_ipc import TaskRef

    task = TaskRef(id=task_id, title=task_id, verification_mode=verification_mode)
    engine = runtime.orchestrator.engine
    engine.register_task(task, runtime.workflow_id)
    engine.register_batch(f"batch-{task_id}", [task_id])
    engine.approve_batch(
        f"batch-{task_id}",
        [{"task_id": task_id, "agent_id": AGENT_ID, "claimed_paths": []}],
    )


def _seed_verifying_task(runtime: Runtime, *, task_id: str = TASK_ID) -> None:
    _seed_assigned_task(runtime, task_id=task_id)
    runtime.orchestrator.engine.report_worker_started(task_id, AGENT_ID)
    runtime.orchestrator.engine.report_worker_completion(
        task_id,
        {"idempotency_key": f"idem-{uuid4().hex}"},
    )


def _complete_task_via_ipc(runtime: Runtime, *, task_id: str = TASK_ID) -> Any:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op

    return try_handle_ralph_op(
        "ralph_task_event",
        {
            "group_id": runtime.group_id,
            "project_root": str(runtime.project_root),
            "task_id": task_id,
            "event_type": "completed",
            "payload": {
                "agent_id": AGENT_ID,
                "workflow_id": runtime.workflow_id,
                "changed_files": [],
                "evidence": {"summary": "done"},
            },
        },
    )


def _workflow_kinds(runtime: Runtime) -> list[str]:
    ledger_path = runtime.orchestrator.group.ledger_path
    if not ledger_path.exists():
        return []
    events = []
    for raw in ledger_path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            events.append(json.loads(raw))
    return [str(event.get("kind") or "") for event in events]


def test_no_verification_commands_cannot_reach_completed(runtime: Runtime) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    _seed_assigned_task(runtime)
    response = _complete_task_via_ipc(runtime)

    assert response is not None
    assert response.ok is True
    assert response.result["verification_outcome"] == "skipped_blocked"
    state = runtime.orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.FAILED
    assert state.status != WorkflowTaskStatus.COMPLETED


def test_skipped_blocked_is_written_to_ledger_and_notification(runtime: Runtime) -> None:
    _seed_assigned_task(runtime)
    response = _complete_task_via_ipc(runtime)

    assert response is not None
    assert response.ok is True
    assert "workflow.verification_skipped_blocked" in _workflow_kinds(runtime)
    assert "workflow.verification_passed" not in _workflow_kinds(runtime)
    assert any(
        update.get("new_status") == "verification_skipped_blocked"
        for update in runtime.updates
    )


def test_agent_verification_mode_runs_agent(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    monkeypatch.setattr(
        "cccc.ralph.agent.subprocess.run",
        lambda command, **kwargs: _agent_completed(),
    )
    _seed_assigned_task(runtime, verification_mode="agent")
    response = _complete_task_via_ipc(runtime)

    assert response is not None
    assert response.ok is True
    assert response.result["verification_outcome"] == "passed"
    state = runtime.orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.COMPLETED
    assert "workflow.verification_passed" in _workflow_kinds(runtime)


def test_external_skipped_result_does_not_sync_completed(runtime: Runtime) -> None:
    from cccc.daemon.ralph_ipc_handler import try_handle_ralph_op
    from cccc.kernel.workflow_state import WorkflowTaskStatus

    _seed_verifying_task(runtime)
    response = try_handle_ralph_op(
        "ralph_verification_result",
        {
            "group_id": runtime.group_id,
            "project_root": str(runtime.project_root),
            "workflow_id": runtime.workflow_id,
            "task_id": TASK_ID,
            "overall_outcome": "skipped",
            "summary": "verification skipped",
        },
    )

    assert response is not None
    assert response.ok is True
    state = runtime.orchestrator.engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.FAILED
    assert "workflow.verification_skipped_blocked" in _workflow_kinds(runtime)
    assert all(update.get("new_status") != "completed" for update in runtime.updates)
