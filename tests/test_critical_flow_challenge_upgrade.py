from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.kernel.workflow_state_types import WorkflowMeta
from cccc.ralph.models import CriticalFlow, Plan, TaskSpec
from cccc.ralph.validator import validate


class _WorkflowEngineStub:
    def __init__(self, plan_path: Path) -> None:
        self._meta = WorkflowMeta(workflow_id="wf-1", plan_path=str(plan_path))

    def get_workflow_meta(self, workflow_id: str) -> WorkflowMeta:
        assert workflow_id == "wf-1"
        return self._meta


def _write_plan(tmp_path: Path, entrypoint: str) -> Path:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "tasks": [],
                "critical_flows": [{"id": "flow-login", "entrypoints": [entrypoint]}],
            }
        ),
        encoding="utf-8",
    )
    return plan_path


def _service(tmp_path: Path, entrypoint: str) -> RalphService:
    plan_path = _write_plan(tmp_path, entrypoint)
    return RalphService(
        project_root=tmp_path,
        group_id="test-group",
        workflow_engine=_WorkflowEngineStub(plan_path),
    )


def _task_ref(*, claimed_paths: list[str], mode: str = "ralph") -> TaskRef:
    return TaskRef(
        id="T1",
        title="Critical flow task",
        claimed_paths=claimed_paths,
        verification_mode=mode,
    )


def _result(outcome: str, summary: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{outcome}",
        workflow_id="wf-1",
        task_id="T1",
        overall_outcome=outcome,
        checks=[],
        summary=summary,
    )


def test_critical_flow_task_upgrades_ralph_mode_to_challenge(tmp_path: Path) -> None:
    service = _service(tmp_path, "src/auth/login.py")
    task_ref = _task_ref(claimed_paths=["src/auth/login.py"], mode="ralph")
    challenge_result = _result("passed", "challenge route")

    with (
        patch.object(service, "_verify_completion_with_challenge", return_value=challenge_result) as challenge,
        patch.object(service, "_verify_completion_with_worker") as worker,
    ):
        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

    assert result == challenge_result
    challenge.assert_called_once()
    worker.assert_not_called()


def test_non_critical_flow_task_stays_on_ralph_mode(tmp_path: Path) -> None:
    service = _service(tmp_path, "src/auth/login.py")
    task_ref = _task_ref(claimed_paths=["src/profile/view.py"], mode="ralph")
    worker_result = _result("passed", "worker route")

    with (
        patch.object(service, "_verify_completion_with_worker", return_value=worker_result) as worker,
        patch.object(service, "_verify_completion_with_challenge") as challenge,
    ):
        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

    assert result == worker_result
    worker.assert_called_once()
    challenge.assert_not_called()


def test_critical_flow_task_keeps_explicit_challenge_mode(tmp_path: Path) -> None:
    service = _service(tmp_path, "src/auth/login.py")
    task_ref = _task_ref(claimed_paths=["src/auth/login.py"], mode="challenge")
    challenge_result = _result("passed", "explicit challenge route")

    with (
        patch.object(service, "_verify_completion_with_challenge", return_value=challenge_result) as challenge,
        patch.object(service, "_verify_completion_with_worker") as worker,
    ):
        result = service.verify_completion("T1", [], workflow_id="wf-1", task_ref=task_ref)

    assert result == challenge_result
    challenge.assert_called_once()
    worker.assert_not_called()


def test_should_upgrade_ralph_task_touching_critical_flow(tmp_path: Path) -> None:
    service = _service(tmp_path, "src/auth/login.py")
    task_ref = _task_ref(claimed_paths=["src/auth/login.py"], mode="ralph")

    assert service._should_upgrade_to_challenge(task_ref, "wf-1") is True


def test_should_not_upgrade_ralph_task_outside_critical_flow(tmp_path: Path) -> None:
    service = _service(tmp_path, "src/auth/login.py")
    task_ref = _task_ref(claimed_paths=["src/profile/view.py"], mode="ralph")

    assert service._should_upgrade_to_challenge(task_ref, "wf-1") is False


def test_should_not_upgrade_explicit_challenge_task(tmp_path: Path) -> None:
    service = _service(tmp_path, "src/auth/login.py")
    task_ref = _task_ref(claimed_paths=["src/auth/login.py"], mode="challenge")

    assert service._should_upgrade_to_challenge(task_ref, "wf-1") is False


def test_validate_warns_when_critical_flow_task_uses_ralph_mode() -> None:
    plan = Plan(
        tasks=[
            TaskSpec(
                id="T1",
                claimed_paths=["src/auth/login.py"],
                verification_mode="ralph",
            )
        ],
        critical_flows=[CriticalFlow(id="flow-login", entrypoints=["src/auth/login.py"])],
    )

    report = validate(plan)
    issues = [
        issue for issue in report.warnings
        if issue.code == "W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION"
    ]

    assert len(issues) == 1
    assert issues[0].task_ids == ["T1"]
    assert issues[0].evidence["critical_flows"] == ["flow-login"]


def test_validate_skips_warning_for_non_critical_flow_task() -> None:
    plan = Plan(
        tasks=[
            TaskSpec(
                id="T1",
                claimed_paths=["src/profile/view.py"],
                verification_mode="ralph",
            )
        ],
        critical_flows=[CriticalFlow(id="flow-login", entrypoints=["src/auth/login.py"])],
    )

    report = validate(plan)
    issues = [
        issue for issue in report.warnings
        if issue.code == "W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION"
    ]

    assert issues == []
