from __future__ import annotations

from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.prompt_builder import extract_evidence_summary
from cccc.daemon.foreman.verification_gate import (
    AEGIS_EVIDENCE_CHECK_NAME,
    AEGIS_EVIDENCE_MISSING_ERROR,
    AEGIS_FIX_ROOT_CAUSE_WARNING,
    process_completed_event,
)
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus


class _Engine:
    def __init__(self) -> None:
        self.recorded_verification: VerificationResult | None = None
        self.worker_completion: dict[str, Any] = {}

    def report_worker_completion(
        self,
        task_id: str,
        evidence: dict[str, Any],
        *,
        hook_ctx: dict[str, Any],
        attempt_id: str,
    ) -> None:
        self.worker_completion = {
            "task_id": task_id,
            "evidence": evidence,
            "hook_ctx": hook_ctx,
            "attempt_id": attempt_id,
        }

    def record_verification_result(
        self,
        task_id: str,
        verification: VerificationResult,
        *,
        hook_ctx: dict[str, Any],
    ) -> None:
        self.recorded_verification = verification

    def record_verification_warning(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("unexpected verification warning")


class _PassingRalphService:
    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=f"ver-{task_id}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="worker verification passed",
        )


def test_empty_evidence_challenge_fails() -> None:
    verification, callbacks = _run_completed_event(
        verification_mode="challenge",
        evidence_summary="",
        aegis={"intent": "fix"},
    )

    assert verification.overall_outcome == "failed"
    assert callbacks["failed"]
    assert not callbacks["completed"]
    gate_check = verification.checks[-1]
    assert gate_check.name == AEGIS_EVIDENCE_CHECK_NAME
    assert gate_check.outcome == "failed"
    assert AEGIS_EVIDENCE_MISSING_ERROR in gate_check.details["errors"]


def test_empty_evidence_ralph_passes_with_warning() -> None:
    verification, callbacks = _run_completed_event(
        verification_mode="ralph",
        evidence_summary="completed",
        aegis={"intent": "fix"},
    )

    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert not callbacks["failed"]
    assert AEGIS_EVIDENCE_MISSING_ERROR in verification.warnings


def test_good_evidence_passes() -> None:
    verification, callbacks = _run_completed_event(
        verification_mode="challenge",
        evidence_summary="Root cause was stale task metadata; patched it and tests pass. All paths covered.",
        aegis={"intent": "fix"},
    )

    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert verification.warnings == []
    assert [check.name for check in verification.checks] == []


def test_no_aegis_data_has_no_effect() -> None:
    verification, callbacks = _run_completed_event(
        verification_mode="challenge",
        evidence_summary="",
        aegis=None,
    )

    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert verification.warnings == []
    assert verification.checks == []


def test_fix_without_root_cause_warns_without_failing() -> None:
    verification, callbacks = _run_completed_event(
        verification_mode="challenge",
        evidence_summary="Patched the completion path and added a regression test.",
        aegis={"intent": "fix"},
    )

    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert AEGIS_FIX_ROOT_CAUSE_WARNING in verification.warnings


def _run_completed_event(
    *,
    verification_mode: str,
    evidence_summary: str,
    aegis: dict[str, Any] | None,
) -> tuple[VerificationResult, dict[str, list[dict[str, Any]]]]:
    engine = _Engine()
    callbacks: dict[str, list[dict[str, Any]]] = {
        "completed": [],
        "failed": [],
        "notifications": [],
        "contexts": [],
    }
    task = _task_ref(verification_mode=verification_mode, aegis=aegis)
    state = TaskState(
        task=task,
        workflow_id="wf-1",
        status=WorkflowTaskStatus.RUNNING,
        agent_id="agent-1",
    )

    process_completed_event(
        engine=engine,
        ralph_service=_PassingRalphService(),
        task_id=task.id,
        state=state,
        payload=_payload(evidence_summary),
        agent_id="agent-1",
        hook_ctx={},
        result={"accepted": True},
        extract_evidence_summary_fn=extract_evidence_summary,
        on_task_completed_fn=lambda **kwargs: callbacks["completed"].append(kwargs),
        on_task_failed_fn=lambda **kwargs: callbacks["failed"].append(kwargs),
        notify_verification_fn=lambda **kwargs: callbacks["notifications"].append(kwargs),
        save_context_fn=lambda **kwargs: callbacks["contexts"].append(kwargs),
        auto_start_fn=_unexpected_auto_start,
    )

    assert engine.recorded_verification is not None
    return engine.recorded_verification, callbacks


def _task_ref(*, verification_mode: str, aegis: dict[str, Any] | None) -> TaskRef:
    return TaskRef(
        id="T4",
        title="Fix completion evidence gate",
        goal_behavior="Fix evidence handling after worker completion.",
        acceptance_criteria="Evidence gate enforces meaningful completion proof.",
        claimed_paths=["src/cccc/daemon/foreman/verification_gate.py"],
        verification_mode=verification_mode,
        aegis=aegis,
    )


def _payload(evidence_summary: str) -> dict[str, Any]:
    return {
        "agent_id": "agent-1",
        "changed_files": ["src/cccc/daemon/foreman/verification_gate.py"],
        "duration_seconds": 1,
        "evidence_summary": evidence_summary,
        "idempotency_key": "complete-T4",
    }


def _unexpected_auto_start(**kwargs: Any) -> TaskState:
    raise AssertionError("running task should not need auto-start")
