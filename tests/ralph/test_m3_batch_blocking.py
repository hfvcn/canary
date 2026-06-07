from __future__ import annotations

import json
import shlex
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.test_workflow_state import group, temp_home, temp_project_dir


TASK_ID = "T1"
WORKFLOW_ID = "wf-batch-gate"
AGENT_ID = "worker-1"
FAILED_CODE = "E_BATCH_E2E_FAILED"


def _read_ledger_events(ledger_path: Path, *, kind: str = "") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not ledger_path.exists():
        return events
    for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines():
        if not raw.strip():
            continue
        event = json.loads(raw)
        if kind and str(event.get("kind") or "") != kind:
            continue
        events.append(event)
    return events


def _batch_e2e_command(exit_code: int, *, stderr: str = "") -> str:
    python = shlex.quote(sys.executable)
    return (
        f"{python} -c "
        f"\"import sys; sys.stderr.write({stderr!r}); sys.exit({exit_code})\""
    )


def _managed_suppress_instance() -> dict[str, str]:
    today = date.today()
    return {
        "code": FAILED_CODE,
        "owner": "foreman",
        "expiry": (today + timedelta(days=30)).isoformat(),
        "review_after": (today + timedelta(days=7)).isoformat(),
    }


def _write_plan(
    project_root: Path,
    *,
    batch_e2e_command: str = "",
    suppress_codes: list[str] | None = None,
    suppress_instances: list[dict[str, str]] | None = None,
) -> Path:
    plan_path = project_root / "plan.yaml"
    payload: dict[str, Any] = {
        "tasks": [{"id": TASK_ID, "title": "Batch gate task"}],
        "batch_e2e_timeout": 5,
    }
    if batch_e2e_command:
        payload["batch_e2e_command"] = batch_e2e_command
    if suppress_codes is not None:
        payload["suppress_codes"] = suppress_codes
    if suppress_instances is not None:
        payload["suppress_instances"] = suppress_instances
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    return plan_path


def _setup_orchestrator(
    group,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    batch_e2e_command: str = "",
    suppress_codes: list[str] | None = None,
    suppress_instances: list[dict[str, str]] | None = None,
):
    from cccc.contracts.v1.ralph_ipc import TaskRef
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    plan_path = _write_plan(
        project_root,
        batch_e2e_command=batch_e2e_command,
        suppress_codes=suppress_codes,
        suppress_instances=suppress_instances,
    )
    orchestrator = WorkflowOrchestrator(project_root=project_root, group_id=group.group_id)
    monkeypatch.setattr(orchestrator.reporter, "_send_card", lambda _card: True)
    monkeypatch.setattr(orchestrator.foreman, "release_completed_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "cccc.daemon.foreman.workflow_orchestrator._workflow_eval_io.workflow_evaluation_empty_sections",
        lambda *_args, **_kwargs: [],
    )

    orchestrator.engine.register_task(TaskRef(id=TASK_ID, title="Batch gate task"), WORKFLOW_ID)
    orchestrator.engine.register_batch("b1", [TASK_ID])
    orchestrator.engine.approve_batch(
        "b1",
        [{"task_id": TASK_ID, "agent_id": AGENT_ID, "claimed_paths": []}],
    )
    orchestrator.engine.report_worker_started(TASK_ID, AGENT_ID)
    orchestrator.engine.set_workflow_meta(WORKFLOW_ID, plan_path=str(plan_path))

    orchestrator._ensure_active_workflow(WORKFLOW_ID)
    orchestrator._active_workflows[WORKFLOW_ID]["tasks"][TASK_ID] = {
        "status": "running",
        "agent_id": AGENT_ID,
        "agent_name": AGENT_ID,
        "claimed_paths": [],
        "workflow_id": WORKFLOW_ID,
    }
    orchestrator.reporter.on_batch_started(
        "b1",
        [{"id": TASK_ID, "title": "Batch gate task", "agent_name": AGENT_ID}],
        workflow_id=WORKFLOW_ID,
    )

    batch_statuses: list[str] = []
    batch_state_snapshots: list[dict[str, Any]] = []
    original_check_batch_completion = orchestrator._check_batch_completion

    def wrapped_check_batch_completion(workflow_id: str | None) -> str:
        status = original_check_batch_completion(workflow_id)
        batch_statuses.append(status)
        state = orchestrator.reporter.get_state()
        batch_state_snapshots.append({
            "status": getattr(state, "batch_e2e_status", None),
            "exempted": getattr(state, "batch_e2e_exempted", None),
            "completed_batches": getattr(state, "completed_batches", None),
        })
        return status

    monkeypatch.setattr(orchestrator, "_check_batch_completion", wrapped_check_batch_completion)

    batch_completed_calls: list[str] = []
    original_on_batch_completed = orchestrator.reporter.on_batch_completed

    def wrapped_on_batch_completed() -> bool:
        batch_completed_calls.append("called")
        return original_on_batch_completed()

    monkeypatch.setattr(orchestrator.reporter, "on_batch_completed", wrapped_on_batch_completed)
    return orchestrator, batch_statuses, batch_state_snapshots, batch_completed_calls


def test_batch_e2e_failure_blocks_workflow_completion(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _batch_e2e_command(3, stderr="boom\\n")
    orchestrator, batch_statuses, batch_state_snapshots, batch_completed_calls = _setup_orchestrator(
        group,
        temp_project_dir,
        monkeypatch,
        batch_e2e_command=command,
    )

    assert orchestrator.on_task_completed(TASK_ID, AGENT_ID, 1, [], workflow_id=WORKFLOW_ID) is True

    assert batch_statuses == ["blocked"]
    assert batch_state_snapshots == [{"status": "blocked", "exempted": False, "completed_batches": 0}]
    assert batch_completed_calls == []
    assert _read_ledger_events(group.ledger_path, kind="workflow.completed") == []
    assert _read_ledger_events(group.ledger_path, kind="workflow.failed") == []
    failed_events = _read_ledger_events(group.ledger_path, kind="batch.e2e_failed")
    assert len(failed_events) == 1
    assert failed_events[0]["data"]["exit_code"] == 3
    assert failed_events[0]["data"]["command"] == command
    assert WORKFLOW_ID in orchestrator._active_workflows
    assert orchestrator._active_workflows[WORKFLOW_ID]["batch_e2e_status"] == "blocked"
    state = orchestrator.reporter.get_state()
    assert state is not None
    assert state.batch_e2e_status == "blocked"
    assert state.completed_batches == 0


def test_batch_e2e_success_advances_normally(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _batch_e2e_command(0)
    orchestrator, batch_statuses, batch_state_snapshots, batch_completed_calls = _setup_orchestrator(
        group,
        temp_project_dir,
        monkeypatch,
        batch_e2e_command=command,
    )

    assert orchestrator.on_task_completed(TASK_ID, AGENT_ID, 1, [], workflow_id=WORKFLOW_ID) is True

    assert batch_statuses == ["pass"]
    assert batch_state_snapshots == [{"status": "pass", "exempted": False, "completed_batches": 1}]
    assert batch_completed_calls == ["called"]
    passed_events = _read_ledger_events(group.ledger_path, kind="batch.e2e_passed")
    assert len(passed_events) == 1
    assert passed_events[0]["data"]["exit_code"] == 0
    assert passed_events[0]["data"]["command"] == command
    assert len(_read_ledger_events(group.ledger_path, kind="workflow.completed")) == 1


def test_plain_suppress_codes_do_not_unblock_batch_e2e(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator, batch_statuses, batch_state_snapshots, batch_completed_calls = _setup_orchestrator(
        group,
        temp_project_dir,
        monkeypatch,
        batch_e2e_command=_batch_e2e_command(2, stderr="still blocked\\n"),
        suppress_codes=[FAILED_CODE],
    )

    assert orchestrator.on_task_completed(TASK_ID, AGENT_ID, 1, [], workflow_id=WORKFLOW_ID) is True

    assert batch_statuses == ["blocked"]
    assert batch_state_snapshots == [{"status": "blocked", "exempted": False, "completed_batches": 0}]
    assert batch_completed_calls == []
    assert len(_read_ledger_events(group.ledger_path, kind="batch.e2e_failed")) == 1
    assert _read_ledger_events(group.ledger_path, kind="workflow.completed") == []


def test_managed_suppress_instance_exempts_batch_e2e_failure(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator, batch_statuses, batch_state_snapshots, batch_completed_calls = _setup_orchestrator(
        group,
        temp_project_dir,
        monkeypatch,
        batch_e2e_command=_batch_e2e_command(5, stderr="managed\\n"),
        suppress_instances=[_managed_suppress_instance()],
    )

    assert orchestrator.on_task_completed(TASK_ID, AGENT_ID, 1, [], workflow_id=WORKFLOW_ID) is True

    assert batch_statuses == ["pass"]
    assert batch_state_snapshots == [{"status": "pass", "exempted": True, "completed_batches": 1}]
    assert batch_completed_calls == ["called"]
    assert len(_read_ledger_events(group.ledger_path, kind="batch.e2e_failed")) == 1
    assert len(_read_ledger_events(group.ledger_path, kind="workflow.completed")) == 1


def test_no_batch_e2e_command_keeps_existing_auto_complete_behavior(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator, batch_statuses, batch_state_snapshots, batch_completed_calls = _setup_orchestrator(
        group,
        temp_project_dir,
        monkeypatch,
    )

    assert orchestrator.on_task_completed(TASK_ID, AGENT_ID, 1, [], workflow_id=WORKFLOW_ID) is True

    assert batch_statuses == ["none"]
    assert batch_state_snapshots == [{"status": "none", "exempted": False, "completed_batches": 1}]
    assert batch_completed_calls == ["called"]
    assert _read_ledger_events(group.ledger_path, kind="batch.e2e_failed") == []
    assert _read_ledger_events(group.ledger_path, kind="batch.e2e_passed") == []
    assert len(_read_ledger_events(group.ledger_path, kind="workflow.completed")) == 1
