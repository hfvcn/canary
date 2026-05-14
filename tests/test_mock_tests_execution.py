"""Tests for agent-mode mock_tests execution and prompt redaction."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from cccc.contracts.v1.ralph_ipc import (
    MockTestCase,
    TaskEvent,
    TaskRef,
    VerificationSpec,
)
from cccc.daemon.foreman.context_store import ContextStore
from cccc.daemon.foreman.prompt_builder import build_task_prompt
from cccc.daemon.foreman.ralph_service import RalphAgent, RalphService
from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator


SECRET_NAME = "SECRET_CASE_NAME_4711"
SECRET_COMMAND = "SECRET_VERIFY_COMMAND_4711"
SECRET_STDOUT = "SECRET_STDOUT_4711"
SECRET_STDERR = "SECRET_STDERR_4711"
SECRET_INPUT = "SECRET_INPUT_4711"
SECRET_EXPECTED = "SECRET_EXPECTED_4711"
SANITIZED_FAILURE = "verification failed: 1 of 2 mock tests did not pass"


def _python_command(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _service(tmp_path: Path) -> RalphService:
    return RalphService(project_root=tmp_path, group_id="test-group")


def _agent_task(task_id: str, mock_tests: List[MockTestCase] | None) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        type="backend",
        goal_behavior="Implement the public behavior",
        acceptance_criteria="Public acceptance criteria are visible",
        verification_mode="agent",
        verification=VerificationSpec(level="unit", mock_tests=mock_tests),
    )


def _no_gemini(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    del args, kwargs
    raise FileNotFoundError("gemini unavailable")


def _passing_mock_test() -> MockTestCase:
    setup = _python_command(
        "from pathlib import Path; Path('mock-fixture.txt').write_text('ok')"
    )
    verify = _python_command(
        "from pathlib import Path; "
        "raise SystemExit(0 if Path('mock-fixture.txt').read_text() == 'ok' else 2)"
    )
    return MockTestCase(name="passing-case", setup_command=setup, verify_command=verify)


def _failing_mock_test() -> MockTestCase:
    verify = _python_command(
        "import sys; "
        f"print('{SECRET_STDOUT}'); "
        f"print('{SECRET_STDERR}', file=sys.stderr); "
        "sys.exit(7)"
    )
    return MockTestCase(
        name=SECRET_NAME,
        input={"payload": SECRET_INPUT},
        expected_output={"result": SECRET_EXPECTED},
        verify_command=f"{verify} # {SECRET_COMMAND}",
        description="adversarial hidden case",
    )


def _assert_sensitive_absent(text: str) -> None:
    for secret in (
        SECRET_NAME,
        SECRET_COMMAND,
        SECRET_STDOUT,
        SECRET_STDERR,
        SECRET_INPUT,
        SECRET_EXPECTED,
    ):
        assert secret not in text


def _register_running_task(
    orchestrator: WorkflowOrchestrator,
    task: TaskRef,
    *,
    workflow_id: str,
    agent_id: str,
) -> None:
    orchestrator.engine.register_task(task, workflow_id)
    orchestrator.engine.register_batch(f"b-{task.id}", [task.id])
    orchestrator.engine.approve_batch(
        f"b-{task.id}",
        [{"task_id": task.id, "agent_id": agent_id, "claimed_paths": []}],
    )
    orchestrator.engine.report_worker_started(task.id, agent_id)


def test_mock_tests_all_pass_without_gemini_returns_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RalphAgent, "verify_task_completion", _no_gemini)
    task = _agent_task("T-pass", [_passing_mock_test()])

    result = _service(tmp_path).verify_completion(
        "T-pass",
        [],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert result.overall_outcome == "passed"
    assert result.summary == "verification passed: 1 mock tests passed"
    assert [check.outcome for check in result.checks] == ["passed"]
    assert any("W_AGENT_REVIEW_SKIPPED" in warning for warning in result.warnings)
    assert (tmp_path / "mock-fixture.txt").read_text(encoding="utf-8") == "ok"


def test_mock_tests_partial_failure_returns_sanitized_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        del args, kwargs
        pytest.fail("Gemini must not run after mock_tests fail")

    monkeypatch.setattr(RalphAgent, "verify_task_completion", fail_if_called)
    task = _agent_task("T-fail", [_passing_mock_test(), _failing_mock_test()])

    result = _service(tmp_path).verify_completion(
        "T-fail",
        [],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert result.overall_outcome == "failed"
    assert result.summary == SANITIZED_FAILURE
    _assert_sensitive_absent(result.summary)
    failed_check = result.checks[1]
    assert failed_check.name == "mock_test_2"
    assert failed_check.message == "mock test did not pass"
    assert failed_check.details["mock_test_name"] == SECRET_NAME
    assert failed_check.details["verify_command"].endswith(SECRET_COMMAND)
    assert SECRET_STDOUT in failed_check.details["verify"]["stdout"]
    assert SECRET_STDERR in failed_check.details["verify"]["stderr"]


def test_agent_mode_without_mock_tests_uses_gemini_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: List[Dict[str, Any]] = []

    def fake_verify(self: RalphAgent, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        del self, args
        calls.append(kwargs)
        return {
            "outcome": "passed",
            "reason": "gemini path passed",
            "checks": [{"name": "agent_review", "outcome": "passed", "message": "ok"}],
        }

    monkeypatch.setattr(RalphAgent, "verify_task_completion", fake_verify)
    task = _agent_task("T-agent", None)

    result = _service(tmp_path).verify_completion(
        "T-agent",
        [],
        workflow_id="wf-1",
        task_ref=task,
    )

    assert calls
    assert result.overall_outcome == "passed"
    assert result.summary == "gemini path passed"
    assert [check.name for check in result.checks] == ["agent_review"]


def test_worker_prompt_does_not_include_mock_tests_content() -> None:
    task = _agent_task("T-prompt", [_failing_mock_test()])

    prompt = build_task_prompt(task)

    assert "Acceptance Criteria: Public acceptance criteria are visible" in prompt
    assert "mock_tests" not in prompt
    _assert_sensitive_absent(prompt)


def test_retry_context_uses_sanitized_mock_tests_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RalphAgent, "verify_task_completion", _no_gemini)
    orchestrator = WorkflowOrchestrator(project_root=tmp_path, group_id="test-group")
    monkeypatch.setattr(
        orchestrator.reporter,
        "on_task_failed",
        lambda *args, **kwargs: True,
    )
    task = _agent_task("T-retry", [_passing_mock_test(), _failing_mock_test()])
    _register_running_task(
        orchestrator,
        task,
        workflow_id="wf-retry",
        agent_id="worker-retry",
    )

    result = orchestrator.apply_task_event(
        TaskEvent(
            task_id="T-retry",
            event_type="completed",
            payload={
                "agent_id": "worker-retry",
                "duration_seconds": 3,
                "changed_files": ["src/example.py"],
            },
        )
    )

    context = ContextStore(tmp_path).load("T-retry")
    retry_prompt = orchestrator._build_task_prompt(task)

    assert result["verification_outcome"] == "failed"
    assert context is not None
    assert context.last_error == SANITIZED_FAILURE
    assert SANITIZED_FAILURE in retry_prompt
    _assert_sensitive_absent(context.last_error)
    _assert_sensitive_absent(retry_prompt)
