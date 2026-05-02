from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.prompt_builder import build_task_prompt
from cccc.ralph.core import verify
from cccc.ralph.models import TaskSpec, Verification, VerificationCovers


def _verification(task_id: str, command: str = "true") -> Verification:
    return Verification(
        level="integration",
        command=command,
        covers=VerificationCovers(tasks=[task_id]),
    )


def _task(task_id: str, *, verification_mode: str = "agent") -> TaskSpec:
    return TaskSpec(
        id=task_id,
        title=f"Task {task_id}",
        claimed_paths=[f"src/{task_id.lower()}.py"],
        goal_behavior="Handle the user workflow correctly.",
        acceptance_criteria="Foreman simulation cases pass.",
        verification=_verification(task_id),
        verification_mode=verification_mode,
    )


def _gemini_stdout(payload: dict[str, Any]) -> str:
    return json.dumps({"response": json.dumps(payload)})


def _completed(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gemini"],
        returncode=0,
        stdout=_gemini_stdout(payload),
        stderr="",
    )


def _positive_payload() -> dict[str, Any]:
    return {
        "passed": True,
        "summary": "simulation accepted behavior",
        "checks": [{"name": "foreman_case", "outcome": "passed", "message": "ok"}],
    }


def test_agent_mode_routes_through_ralph_agent_with_subprocess_mocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return _completed(_positive_payload())

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", fake_run)

    result = verify(_task("T-agent"), changed_files=["src/t_agent.py"], project_root=tmp_path)

    gemini_calls = [c for c in calls if isinstance(c, list) and "gemini" in c]
    assert len(gemini_calls) == 1
    gemini_cmd = gemini_calls[0]
    prompt_idx = gemini_cmd.index("--prompt")
    prompt = gemini_cmd[prompt_idx + 1]
    assert result["outcome"] == "passed"
    assert result["reason"] == "simulation accepted behavior"
    assert gemini_cmd[:2] == ["gemini", "--model"]
    assert "ONLY on the evidence" in prompt


def test_ralph_mode_still_uses_existing_core_verify_checks_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FailAgent:
        def __init__(self, **kwargs: Any) -> None:
            raise AssertionError("RalphAgent must not be constructed in ralph mode")

    def fake_check(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"name": kwargs["name"], "outcome": "passed", "duration_ms": 1}

    monkeypatch.setattr("cccc.ralph.core.RalphAgent", FailAgent)
    monkeypatch.setattr("cccc.ralph.core._run_check", fake_check)

    result = verify(_task("T-ralph", verification_mode="ralph"), [], project_root=tmp_path)

    assert result["outcome"] == "passed"
    assert calls[0]["command"] == "true"
    assert calls[0]["expected_exit_code"] == 0


def test_agent_pending_resolves_to_pass_after_agent_positive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "cccc.ralph.agent.subprocess.run",
        lambda command, **kwargs: _completed(_positive_payload()),
    )

    result = verify(_task("T-pass"), changed_files=[], project_root=tmp_path)

    assert result["outcome"] == "passed"
    assert result["outcome"] != "agent_pending"


def test_agent_pending_resolves_to_fail_after_agent_negative(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = {
        "passed": False,
        "summary": "simulation rejected behavior",
        "checks": [{"name": "foreman_case", "outcome": "failed", "message": "bad"}],
    }
    monkeypatch.setattr(
        "cccc.ralph.agent.subprocess.run",
        lambda command, **kwargs: _completed(payload),
    )

    result = verify(_task("T-fail"), changed_files=[], project_root=tmp_path)

    assert result["outcome"] == "failed"
    assert result["reason"] == "simulation rejected behavior"
    assert result["outcome"] != "agent_pending"


def test_agent_mode_worker_prompt_hides_foreman_simulation_cases() -> None:
    task = TaskRef(
        id="T-hidden",
        title="Hidden simulation task",
        verification_mode="agent",
        verification=VerificationSpec(
            level="integration",
            command="pytest tests/foreman_hidden_cases.py --expected-output secret.json",
        ),
    )

    prompt = build_task_prompt(task)

    assert "Verification Command:" not in prompt
    assert "foreman_hidden_cases" not in prompt
    assert "expected-output" not in prompt
