"""RO-25: verification skipped must NOT transition to COMPLETED.

When no verification commands are configured, the outcome is "skipped".
This must result in FAILED status (not COMPLETED), because an unverified task
should not be considered complete. The ledger event
KIND_VERIFICATION_SKIPPED_BLOCKED is written for the audit trail.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


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
def group(temp_home: Path):  # noqa: ARG001
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    reg = load_registry()
    return create_group(reg, title="verify-skip-test", topic="")


def _count_kind(ledger_path: Path, *, kind: str) -> int:
    if not ledger_path.exists():
        return 0
    count = 0
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("kind") == kind:
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_skipped_does_not_complete(group) -> None:
    """verify_completion with no commands -> skipped -> engine task status is FAILED."""
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    engine = WorkflowEngine(group)
    wf = "wf-skip-fail"
    engine.register_task(TaskRef(id="T1", title="skip task"), wf)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-skip-1"})

    vr = VerificationResult(
        verification_id="ver-skip-1",
        workflow_id=wf,
        task_id="T1",
        overall_outcome="skipped",
        checks=[],
        summary="verification skipped: no command configured",
    )
    engine.record_verification_result("T1", vr)
    assert engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]


def test_passed_still_completes(group) -> None:
    """verify_completion with passing commands -> passed -> engine task status is COMPLETED."""
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    engine = WorkflowEngine(group)
    wf = "wf-pass-ok"
    engine.register_task(TaskRef(id="T1", title="pass task"), wf)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-pass-1"})

    vr = VerificationResult(
        verification_id="ver-pass-1",
        workflow_id=wf,
        task_id="T1",
        overall_outcome="passed",
        checks=[],
        summary="all checks passed",
    )
    engine.record_verification_result("T1", vr)
    assert engine.get_task("T1").status == WorkflowTaskStatus.COMPLETED  # type: ignore[union-attr]


def test_failed_stays_failed(group) -> None:
    """verify_completion with failing commands -> failed -> FAILED."""
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    engine = WorkflowEngine(group)
    wf = "wf-fail-fail"
    engine.register_task(TaskRef(id="T1", title="fail task"), wf)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-fail-1"})

    vr = VerificationResult(
        verification_id="ver-fail-1",
        workflow_id=wf,
        task_id="T1",
        overall_outcome="failed",
        checks=[],
        summary="tests failed",
    )
    engine.record_verification_result("T1", vr)
    assert engine.get_task("T1").status == WorkflowTaskStatus.FAILED  # type: ignore[union-attr]


def test_skipped_ledger_event(group) -> None:
    """skipped writes KIND_VERIFICATION_SKIPPED_BLOCKED to ledger."""
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.workflow_state import WorkflowEngine
    from cccc.kernel.workflow_state_types import KIND_VERIFICATION_SKIPPED_BLOCKED

    engine = WorkflowEngine(group)
    wf = "wf-ledger-skip"
    engine.register_task(TaskRef(id="T1", title="ledger task"), wf)
    engine.register_batch("b1", ["T1"])
    engine.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine.report_worker_started("T1", "a1")
    engine.report_worker_completion("T1", {"idempotency_key": "idem-ledger-1"})

    before = _count_kind(group.ledger_path, kind=KIND_VERIFICATION_SKIPPED_BLOCKED)

    vr = VerificationResult(
        verification_id="ver-ledger-1",
        workflow_id=wf,
        task_id="T1",
        overall_outcome="skipped",
        checks=[],
        summary="verification skipped: no command configured",
    )
    engine.record_verification_result("T1", vr)

    after = _count_kind(group.ledger_path, kind=KIND_VERIFICATION_SKIPPED_BLOCKED)
    assert after == before + 1, (
        f"Expected KIND_VERIFICATION_SKIPPED_BLOCKED event; before={before}, after={after}"
    )


def test_skipped_replay_restores_failed(group) -> None:
    """Ledger replay of skipped verification must restore task to FAILED."""
    from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
    from cccc.kernel.group import load_group
    from cccc.kernel.workflow_state import WorkflowEngine, WorkflowTaskStatus

    wf = "wf-replay-skip"
    engine1 = WorkflowEngine(group)
    engine1.register_task(TaskRef(id="T1", title="replay task"), wf)
    engine1.register_batch("b1", ["T1"])
    engine1.approve_batch("b1", [{"task_id": "T1", "agent_id": "a1", "claimed_paths": []}])
    engine1.report_worker_started("T1", "a1")
    engine1.report_worker_completion("T1", {"idempotency_key": "idem-replay-1"})
    engine1.record_verification_result(
        "T1",
        VerificationResult(
            verification_id="ver-replay-1",
            workflow_id=wf,
            task_id="T1",
            overall_outcome="skipped",
            checks=[],
            summary="no checks",
        ),
    )

    # Replay from ledger
    loaded = load_group(group.group_id)
    assert loaded is not None
    engine2 = WorkflowEngine(loaded)
    engine2.replay_from_ledger()

    state = engine2.get_task("T1")
    assert state is not None
    assert state.status == WorkflowTaskStatus.FAILED, (
        f"After replay, skipped verification should be FAILED, got {state.status}"
    )
