"""Tests for challenge-mode adversarial verification gate."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.ralph_service import (
    CHALLENGE_DEGRADED_WARNING_CODE,
    RalphService,
)


def _task_ref() -> TaskRef:
    return TaskRef(
        id="T1",
        title="Task T1",
        goal_behavior="Implement exact edge-case behavior.",
        acceptance_criteria="Reject malformed inputs and preserve valid output.",
        claimed_paths=["src/t1.py"],
        verification_mode="challenge",
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
            covers_tasks=["T1"],
        ),
    )


def _service(tmp_path: Path) -> RalphService:
    return RalphService(project_root=tmp_path, group_id="test-group")


def _agent_completed(passed: bool) -> subprocess.CompletedProcess[str]:
    payload = {
        "passed": passed,
        "summary": "agent found adversarial edge-case result",
        "checks": [
            {
                "name": "adversarial_edge_case",
                "outcome": "passed" if passed else "failed",
                "message": "edge case reviewed",
            }
        ],
    }
    return subprocess.CompletedProcess(
        args=["gemini"],
        returncode=0,
        stdout=json.dumps({"response": json.dumps(payload)}),
        stderr="",
    )


def test_challenge_mode_agent_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cccc.ralph.agent.subprocess.run",
        lambda command, **kwargs: _agent_completed(True),
    )

    result = _service(tmp_path).verify_completion(
        "T1",
        [],
        workflow_id="wf-1",
        task_ref=_task_ref(),
    )

    assert result.overall_outcome == "passed"
    assert result.challenge_outcome == "passed"
    assert [check.name for check in result.checks] == [
        "worker-check",
        "adversarial_edge_case",
    ]


def test_challenge_mode_agent_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cccc.ralph.agent.subprocess.run",
        lambda command, **kwargs: _agent_completed(False),
    )

    result = _service(tmp_path).verify_completion(
        "T1",
        [],
        workflow_id="wf-1",
        task_ref=_task_ref(),
    )

    assert result.overall_outcome == "failed"
    assert result.challenge_outcome == "failed"
    assert "agent found adversarial edge-case result" in result.summary


def test_challenge_mode_agent_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing_agent(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Ralph Agent verification is disabled")

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _missing_agent,
    )

    result = _service(tmp_path).verify_completion(
        "T1",
        [],
        workflow_id="wf-1",
        task_ref=_task_ref(),
    )

    assert result.overall_outcome == "passed"
    assert result.challenge_outcome == ""
    assert result.warnings
    assert result.warnings[0].startswith(f"{CHALLENGE_DEGRADED_WARNING_CODE}:")
