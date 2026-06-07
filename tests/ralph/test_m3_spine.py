from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.contracts.v1.ralph_ipc import VerificationResult
from cccc.daemon.foreman.verification_gate import process_completed_event
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus
from cccc.ralph.module_acceptance import (
    W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT,
    verify_task_modules,
)
from cccc.ralph.plan_io import load_plan
from cccc.ralph.validation_rules import (
    _check_module_structure,
    _check_task_granularity,
    get_all_rules,
)
from cccc.ralph.models import Plan


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "m3_pilot"
GOOD_PLAN_PATH = FIXTURE_ROOT / "plan.yaml"
BAD_PLAN_PATH = FIXTURE_ROOT / "plan_bad.yaml"
TASK_ID = "T-gate"
WORKFLOW_ID = "wf-m3-spine"
AGENT_ID = "worker-m3"
GRANULARITY_CODE = "W_TASK_GRANULARITY_COMPRESSION"
MODULE_CHECK_NAME = "module_acceptance"


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


class _PassingRalphService:
    def verify_completion(
        self,
        task_id: str,
        changed_files: list[str],
        *,
        workflow_id: str,
        task_ref: Any,
    ) -> VerificationResult:
        return VerificationResult(
            verification_id=f"ver-{task_id}",
            workflow_id=workflow_id,
            task_id=task_id,
            overall_outcome="passed",
            checks=[],
            summary="worker verification passed",
        )


def test_module_rules_are_registered_and_importable() -> None:
    rules = get_all_rules()

    assert _check_module_structure in rules
    assert _check_task_granularity in rules


def test_module_structure_flips_between_good_and_bad_pilot_plans() -> None:
    good_plan = load_plan(GOOD_PLAN_PATH)
    bad_plan = load_plan(BAD_PLAN_PATH)

    assert _check_module_structure(good_plan) == []
    assert {issue.code for issue in _check_module_structure(bad_plan)} & {
        "W_MODULE_NO_BLACKBOX_EVIDENCE",
        "W_MODULE_INTEGRATION_CONTRACT_UNRESOLVED",
    }


def test_verify_task_modules_passes_for_good_pilot_fixture() -> None:
    plan = load_plan(GOOD_PLAN_PATH)

    result = verify_task_modules(plan.tasks[0], workspace_root=FIXTURE_ROOT)

    assert result.overall_pass is True
    assert [module.status for module in result.module_results] == ["pass", "pass"]


def test_verification_gate_blocks_task_when_module_acceptance_fails() -> None:
    plan = load_plan(BAD_PLAN_PATH)

    engine, callbacks, result = _run_completed_event(
        project_root=FIXTURE_ROOT,
        task_ref=plan.tasks[0].to_task_ref(),
    )

    verification = engine.recorded[-1]
    assert result["verification_outcome"] == "failed"
    assert verification.overall_outcome == "failed"
    assert any(check.name == MODULE_CHECK_NAME for check in verification.checks)
    assert callbacks["completed"] == []
    assert len(callbacks["failed"]) == 1
    assert engine.failures[0]["failure_type"] == MODULE_CHECK_NAME


def test_verification_gate_records_missing_workspace_context_without_silent_pass() -> None:
    plan = load_plan(GOOD_PLAN_PATH)
    missing_root = FIXTURE_ROOT / "missing-workspace-root"

    engine, callbacks, result = _run_completed_event(
        project_root=missing_root,
        task_ref=plan.tasks[0].to_task_ref(),
    )

    assert result["verification_outcome"] == "passed"
    assert engine.recorded[-1].overall_outcome == "passed"
    assert len(callbacks["completed"]) == 1
    assert callbacks["failed"] == []
    assert engine.warnings[0]["warning_type"] == W_MODULE_ACCEPTANCE_SKIPPED_MISSING_CONTEXT


def test_task_granularity_rule_is_reachable_and_flips() -> None:
    compressed = Plan.model_validate({
        "tasks": [
            {
                "id": "T-compressed",
                "addresses": ["DG-33", "FL-73", "RV-22", "RA-11"],
                "claimed_paths": [
                    "src/cccc/ralph/core.py",
                    "src/cccc/daemon/foreman/agent_pool.py",
                    "src/cccc/contracts/v1/ralph_ipc.py",
                ],
                "goal_behavior": (
                    "A. Update the validator path.\n"
                    "B. Expand daemon orchestration handling.\n"
                    "C. Adjust contracts surface and schema.\n"
                    "D. Align verification expectations."
                ),
                "acceptance_criteria": "granularity rule should trigger",
            }
        ]
    })
    focused = Plan.model_validate({
        "tasks": [
            {
                "id": "T-focused",
                "addresses": ["DG-33", "FL-73"],
                "claimed_paths": [
                    "src/cccc/ralph/core.py",
                    "src/cccc/ralph/models.py",
                ],
                "goal_behavior": "A. Tighten one validator path.\nB. Update its local tests.",
                "acceptance_criteria": "granularity rule should stay silent",
            }
        ]
    })

    assert any(issue.code == GRANULARITY_CODE for issue in _check_task_granularity(compressed))
    assert _check_task_granularity(focused) == []


def _run_completed_event(
    *,
    project_root: Path,
    task_ref: Any,
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
        ralph_service=_PassingRalphService(),
        task_id=TASK_ID,
        state=_state(task_ref),
        payload=_payload(),
        agent_id=AGENT_ID,
        hook_ctx={},
        result={"accepted": True},
        extract_evidence_summary_fn=lambda payload: str(payload.get("evidence_summary") or ""),
        on_task_completed_fn=lambda **kwargs: callbacks["completed"].append(kwargs),
        on_task_failed_fn=lambda **kwargs: callbacks["failed"].append(kwargs),
        notify_verification_fn=lambda **kwargs: callbacks["notifications"].append(kwargs),
        save_context_fn=lambda **kwargs: callbacks["contexts"].append(kwargs),
        auto_start_fn=_unexpected_auto_start,
    )
    return engine, callbacks, result


def _state(task_ref: Any) -> TaskState:
    return TaskState(
        task=task_ref.model_copy(update={"id": TASK_ID}),
        workflow_id=WORKFLOW_ID,
        status=WorkflowTaskStatus.RUNNING,
        agent_id=AGENT_ID,
    )


def _payload() -> dict[str, Any]:
    return {
        "agent_id": AGENT_ID,
        "changed_files": [],
        "duration_seconds": 1,
        "evidence_summary": "worker verification passed",
        "idempotency_key": "complete-m3-spine",
    }


def _unexpected_auto_start(**kwargs: Any) -> Any:
    raise AssertionError(f"unexpected auto_start call: {kwargs}")
