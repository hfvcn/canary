from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.verification_gate import (
    INPUT_ROBUSTNESS_CHECK_NAME,
    SECURITY_LINT_CHECK_NAME,
    _apply_input_robustness_gate,
    _apply_security_lint_gate,
    _mode_gate_task_ref,
)
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


@pytest.mark.parametrize(
    ("mode", "expected_outcome"),
    [("ralph", "passed"), ("agent", "passed"), ("challenge", "failed")],
)
def test_security_lint_gate_respects_mode(
    tmp_path: Path,
    mode: str,
    expected_outcome: str,
) -> None:
    _write(tmp_path, "src/app.py", "app.run(debug=True)\n")

    result = _apply_security_lint_gate(
        verification=_gate_result(),
        engine=_GateEngine(tmp_path),
        task_id=TASK_ID,
        changed_files=["src/app.py"],
        workspace_root=tmp_path,
        task_ref=_task_ref_for_gate(mode),
    )

    assert result.overall_outcome == expected_outcome
    if expected_outcome == "failed":
        assert _verification_check(result, SECURITY_LINT_CHECK_NAME)
    else:
        assert "security_lint warning" in result.warnings[0]


def test_security_lint_blocks_after_critical_flow_upgrade(tmp_path: Path) -> None:
    _write(tmp_path, "src/app.py", "app.run(debug=True)\n")
    task_ref = _task_ref_for_gate("ralph")
    gate_task_ref = _mode_gate_task_ref(
        ralph_service=_UpgradingService(),
        task_ref=task_ref,
        workflow_id=WORKFLOW_ID,
    )

    result = _apply_security_lint_gate(
        verification=_gate_result(),
        engine=_GateEngine(tmp_path),
        task_id=TASK_ID,
        changed_files=["src/app.py"],
        workspace_root=tmp_path,
        task_ref=gate_task_ref,
    )

    assert task_ref.verification_mode == "ralph"
    assert gate_task_ref.verification_mode == "challenge"
    assert result.overall_outcome == "failed"
    assert _verification_check(result, SECURITY_LINT_CHECK_NAME)


@pytest.mark.parametrize(
    ("mode", "expected_outcome"),
    [("ralph", "passed"), ("agent", "passed"), ("challenge", "failed")],
)
def test_input_robustness_gate_respects_mode(
    tmp_path: Path,
    mode: str,
    expected_outcome: str,
) -> None:
    _write(tmp_path, "tests/test_search.py", "def test_search():\n    assert True\n")

    result = _apply_input_robustness_gate(
        verification=_gate_result(),
        engine=_GateEngine(tmp_path),
        task_id=TASK_ID,
        workspace_root=tmp_path,
        task_ref=_input_task_ref(mode),
    )

    assert result.overall_outcome == expected_outcome
    if expected_outcome == "failed":
        assert _verification_check(result, INPUT_ROBUSTNESS_CHECK_NAME)
    else:
        assert "input_robustness warning" in result.warnings[0]


class _GateEngine:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.warnings: list[dict[str, Any]] = []

    def record_verification_warning(self, task_id: str, **kwargs: Any) -> None:
        self.warnings.append({"task_id": task_id, **kwargs})

    def get_task(self, task_id: str) -> None:
        return None


class _UpgradingService:
    def _should_upgrade_to_challenge(self, task_ref: TaskRef, workflow_id: str) -> bool:
        return True


def _task_ref_for_gate(mode: str) -> TaskRef:
    return TaskRef(
        id=TASK_ID,
        title="Mode-aware gate task",
        claimed_paths=["src/app.py"],
        verification_mode=mode,
    )


def _input_task_ref(mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        verification_mode=mode,
        critical_flows=[
            {"id": "search_flow", "description": "search query endpoint"},
        ],
        verification=SimpleNamespace(
            checks=[
                SimpleNamespace(command="python -m pytest tests/test_search.py -v"),
            ],
        ),
    )


def _gate_result() -> VerificationResult:
    return VerificationResult(
        verification_id="ver-gate",
        workflow_id=WORKFLOW_ID,
        task_id=TASK_ID,
        overall_outcome="passed",
        checks=[],
        summary="worker verification passed",
    )


def _write(project_root: Path, relative_path: str, content: str) -> None:
    target = project_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _verification_check(verification: VerificationResult, check_name: str) -> Any:
    return next(check for check in verification.checks if check.name == check_name)
