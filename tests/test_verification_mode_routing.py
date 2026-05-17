from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService


WORKFLOW_ID = "wf-mode-routing"
TASK_ID = "T-route"
SHELL_CHECK_NAME = "shell-check"


def _service(tmp_path: Path) -> RalphService:
    return RalphService(project_root=tmp_path, group_id="test-group")


def _task_ref(mode: str) -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Verification mode routing",
        verification_mode=mode,
        verification=VerificationSpec(
            level="unit",
            checks=[
                {
                    "name": SHELL_CHECK_NAME,
                    "command": "true",
                    "required": True,
                    "expected_exit_code": 0,
                }
            ],
            covers_tasks=[TASK_ID],
        ),
    )


def _review_result(summary: str) -> VerificationResult:
    return VerificationResult(
        verification_id=f"ver-{summary}",
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        overall_outcome="passed",
        checks=[],
        summary=summary,
    )


def test_ralph_mode_runs_shell_checks_without_review(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with (
        patch.object(service, "_verify_completion_with_agent") as agent_review,
        patch.object(service, "_verify_completion_with_challenge") as challenge_review,
    ):
        result = service.verify_completion(
            TASK_ID,
            [],
            workflow_id=WORKFLOW_ID,
            task_ref=_task_ref("ralph"),
        )

    assert result.overall_outcome == "passed"
    assert [check.name for check in result.checks] == [SHELL_CHECK_NAME]
    agent_review.assert_not_called()
    challenge_review.assert_not_called()


def test_agent_mode_runs_shell_checks_then_agent_review(tmp_path: Path) -> None:
    service = _service(tmp_path)
    agent_result = _review_result("agent review")

    with (
        patch.object(
            service,
            "_verify_completion_with_agent",
            return_value=agent_result,
        ) as agent_review,
        patch.object(service, "_verify_completion_with_challenge") as challenge_review,
    ):
        result = service.verify_completion(
            TASK_ID,
            [],
            workflow_id=WORKFLOW_ID,
            task_ref=_task_ref("agent"),
        )

    assert result == agent_result
    challenge_review.assert_not_called()
    agent_review.assert_called_once()
    verification_output = agent_review.call_args.kwargs["verification_output"]
    assert verification_output["checks"][0]["name"] == SHELL_CHECK_NAME
    assert verification_output["checks"][0]["outcome"] == "passed"


def test_challenge_mode_runs_shell_checks_then_challenge_review(tmp_path: Path) -> None:
    service = _service(tmp_path)
    challenge_result = _review_result("challenge review")

    with (
        patch.object(service, "_verify_completion_with_agent") as agent_review,
        patch.object(
            service,
            "_verify_completion_with_challenge",
            return_value=challenge_result,
        ) as challenge_review,
    ):
        result = service.verify_completion(
            TASK_ID,
            [],
            workflow_id=WORKFLOW_ID,
            task_ref=_task_ref("challenge"),
        )

    assert result == challenge_result
    agent_review.assert_not_called()
    challenge_review.assert_called_once()
    worker_result = challenge_review.call_args.kwargs["worker_result"]
    assert [check.name for check in worker_result.checks] == [SHELL_CHECK_NAME]
    assert worker_result.overall_outcome == "passed"
