from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest
import yaml

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationCheck, VerificationResult
from cccc.daemon.foreman.verification_gate import (
    INPUT_ROBUSTNESS_CHECK_NAME,
    process_completed_event,
)
from cccc.kernel.workflow_state import TaskState, WorkflowTaskStatus


class _Engine:
    def __init__(self, project_root: Path, plan_path: Optional[Path] = None) -> None:
        self.project_root = project_root
        self.plan_path = plan_path
        self.recorded_verification: Optional[VerificationResult] = None
        self.failures: list[dict[str, Any]] = []
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

    def record_verification_failure(self, task_id: str, **kwargs: Any) -> None:
        self.failures.append({"task_id": task_id, **kwargs})

    def get_task(self, task_id: str) -> Any:
        return SimpleNamespace(task=None, workflow_id="wf-1")

    def get_workflow_meta(self, workflow_id: str) -> Any:
        return SimpleNamespace(plan_path=str(self.plan_path or ""))


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


@pytest.mark.parametrize(
    ("content", "expected_type"),
    [
        ("value = eval(user_input)\n", "eval_call"),
        ("exec(user_input)\n", "exec_call"),
        ("try:\n    work()\nexcept:\n    recover()\n", "bare_except"),
        ("app.run(host='0.0.0.0', debug=True)\n", "app_run_debug"),
        ("api_key = \"dev-secret\"\n", "hardcoded_secret"),
    ],
)
def test_security_lint_hit_blocks_challenge_completion(
    tmp_path: Path,
    content: str,
    expected_type: str,
) -> None:
    _write(tmp_path, "src/app.py", content)

    engine, callbacks, result = _run_completed_event(tmp_path, "src/app.py")

    verification = _recorded_verification(engine)
    assert result["verification_outcome"] == "failed"
    assert verification.overall_outcome == "failed"
    assert not callbacks["completed"]
    assert callbacks["failed"]
    assert _single_security_failure_hit(engine, expected_type)["type"] == expected_type
    assert not [
        w for w in engine.warnings if w["warning_type"] == "security_lint"
    ]


def test_security_lint_whitelists_test_files(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_app.py", "value = eval(user_input)\n")

    engine, callbacks, result = _run_completed_event(tmp_path, "tests/test_app.py")

    verification = _recorded_verification(engine)
    assert result["verification_outcome"] == "passed"
    assert verification.overall_outcome == "passed"
    assert callbacks["completed"]
    assert not callbacks["failed"]
    assert engine.failures == []
    assert engine.warnings == []


def test_critical_flow_input_robustness_gap_blocks_completion(tmp_path: Path) -> None:
    _write(tmp_path, "src/search.py", "def search(query):\n    return []\n")
    _write(tmp_path, "tests/test_search.py", "def test_search():\n    assert search('ok') == []\n")
    plan_path = _write_plan(tmp_path)

    engine, callbacks, result = _run_completed_event(tmp_path, "src/search.py", plan_path)

    verification = _recorded_verification(engine)
    robustness_check = _verification_check(verification, INPUT_ROBUSTNESS_CHECK_NAME)
    assert result["verification_outcome"] == "failed"
    assert verification.overall_outcome == "failed"
    assert not callbacks["completed"]
    assert callbacks["failed"]
    assert robustness_check.details["critical_flows_with_input"] == ["search_flow"]
    assert engine.failures[0]["failure_type"] == "input_robustness_gap"
    assert not [
        w for w in engine.warnings if w["warning_type"] == "input_robustness_gap"
    ]


def _run_completed_event(
    project_root: Path,
    changed_path: str,
    plan_path: Optional[Path] = None,
) -> tuple[_Engine, dict[str, list[dict[str, Any]]], dict[str, Any]]:
    engine = _Engine(project_root, plan_path)
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
        id="T26",
        title="Extended security lint",
        goal_behavior="Extend security lint warnings and input robustness blocking.",
        acceptance_criteria="Security warnings are visible and robustness gaps block critical flows.",
        claimed_paths=[changed_path],
        verification_mode="challenge",
    )


def _payload(changed_path: str) -> dict[str, Any]:
    return {
        "agent_id": "agent-1",
        "changed_files": [changed_path],
        "duration_seconds": 1,
        "evidence_summary": "Implemented T26 security lint extension.",
        "idempotency_key": "complete-T26",
    }


def _write_plan(tmp_path: Path) -> Path:
    plan_path = tmp_path / "workflow-plan.yaml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "critical_flows": [
                    {"id": "search_flow", "description": "search query endpoint"},
                ],
                "tasks": [
                    {
                        "id": "T26",
                        "verification": {
                            "level": "unit",
                            "checks": [
                                {
                                    "name": "search endpoint tests",
                                    "command": "python -m pytest tests/test_search.py -v",
                                },
                            ],
                        },
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return plan_path


def _write(project_root: Path, relative_path: str, content: str) -> None:
    target = project_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _single_security_failure_hit(engine: _Engine, expected_type: str) -> dict[str, Any]:
    security_failures = [
        f for f in engine.failures if f["failure_type"] == "security_lint"
    ]
    assert len(security_failures) == 1
    hits = security_failures[0]["evidence"]["hits"]
    return next(hit for hit in hits if hit["type"] == expected_type)


def _recorded_verification(engine: _Engine) -> VerificationResult:
    assert engine.recorded_verification is not None
    return engine.recorded_verification


def _verification_check(
    verification: VerificationResult,
    check_name: str,
) -> VerificationCheck:
    return next(check for check in verification.checks if check.name == check_name)


def _unexpected_auto_start(**kwargs: Any) -> TaskState:
    raise AssertionError("running task should not need auto-start")
