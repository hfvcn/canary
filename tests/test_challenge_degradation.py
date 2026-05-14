from __future__ import annotations

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
        acceptance_criteria="Network errors pass worker-only; real agent failures fail.",
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


def test_challenge_degrades_on_gemini_network_error(
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

    assert result.overall_outcome == "passed"
    assert result.challenge_outcome == ""
    assert [check.name for check in result.checks] == ["worker-check"]
    assert result.warnings == [
        "W_CHALLENGE_DEGRADED: agent verification unavailable "
        "(ECONNRESET), falling back to worker-only"
    ]


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


def test_challenge_degradation_warning_is_in_verification_result(
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

    assert len(result.warnings) == 1
    assert result.warnings[0].startswith(f"{CHALLENGE_DEGRADED_WARNING_CODE}:")
    assert "connection reset by peer" in result.warnings[0]


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

    assert result.overall_outcome == "failed"
    assert result.summary == "agent verification failed: ECONNRESET"
    assert result.warnings == []
