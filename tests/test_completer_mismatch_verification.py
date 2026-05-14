from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from cccc.contracts.v1.ralph_ipc import TaskEvent, TaskRef, VerificationResult
from cccc.daemon.foreman.verification_gate import FORCE_COMPLETE_MISMATCH_WARNING
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.kernel.workflow_state import WorkflowTaskStatus
from cccc.kernel.workflow_state_types import KIND_VERIFICATION_PASSED, KIND_VERIFICATION_SKIPPED

DURATION_SECONDS = 1


@pytest.fixture
def orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkflowOrchestrator:
    orch = WorkflowOrchestrator(project_root=tmp_path, group_id="g-completer-mismatch")
    monkeypatch.setattr(orch, "on_task_completed", lambda *args, **kwargs: True)
    monkeypatch.setattr(orch, "on_task_failed", lambda *args, **kwargs: True)
    monkeypatch.setattr(orch, "_notify_foreman_verification_result", lambda *args, **kwargs: None)
    return orch


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    task_id: str,
    *,
    agent_id: str,
) -> TaskRef:
    task = TaskRef(id=task_id, title=task_id, type="backend")
    orchestrator.engine.register_task(task, f"wf-{task_id}")
    orchestrator.engine.register_batch(f"b-{task_id}", [task_id])
    orchestrator.engine.approve_batch(
        f"b-{task_id}",
        [{"task_id": task_id, "agent_id": agent_id, "claimed_paths": []}],
    )
    orchestrator.engine.report_worker_started(task_id, agent_id)
    return task


def _verification_result(task_id: str, workflow_id: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=workflow_id,
        task_id=task_id,
        overall_outcome="passed",
        checks=[],
        warnings=[],
        summary="ok",
    )


def _recording_verify(calls: list[dict[str, Any]]) -> Callable[..., VerificationResult]:
    def verify_completion(
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        calls.append({"task_id": task_id, "changed_files": changed_files, "task_ref": task_ref})
        return _verification_result(task_id, workflow_id)

    return verify_completion


def _complete(
    orchestrator: WorkflowOrchestrator,
    task_id: str,
    *,
    agent_id: str,
    force_complete: bool,
) -> dict[str, Any]:
    event = TaskEvent(
        task_id=task_id,
        event_type="completed",
        payload={
            "agent_id": agent_id,
            "duration_seconds": DURATION_SECONDS,
            "changed_files": [f"src/{task_id}.py"],
        },
    )
    return orchestrator.apply_task_event(event, force_complete=force_complete)


def _ledger_events(ledger_path: Path, kind: str) -> list[dict[str, Any]]:
    return [
        event
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for event in [json.loads(line)]
        if event.get("kind") == kind
    ]


def test_force_complete_with_completer_mismatch_runs_verification(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _register_running_task(orchestrator, "T-force-mismatch-runs", agent_id="worker-a")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(orchestrator.ralph, "verify_completion", _recording_verify(calls))

    result = _complete(orchestrator, task.id, agent_id="worker-b", force_complete=True)

    assert result["accepted"] is True
    assert result["verification_outcome"] == "passed"
    assert result["force_complete_overridden"] is True
    assert len(calls) == 1
    assert calls[0]["task_id"] == task.id
    assert orchestrator.engine.get_task(task.id).status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]
    assert not _ledger_events(orchestrator.group.ledger_path, KIND_VERIFICATION_SKIPPED)
    assert _ledger_events(orchestrator.group.ledger_path, KIND_VERIFICATION_PASSED)


def test_force_complete_without_completer_mismatch_skips_verification(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _register_running_task(orchestrator, "T-force-match-skips", agent_id="worker-a")

    def fail_verify(*args: Any, **kwargs: Any) -> VerificationResult:
        raise AssertionError("verify_completion should not run without mismatch")

    monkeypatch.setattr(orchestrator.ralph, "verify_completion", fail_verify)

    result = _complete(orchestrator, task.id, agent_id="worker-a", force_complete=True)

    assert result["accepted"] is True
    assert result["verification_outcome"] == "force_passed"
    assert "force_complete_overridden" not in result
    assert "warnings" not in result
    assert orchestrator.engine.get_task(task.id).status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]
    assert _ledger_events(orchestrator.group.ledger_path, KIND_VERIFICATION_SKIPPED)
    assert not _ledger_events(orchestrator.group.ledger_path, KIND_VERIFICATION_PASSED)


def test_non_force_complete_with_completer_mismatch_runs_normal_verification(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _register_running_task(orchestrator, "T-normal-mismatch", agent_id="worker-a")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(orchestrator.ralph, "verify_completion", _recording_verify(calls))

    result = _complete(orchestrator, task.id, agent_id="worker-b", force_complete=False)

    assert result["accepted"] is True
    assert result["verification_outcome"] == "passed"
    assert "force_complete_overridden" not in result
    assert "warnings" not in result
    assert len(calls) == 1
    assert orchestrator.engine.get_task(task.id).status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]


def test_force_complete_mismatch_warning_is_returned_and_recorded(
    orchestrator: WorkflowOrchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _register_running_task(orchestrator, "T-force-mismatch-warning", agent_id="worker-a")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(orchestrator.ralph, "verify_completion", _recording_verify(calls))

    result = _complete(orchestrator, task.id, agent_id="worker-b", force_complete=True)

    passed_events = _ledger_events(orchestrator.group.ledger_path, KIND_VERIFICATION_PASSED)
    verification = passed_events[-1]["data"]["verification"]

    assert result["warnings"] == [FORCE_COMPLETE_MISMATCH_WARNING]
    assert verification["warnings"] == [FORCE_COMPLETE_MISMATCH_WARNING]
    assert len(calls) == 1
