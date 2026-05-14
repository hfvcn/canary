from __future__ import annotations

import json
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.kernel import workflow_state_types as wt
from cccc.kernel.group import Group, create_group
from cccc.kernel.registry import load_registry
from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus


WORKFLOW_ID = "wf-retry-assigned"
BATCH_ID = "batch-retry-assigned"
TASK_ID = "T-retry"
AGENT_ID = "agent-retry"
ATTEMPT_ID = "attempt-retry"
SEEDED_STATUSES = {
    WorkflowTaskStatus.ASSIGNED,
    WorkflowTaskStatus.RUNNING,
    WorkflowTaskStatus.VERIFYING,
    WorkflowTaskStatus.COMPLETED,
    WorkflowTaskStatus.FAILED,
}


@pytest.fixture()
def engine_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[WorkflowEngine, Group]:
    monkeypatch.setenv("CCCC_HOME", str(tmp_path / "cccc-home"))
    group = create_group(load_registry(), title="retry-assigned", topic="")
    return WorkflowEngine(group), group


def _seed_task(
    engine: WorkflowEngine,
    status: WorkflowTaskStatus,
    *,
    task_id: str = TASK_ID,
) -> None:
    if status not in SEEDED_STATUSES:
        raise AssertionError(f"unsupported seed status: {status.value}")

    task = TaskRef(id=task_id, title=task_id, claimed_paths=["src/retry.py"])
    engine.register_task(task, WORKFLOW_ID)
    engine.register_batch(BATCH_ID, [task_id])
    engine.approve_batch(
        BATCH_ID,
        [
            {
                "task_id": task_id,
                "agent_id": AGENT_ID,
                "claimed_paths": ["src/retry.py"],
                "attempt_id": ATTEMPT_ID,
            }
        ],
    )
    if status == WorkflowTaskStatus.ASSIGNED:
        return

    engine.report_worker_started(task_id, AGENT_ID)
    if status == WorkflowTaskStatus.RUNNING:
        return

    engine.report_worker_completion(
        task_id,
        {"idempotency_key": f"idem-{task_id}"},
        attempt_id=ATTEMPT_ID,
    )
    if status == WorkflowTaskStatus.VERIFYING:
        return

    outcome = "passed" if status == WorkflowTaskStatus.COMPLETED else "failed"
    engine.record_verification_result(task_id, _verification_result(task_id, outcome))


def _verification_result(task_id: str, outcome: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{task_id}",
        workflow_id=WORKFLOW_ID,
        task_id=task_id,
        overall_outcome=outcome,
        checks=[],
        summary=outcome,
    )


def _ledger_kinds(group: Group) -> list[str]:
    events = []
    for raw in group.ledger_path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            events.append(json.loads(raw))
    return [str(event.get("kind") or "") for event in events]


def test_retry_assigned_task_resets_to_ready(engine_group: tuple[WorkflowEngine, Group]) -> None:
    engine, group = engine_group
    _seed_task(engine, WorkflowTaskStatus.ASSIGNED)

    engine.retry_after_verification(TASK_ID)

    state = engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY
    assert state.agent_id == ""
    assert state.attempt_id == ""
    assert wt.KIND_RETRY_REQUESTED in _ledger_kinds(group)


@pytest.mark.parametrize("status", [WorkflowTaskStatus.VERIFYING, WorkflowTaskStatus.FAILED])
def test_retry_existing_retryable_states_still_work(
    engine_group: tuple[WorkflowEngine, Group],
    status: WorkflowTaskStatus,
) -> None:
    engine, _group = engine_group
    _seed_task(engine, status)

    engine.retry_after_verification(TASK_ID)

    state = engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == WorkflowTaskStatus.READY


@pytest.mark.parametrize("status", [WorkflowTaskStatus.RUNNING, WorkflowTaskStatus.COMPLETED])
def test_retry_non_retryable_states_still_rejected(
    engine_group: tuple[WorkflowEngine, Group],
    status: WorkflowTaskStatus,
) -> None:
    engine, _group = engine_group
    _seed_task(engine, status)

    with pytest.raises(ValueError, match="task not retryable"):
        engine.retry_after_verification(TASK_ID)

    state = engine.get_task(TASK_ID)
    assert state is not None
    assert state.status == status
