from __future__ import annotations

import json
from pathlib import Path

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
from cccc.daemon.foreman.workflow_monitor import FRESH_SELF_TEST_ALERT_PREFIX, MonitorMode
from cccc.daemon.ops import workflow_task_ops
from cccc.kernel.workflow_state_types import (
    KIND_MONITOR_VIOLATION,
    KIND_TASK_REPORTED_COMPLETED,
    KIND_TRANSITION_REJECTED,
    TransitionRejected,
)
from tests.test_workflow_state import group, temp_home, temp_project_dir


TASK_ID = "T-inv7"
WORKFLOW_ID = "wf-inv7"
AGENT_ID = "worker-inv7"
CHANGED_FILE = "src/inv7.py"


def _self_test(attempt_id: str) -> dict[str, str]:
    return {
        "outcome": "passed",
        "attempt_id": attempt_id,
        "ran_at": "2026-06-08T00:00:00Z",
    }


def test_complete_task_producer_chain_preserves_self_test(
    group,
    temp_project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    attempt_id = "attempt-producer"
    self_test = _self_test(attempt_id)
    _register_running_task(orchestrator, attempt_id=attempt_id)
    monkeypatch.setattr(workflow_task_ops, "get_orchestrator", lambda *args, **kwargs: orchestrator)
    monkeypatch.setattr(
        orchestrator.ralph,
        "verify_completion",
        lambda *args, **kwargs: _passing_verification(),
    )

    captured: dict[str, object] = {}
    original_report = orchestrator.engine.report_worker_completion

    def capture_completion(task_id, evidence, *, hook_ctx=None, attempt_id=""):
        captured["task_id"] = task_id
        captured["evidence"] = dict(evidence)
        captured["attempt_id"] = attempt_id
        return original_report(task_id, evidence, hook_ctx=hook_ctx, attempt_id=attempt_id)

    monkeypatch.setattr(orchestrator.engine, "report_worker_completion", capture_completion)

    result = workflow_task_ops.complete_task(
        group.group_id,
        TASK_ID,
        AGENT_ID,
        [CHANGED_FILE],
        {"self_test": self_test},
        WORKFLOW_ID,
        str(temp_project_dir),
        None,
        attempt_id=attempt_id,
    )

    assert result["ok"] is True
    assert captured["task_id"] == TASK_ID
    assert captured["attempt_id"] == attempt_id
    assert captured["evidence"]["self_test"] == self_test


def test_fresh_self_test_hook_is_registered_and_allows_current_attempt(
    group,
    temp_project_dir: Path,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    attempt_id = "attempt-fresh"
    _register_running_task(orchestrator, attempt_id=attempt_id)

    hook_ids = {getattr(hook, "invariant_id", "") for hook in orchestrator.engine._pre_transition_hooks}
    assert "fresh_self_test" in hook_ids

    orchestrator.engine.report_worker_completion(
        TASK_ID,
        {
            "agent_id": AGENT_ID,
            "changed_files": [CHANGED_FILE],
            "idempotency_key": "idem-fresh",
            "self_test": _self_test(attempt_id),
        },
        attempt_id=attempt_id,
    )

    assert _count_kind(group.ledger_path, KIND_TASK_REPORTED_COMPLETED) == 1
    assert _count_kind(group.ledger_path, KIND_MONITOR_VIOLATION) == 0


@pytest.mark.parametrize(
    ("label", "self_test"),
    [
        ("stale", _self_test("attempt-stale")),
        ("missing", None),
    ],
)
def test_warn_mode_emits_monitor_violation_for_stale_or_missing_self_test(
    group,
    temp_project_dir: Path,
    label: str,
    self_test: dict[str, str] | None,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    attempt_id = "attempt-current"
    _register_running_task(orchestrator, attempt_id=attempt_id)

    evidence = {
        "agent_id": AGENT_ID,
        "changed_files": [CHANGED_FILE],
        "idempotency_key": f"idem-{label}",
    }
    if self_test is not None:
        evidence["self_test"] = self_test

    orchestrator.engine.report_worker_completion(
        TASK_ID,
        evidence,
        attempt_id=attempt_id,
    )

    violations = _events_of_kind(group.ledger_path, KIND_MONITOR_VIOLATION)
    assert len(violations) == 1
    violation = violations[0]["data"]
    assert violation["alert_type"] == f"{FRESH_SELF_TEST_ALERT_PREFIX}:{TASK_ID}"
    assert violation["evidence"]["current_attempt_id"] == attempt_id
    assert violation["evidence"]["reason"] in {"missing_self_test", "stale_self_test"}


@pytest.mark.parametrize(
    ("label", "self_test"),
    [
        ("stale", _self_test("attempt-stale")),
        ("missing", None),
    ],
)
def test_block_mode_raises_transition_rejected_for_stale_or_missing_self_test(
    group,
    temp_project_dir: Path,
    label: str,
    self_test: dict[str, str] | None,
) -> None:
    orchestrator = WorkflowOrchestrator(project_root=temp_project_dir, group_id=group.group_id)
    attempt_id = "attempt-current"
    _register_running_task(orchestrator, attempt_id=attempt_id)
    orchestrator.engine.set_monitor_mode("fresh_self_test", MonitorMode.BLOCK)

    evidence = {
        "agent_id": AGENT_ID,
        "changed_files": [CHANGED_FILE],
        "idempotency_key": f"idem-block-{label}",
    }
    if self_test is not None:
        evidence["self_test"] = self_test

    with pytest.raises(TransitionRejected) as exc_info:
        orchestrator.engine.report_worker_completion(
            TASK_ID,
            evidence,
            attempt_id=attempt_id,
        )

    assert type(exc_info.value) is TransitionRejected
    assert exc_info.value.alert_type == f"{FRESH_SELF_TEST_ALERT_PREFIX}:{TASK_ID}"
    assert _count_kind(group.ledger_path, KIND_TASK_REPORTED_COMPLETED) == 0
    assert _count_kind(group.ledger_path, KIND_TRANSITION_REJECTED) == 1


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    *,
    attempt_id: str,
) -> None:
    orchestrator.engine.register_task(
        TaskRef(id=TASK_ID, title="INV-7 task", claimed_paths=[CHANGED_FILE]),
        WORKFLOW_ID,
    )
    orchestrator.engine.register_batch("b-inv7", [TASK_ID])
    orchestrator.engine.approve_batch(
        "b-inv7",
        [
            {
                "task_id": TASK_ID,
                "agent_id": AGENT_ID,
                "claimed_paths": [CHANGED_FILE],
                "attempt_id": attempt_id,
            }
        ],
    )
    orchestrator.engine.report_worker_started(TASK_ID, AGENT_ID)


def _passing_verification() -> VerificationResult:
    return VerificationResult(
        verification_id="ver-inv7",
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        overall_outcome="passed",
        checks=[],
        summary="ok",
    )


def _count_kind(ledger_path: Path, kind: str) -> int:
    return len(_events_of_kind(ledger_path, kind))


def _events_of_kind(ledger_path: Path, kind: str) -> list[dict[str, object]]:
    return [
        json.loads(raw)
        for raw in ledger_path.read_text(encoding="utf-8", errors="strict").splitlines()
        if raw.strip() and json.loads(raw).get("kind") == kind
    ]
