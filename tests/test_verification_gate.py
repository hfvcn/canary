from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.verification_gate import (
    SHALLOW_CHECK_DEPTH_NAME,
    SHALLOW_CHECK_FAILURE,
    process_completed_event,
)
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus


TASK_ID = "T5"
WORKFLOW_ID = "wf-shallow-check"
AGENT_ID = "worker-1"


class _Engine:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.recorded: list[VerificationResult] = []
        self.warnings: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []

    def report_worker_completion(
        self,
        task_id: str,
        evidence: dict[str, Any],
        *,
        hook_ctx: dict[str, Any],
        attempt_id: str,
    ) -> None:
        self.completion = {
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
        self.recorded.append(verification)

    def record_verification_warning(self, task_id: str, **kwargs: Any) -> None:
        self.warnings.append({"task_id": task_id, **kwargs})

    def record_verification_failure(self, task_id: str, **kwargs: Any) -> None:
        self.failures.append({"task_id": task_id, **kwargs})


class _StaticRalphService:
    def __init__(self, verification: VerificationResult) -> None:
        self.verification = verification
        self.calls = 0

    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        self.calls += 1
        return self.verification


class _UnexpectedRalphService:
    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: TaskRef,
    ) -> VerificationResult:
        raise AssertionError("verify_completion should not be called")


def test_shallow_check_all_import_fails(tmp_path: Path) -> None:
    task = _task_ref(
        [
            {"name": "import smoke", "command": "python -c \"import cccc\""},
            {"name": "compile check", "command": "python -m py_compile src/feature.py"},
        ]
    )
    service = _StaticRalphService(_verification("passed", "worker verification passed"))

    engine, callbacks, result = _run_completed_event(tmp_path, task, service)

    verification = engine.recorded[-1]
    shallow_check = _verification_check(verification, SHALLOW_CHECK_DEPTH_NAME)
    assert service.calls == 1
    assert result["verification_outcome"] == "failed"
    assert verification.overall_outcome == "failed"
    assert shallow_check.message == SHALLOW_CHECK_FAILURE
    assert callbacks["completed"] == []
    assert len(callbacks["failed"]) == 1


def test_shallow_check_with_behavioral_passes(tmp_path: Path) -> None:
    task = _task_ref(
        [
            {"name": "compile check", "command": "python -m py_compile src/feature.py"},
            {"name": "behavior test", "command": "python -m pytest tests/test_feature.py -q"},
        ]
    )
    service = _StaticRalphService(_verification("passed", "worker verification passed"))

    engine, callbacks, result = _run_completed_event(tmp_path, task, service)

    verification = engine.recorded[-1]
    assert result["verification_outcome"] == "passed"
    assert verification.overall_outcome == "passed"
    assert _verification_check_names(verification) == []
    assert len(callbacks["completed"]) == 1
    assert callbacks["failed"] == []


def test_shallow_check_no_checks_skips(tmp_path: Path) -> None:
    task = _task_ref([])
    service = _StaticRalphService(_verification("passed", "worker verification passed"))

    engine, callbacks, result = _run_completed_event(tmp_path, task, service)

    verification = engine.recorded[-1]
    assert result["verification_outcome"] == "passed"
    assert verification.overall_outcome == "passed"
    assert _verification_check_names(verification) == []
    assert len(callbacks["completed"]) == 1
    assert callbacks["failed"] == []


def test_shallow_check_force_passed_unchanged(tmp_path: Path) -> None:
    task = _task_ref(
        [
            {"name": "import smoke", "command": "python -c \"import cccc\""},
            {"name": "compile check", "command": "python -m py_compile src/feature.py"},
        ]
    )

    engine, callbacks, result = _run_completed_event(
        tmp_path,
        task,
        _UnexpectedRalphService(),
        hook_ctx={"force_complete": True},
    )

    verification = engine.recorded[-1]
    assert result["verification_outcome"] == "force_passed"
    assert verification.overall_outcome == "force_passed"
    assert _verification_check_names(verification) == []
    assert len(callbacks["completed"]) == 1
    assert callbacks["failed"] == []


def _run_completed_event(
    project_root: Path,
    task: TaskRef,
    ralph_service: Any,
    *,
    hook_ctx: dict[str, Any] | None = None,
) -> tuple[_Engine, dict[str, list[dict[str, Any]]], dict[str, Any]]:
    engine = _Engine(project_root)
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
        state=_state(task),
        payload=_payload(),
        agent_id=AGENT_ID,
        hook_ctx=hook_ctx or {},
        result={"accepted": True},
        extract_evidence_summary_fn=lambda payload: str(payload.get("evidence_summary") or ""),
        on_task_completed_fn=lambda **kwargs: callbacks["completed"].append(kwargs),
        on_task_failed_fn=lambda **kwargs: callbacks["failed"].append(kwargs),
        notify_verification_fn=lambda **kwargs: callbacks["notifications"].append(kwargs),
        save_context_fn=lambda **kwargs: callbacks["contexts"].append(kwargs),
        auto_start_fn=_unexpected_auto_start,
    )
    return engine, callbacks, result


def _state(task: TaskRef) -> TaskState:
    return TaskState(
        task=task,
        workflow_id=WORKFLOW_ID,
        status=WorkflowTaskStatus.RUNNING,
        agent_id=AGENT_ID,
    )


def _task_ref(checks: list[dict[str, Any]]) -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Shallow verification gate",
        claimed_paths=["src/cccc/daemon/foreman/verification_gate.py"],
        verification_mode="ralph",
        verification={"level": "unit", "checks": checks},
    )


def _payload() -> dict[str, Any]:
    return {
        "agent_id": AGENT_ID,
        "changed_files": [],
        "duration_seconds": 1,
        "evidence_summary": "worker verification passed",
        "idempotency_key": "complete-T5",
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


def _verification_check(
    verification: VerificationResult,
    name: str,
) -> Any:
    for check in verification.checks:
        if check.name == name:
            return check
    raise AssertionError(f"missing verification check: {name}")


def _verification_check_names(verification: VerificationResult) -> list[str]:
    return [check.name for check in verification.checks]


def _unexpected_auto_start(**kwargs: Any) -> Any:
    raise AssertionError(f"unexpected auto_start call: {kwargs}")
