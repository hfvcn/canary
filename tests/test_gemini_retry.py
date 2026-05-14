from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cccc.daemon.foreman.ralph_service import (
    CHALLENGE_DEGRADED_WARNING,
    RalphService,
)
from cccc.ralph.agent import (
    AgentConfig,
    GEMINI_PROVIDER,
    GeminiResponseError,
    RalphAgent,
)
from cccc.ralph.models import TaskSpec, ValidationIssue


def _agent() -> RalphAgent:
    return RalphAgent(
        workflow_id="wf-gemini-retry",
        config=AgentConfig(provider=GEMINI_PROVIDER, warmup_enabled=False),
    )


def _issue() -> ValidationIssue:
    return ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="goal_behavior references missing function run_review",
        task_ids=["T2"],
        evidence={"path": "src/cccc/ralph/agent.py", "symbol": "run_review"},
        beyond_scope=True,
        issue_instance_id="issue-001",
    )


def _task() -> TaskSpec:
    return TaskSpec(
        id="T2",
        title="Retry Gemini JSON failures",
        type="backend",
        claimed_paths=["src/cccc/ralph/agent.py"],
        goal_behavior="Retry Gemini JSON parse failures once before surfacing or degrading.",
        acceptance_criteria="Review retries once; challenge verification degrades after second JSON failure.",
        verification_mode="challenge",
    )


def _wrapped_response(payload: dict[str, Any]) -> str:
    return json.dumps({"response": json.dumps(payload)})


def test_review_retries_on_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    sleeps: list[int] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        stdout = "not-json"
        if calls["count"] == 2:
            stdout = _wrapped_response({
                "suggestions": [{
                    "issue_id": "issue-001",
                    "checklist_item_id": "RV-18",
                    "suggestion": "Retry once before failing.",
                    "confidence": "medium",
                }]
            })
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", fake_run)
    monkeypatch.setattr("cccc.ralph.agent.time.sleep", lambda seconds: sleeps.append(seconds))

    suggestions = _agent().review_beyond_scope([_issue()])

    assert calls["count"] == 2
    assert sleeps == [2]
    assert suggestions[0].suggestion == "Retry once before failing."


def test_review_raises_after_two_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    sleeps: list[int] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="")

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", fake_run)
    monkeypatch.setattr("cccc.ralph.agent.time.sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(GeminiResponseError, match="Gemini response was not valid JSON"):
        _agent().review_beyond_scope([_issue()])

    assert calls["count"] == 2
    assert sleeps == [2]


def test_verify_retries_on_json_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = {"count": 0}
    sleeps: list[int] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        stdout = "not-json"
        if calls["count"] == 2:
            stdout = _wrapped_response({
                "passed": True,
                "summary": "Challenge checks passed after retry",
                "checks": [],
            })
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", fake_run)
    monkeypatch.setattr("cccc.ralph.agent.time.sleep", lambda seconds: sleeps.append(seconds))

    result = _agent().verify_task_completion(
        _task(),
        changed_files=["src/cccc/ralph/agent.py"],
        project_root=tmp_path,
    )

    assert calls["count"] == 2
    assert sleeps == [2]
    assert result["outcome"] == "passed"
    assert result["reason"] == "Challenge checks passed after retry"


def test_verify_returns_degraded_after_two_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = {"count": 0}
    sleeps: list[int] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="")

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", fake_run)
    monkeypatch.setattr("cccc.ralph.agent.time.sleep", lambda seconds: sleeps.append(seconds))

    result = _agent().verify_task_completion(
        _task(),
        changed_files=["src/cccc/ralph/agent.py"],
        project_root=tmp_path,
    )

    assert calls["count"] == 2
    assert sleeps == [2]
    assert result["outcome"] == "failed"
    assert result["degraded"] is True
    assert "Verification blocked" in result["reason"]


def test_degraded_result_has_correct_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "cccc.ralph.agent.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr=""),
    )
    monkeypatch.setattr("cccc.ralph.agent.time.sleep", lambda seconds: None)

    result = _agent().verify_task_completion(
        _task(),
        changed_files=["src/cccc/ralph/agent.py"],
        project_root=tmp_path,
    )

    assert {"outcome", "reason", "checks"} <= result.keys()
    assert result["checks"] == []


def test_service_adds_warning_for_degraded_payload(tmp_path: Path) -> None:
    result = RalphService(
        project_root=tmp_path,
        group_id="group-1",
    )._agent_verification_result(
        "T2",
        "wf-1",
        [],
        {
            "outcome": "failed",
            "reason": "Verification blocked: Gemini response unparseable after retry",
            "checks": [],
            "degraded": True,
        },
    )

    assert result.overall_outcome == "failed"
    assert result.warnings == [CHALLENGE_DEGRADED_WARNING]
