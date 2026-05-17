from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.ralph_service import (
    CHALLENGE_DEGRADED_WARNING_CODE,
    RalphService,
)


def _task_ref(mode: str) -> TaskRef:
    return TaskRef(
        id="T3",
        title="Challenge degradation",
        goal_behavior="Degrade challenge mode only when agent verification is unavailable.",
        acceptance_criteria="Network errors fail closed; real agent failures fail.",
        claimed_paths=["src/t3.py"],
        verification_mode=mode,
        verification=VerificationSpec(
            level="unit",
            command="true",
            checks=[
                {
                    "name": "worker-check",
                    "command": "true",
                    "required": True,
                    "expected_exit_code": 0,
                }
            ],
            covers_tasks=["T3"],
        ),
    )


def _verify(tmp_path: Path, mode: str) -> Any:
    return RalphService(project_root=tmp_path, group_id="test-group").verify_completion(
        "T3",
        [],
        workflow_id="wf-1",
        task_ref=_task_ref(mode),
    )


def test_challenge_reports_infra_error_on_gemini_network_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_network_error(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        raise OSError("ECONNRESET")

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _raise_network_error,
    )

    result = _verify(tmp_path, "challenge")

    assert result.overall_outcome == "infra_error"
    assert result.challenge_outcome == "infra_error"
    assert [check.name for check in result.checks] == ["worker-check"]
    assert result.summary.startswith("worker verification passed; challenge verification infra_error")
    assert "agent verification infrastructure error: ECONNRESET" in result.summary
    assert result.warnings == []


def test_challenge_genuine_agent_failed_judgment_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _agent_failed(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "outcome": "failed",
            "reason": "agent found a real regression",
            "checks": [
                {"name": "agent-check", "outcome": "failed", "message": "bad"}
            ],
        }

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _agent_failed,
    )

    result = _verify(tmp_path, "challenge")

    assert result.overall_outcome == "failed"
    assert result.challenge_outcome == "failed"
    assert result.warnings == []
    assert "agent found a real regression" in result.summary


def test_challenge_infra_error_detail_is_in_verification_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_network_error(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        raise OSError("connection reset by peer")

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _raise_network_error,
    )

    result = _verify(tmp_path, "challenge")

    assert result.overall_outcome == "infra_error"
    assert "connection reset by peer" in result.summary
    assert result.warnings == []


AGENT_TIMEOUT_SECONDS = 5


@pytest.mark.parametrize(
    "failure",
    [
        (RuntimeError("agent bootstrap failed"), "agent bootstrap failed", "failed"),
        (OSError("temporary dns failure"), "temporary dns failure", "infra_error"),
        (
            subprocess.TimeoutExpired(
                cmd="gemini",
                timeout=AGENT_TIMEOUT_SECONDS,
            ),
            f"timed out after {AGENT_TIMEOUT_SECONDS} seconds",
            "infra_error",
        ),
    ],
)
def test_challenge_verifier_exception_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: tuple[Exception, str, str],
) -> None:
    exc, expected_detail, expected_outcome = failure

    def _raise_infrastructure_error(
        self: Any,
        task: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _raise_infrastructure_error,
    )

    result = _verify(tmp_path, "challenge")

    assert [check.name for check in result.checks] == ["worker-check"]
    assert result.overall_outcome == expected_outcome
    if expected_outcome == "infra_error":
        assert result.challenge_outcome == "infra_error"
        assert expected_detail in result.summary
        assert result.warnings == []
        return
    assert result.challenge_outcome == ""
    assert result.summary == (
        "challenge verification failed: agent infrastructure unavailable "
        f"({expected_detail})"
    )
    assert result.warnings[0].startswith(f"{CHALLENGE_DEGRADED_WARNING_CODE}:")
    assert expected_detail in result.warnings[0]


def test_agent_mode_network_error_not_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_network_error(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        raise OSError("ECONNRESET")

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _raise_network_error,
    )

    result = _verify(tmp_path, "agent")

    assert result.overall_outcome == "infra_error"
    assert result.summary == "agent verification infrastructure error: ECONNRESET"
    assert result.warnings == []
