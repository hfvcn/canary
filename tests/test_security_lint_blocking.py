from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.verification_gate import (
    SECURITY_LINT_CHECK_NAME,
    process_completed_event,
)
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus


class _Engine:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.recorded_verification: VerificationResult | None = None
        self.warnings: list[dict[str, Any]] = []

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

    def record_verification_warning(self, task_id: str, **kwargs: Any) -> None:
        self.warnings.append({"task_id": task_id, **kwargs})


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


def test_source_file_with_debug_true_fails_verification(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py", "app.run(debug=True)\n")

    engine, callbacks, result = _run_completed_event(tmp_path, "src/app.py")

    verification = _recorded_verification(engine)
    assert result["verification_outcome"] == "failed"
    assert verification.overall_outcome == "failed"
    assert not callbacks["completed"]
    assert callbacks["failed"]
    assert _security_check(verification).details["hits"][0]["file"] == "src/app.py"
    assert engine.warnings[0]["warning_type"] == "security_lint"


def test_test_file_with_debug_true_does_not_affect_verification(tmp_path: Path) -> None:
    _write(tmp_path, "tests/app.py", "app.run(debug=True)\n")

    engine, callbacks, result = _run_completed_event(tmp_path, "tests/app.py")

    verification = _recorded_verification(engine)
    assert result["verification_outcome"] == "passed"
    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert not callbacks["failed"]
    assert engine.warnings == []


def test_source_file_without_debug_true_passes_normally(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py", "app.run()\n")

    engine, callbacks, result = _run_completed_event(tmp_path, "src/app.py")

    verification = _recorded_verification(engine)
    assert result["verification_outcome"] == "passed"
    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert not callbacks["failed"]
    assert engine.warnings == []


def _run_completed_event(
    project_root: Path,
    changed_path: str,
) -> tuple[_Engine, dict[str, list[dict[str, Any]]], dict[str, Any]]:
    engine = _Engine(project_root)
    callbacks: dict[str, list[dict[str, Any]]] = {
        "completed": [],
        "failed": [],
        "notifications": [],
        "contexts": [],
    }
    task = _task_ref(changed_path)
    state = TaskState(
        task=task,
        workflow_id="wf-1",
        status=WorkflowTaskStatus.RUNNING,
        agent_id="agent-1",
    )
    result = {"accepted": True}

    process_completed_event(
        engine=engine,
        ralph_service=_PassingRalphService(),
        task_id=task.id,
        state=state,
        payload=_payload(changed_path),
        agent_id="agent-1",
        hook_ctx={},
        result=result,
        extract_evidence_summary_fn=lambda payload: str(payload.get("evidence_summary") or ""),
        on_task_completed_fn=lambda **kwargs: callbacks["completed"].append(kwargs),
        on_task_failed_fn=lambda **kwargs: callbacks["failed"].append(kwargs),
        notify_verification_fn=lambda **kwargs: callbacks["notifications"].append(kwargs),
        save_context_fn=lambda **kwargs: callbacks["contexts"].append(kwargs),
        auto_start_fn=_unexpected_auto_start,
    )
    return engine, callbacks, result


def _task_ref(changed_path: str) -> TaskRef:
    return TaskRef(
        id="T21",
        title="Verify gate debug blocking",
        goal_behavior="Block debug=True before task completion.",
        acceptance_criteria="debug=True in non-test source files fails verification.",
        claimed_paths=[changed_path],
        verification_mode="ralph",
    )


def _payload(changed_path: str) -> dict[str, Any]:
    return {
        "agent_id": "agent-1",
        "changed_files": [changed_path],
        "duration_seconds": 1,
        "evidence_summary": "Implemented debug gate before completion.",
        "idempotency_key": "complete-T21",
    }


def _write(project_root: Path, relative_path: str, content: str) -> None:
    target = project_root / relative_path
    target.parent.mkdir(parents=True)
    target.write_text(content, encoding="utf-8")


def _recorded_verification(engine: _Engine) -> VerificationResult:
    assert engine.recorded_verification is not None
    return engine.recorded_verification


def _security_check(verification: VerificationResult) -> Any:
    return next(check for check in verification.checks if check.name == SECURITY_LINT_CHECK_NAME)


def _unexpected_auto_start(**kwargs: Any) -> TaskState:
    raise AssertionError("running task should not need auto-start")
