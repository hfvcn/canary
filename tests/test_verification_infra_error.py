from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.daemon.foreman.verification_gate import (
    VERIFICATION_INFRA_ESCALATED_WARNING,
    process_completed_event,
)
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus


TASK_ID = "T22"
WORKFLOW_ID = "wf-infra-error"
AGENT_ID = "worker-1"


class _Engine:
    def __init__(self) -> None:
        self.recorded: list[VerificationResult] = []
        self.completions: list[dict[str, Any]] = []

    def report_worker_completion(
        self,
        task_id: str,
        evidence: dict[str, Any],
        *,
        hook_ctx: dict[str, Any],
        attempt_id: str,
    ) -> None:
        self.completions.append(
            {"task_id": task_id, "evidence": evidence, "attempt_id": attempt_id}
        )

    def record_verification_result(
        self,
        task_id: str,
        verification: VerificationResult,
        *,
        hook_ctx: dict[str, Any],
    ) -> None:
        self.recorded.append(verification)

    def record_verification_warning(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("unexpected verification warning")


class _SequenceRalphService:
    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls = 0

    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        result = self._results[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


def test_file_not_found_in_verify_records_infra_error_without_failure_retry() -> None:
    service = _SequenceRalphService(
        [FileNotFoundError("verifier missing"), _verification("passed", "ok")]
    )

    engine, callbacks, result = _run_completed_event(service)

    assert service.calls == 2
    assert result["verification_outcome"] == "passed"
    assert result["verification_infra_retries"] == 1
    assert [item.overall_outcome for item in engine.recorded] == ["infra_error", "passed"]
    assert callbacks["failed"] == []
    assert len(callbacks["completed"]) == 1


def test_ralph_service_missing_verifier_command_returns_infra_error(tmp_path: Path) -> None:
    task = TaskRef(
        id=TASK_ID,
        verification=VerificationSpec(
            checks=[
                {
                    "name": "missing-verifier",
                    "command": "definitely-missing-verifier-t22",
                    "required": True,
                    "expected_exit_code": 0,
                }
            ]
        ),
    )

    result = RalphService(tmp_path, group_id="test-group").verify_completion(
        TASK_ID,
        [],
        workflow_id=WORKFLOW_ID,
        task_ref=task,
    )

    assert result.overall_outcome == "failed"
    assert any("failed" in check.outcome for check in result.checks)
    assert "failed to start" in result.summary or result.summary


def test_normal_verification_failure_still_fails() -> None:
    service = _SequenceRalphService([_verification("failed", "assertion failed")])

    engine, callbacks, result = _run_completed_event(service)

    assert service.calls == 1
    assert result["verification_outcome"] == "failed"
    assert "verification_infra_retries" not in result
    assert [item.overall_outcome for item in engine.recorded] == ["failed"]
    assert callbacks["completed"] == []
    assert len(callbacks["failed"]) == 1


def test_infra_error_after_two_retries_escalates_to_failed() -> None:
    service = _SequenceRalphService(
        [FileNotFoundError("verifier missing") for _ in range(3)]
    )

    engine, callbacks, result = _run_completed_event(service)

    assert service.calls == 3
    assert result["verification_outcome"] == "failed"
    assert result["verification_infra_retries"] == 2
    assert [item.overall_outcome for item in engine.recorded] == [
        "infra_error",
        "infra_error",
        "failed",
    ]
    assert VERIFICATION_INFRA_ESCALATED_WARNING in engine.recorded[-1].warnings
    assert callbacks["completed"] == []
    assert len(callbacks["failed"]) == 1


def _run_completed_event(
    ralph_service: _SequenceRalphService,
) -> tuple[_Engine, dict[str, list[dict[str, Any]]], dict[str, Any]]:
    engine = _Engine()
    callbacks: dict[str, list[dict[str, Any]]] = {
        "completed": [],
        "failed": [],
        "notifications": [],
        "contexts": [],
    }
    result = process_completed_event(
        engine=engine,
        ralph_service=ralph_service,
        task_id=TASK_ID,
        state=_state(),
        payload=_payload(),
        agent_id=AGENT_ID,
        hook_ctx={},
        result={"accepted": True},
        extract_evidence_summary_fn=lambda payload: "verified",
        on_task_completed_fn=lambda **kwargs: callbacks["completed"].append(kwargs),
        on_task_failed_fn=lambda **kwargs: callbacks["failed"].append(kwargs),
        notify_verification_fn=lambda **kwargs: callbacks["notifications"].append(kwargs),
        save_context_fn=lambda **kwargs: callbacks["contexts"].append(kwargs),
        auto_start_fn=_unexpected_auto_start,
    )
    return engine, callbacks, result


def _state() -> TaskState:
    return TaskState(
        task=_task_ref(),
        workflow_id=WORKFLOW_ID,
        status=WorkflowTaskStatus.RUNNING,
        agent_id=AGENT_ID,
    )


def _task_ref() -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Verification infra error",
        claimed_paths=["src/cccc/daemon/foreman/verification_gate.py"],
        verification_mode="ralph",
    )


def _payload() -> dict[str, Any]:
    return {
        "agent_id": AGENT_ID,
        "changed_files": [],
        "duration_seconds": 1,
        "evidence_summary": "verified",
        "idempotency_key": "complete-T22",
    }


def _verification(outcome: str, summary: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{outcome}",
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        overall_outcome=outcome,
        checks=[],
        summary=summary,
    )


def _unexpected_auto_start(**kwargs: Any) -> TaskState:
    raise AssertionError("running task should not need auto-start")
