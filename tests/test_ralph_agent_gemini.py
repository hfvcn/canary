from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from cccc.ralph import cli
from cccc.ralph.agent import (
    AgentConfig,
    AgentSuggestion,
    GEMINI_PROVIDER,
    GeminiResponseError,
    RalphAgent,
)
from cccc.ralph.models import Plan, TaskSpec, ValidationIssue, ValidationReport


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _checklist_path() -> Path:
    return _repo_root() / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"


def _plan() -> Plan:
    return Plan(
        schema_version="1.0.0",
        tasks=[
            TaskSpec(
                id="T5a",
                title="Gemini agent integration",
                type="backend",
                claimed_paths=["src/cccc/ralph/agent.py"],
                goal_behavior="Review goal_behavior symbols with Gemini Flash.",
                acceptance_criteria="Suggestions remain advisory only.",
            )
        ],
    )


def _issue() -> ValidationIssue:
    return ValidationIssue(
        code="S_SYMBOL_TARGET_MISSING",
        severity="warning",
        message="goal_behavior references missing function run_review",
        task_ids=["T5a"],
        evidence={"path": "src/cccc/ralph/agent.py", "symbol": "run_review"},
        beyond_scope=True,
        issue_instance_id="issue-001",
    )


def _args(tmp_path: Path, *, no_agent: bool, fmt: str) -> argparse.Namespace:
    return argparse.Namespace(
        format=fmt,
        gate=None,
        group=None,
        ledger=None,
        no_agent=no_agent,
        no_semantic=False,
        plan=tmp_path / "plan.yaml",
        project_root=tmp_path,
        suppress=[],
    )


def test_gemini_call_constructs_prompt_from_beyond_scope_issues(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append({"cmd": cmd, "kwargs": kwargs})
        payload = {
            "suggestions": [{
                "issue_id": "issue-001",
                "checklist_item_id": "RV-18",
                "suggestion": "Check run_review exists before accepting this plan.",
                "confidence": "medium",
            }]
        }
        stdout = json.dumps({"response": json.dumps(payload)})
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", fake_run)
    agent = RalphAgent(
        workflow_id="wf-gemini",
        plan=_plan(),
        checklist_path=_checklist_path(),
        config=AgentConfig(provider=GEMINI_PROVIDER),
    )

    agent.warm_up()
    suggestions = agent.review_beyond_scope([_issue()])

    warmup_cmd = captured[0]["cmd"]
    warmup_prompt = warmup_cmd[warmup_cmd.index("--prompt") + 1]
    assert "Return exactly this JSON" in warmup_prompt
    assert "--resume" not in warmup_cmd

    cmd = captured[1]["cmd"]
    prompt = cmd[cmd.index("--prompt") + 1]
    assert cmd[:5] == ["gemini", "--model", "flash", "--output-format", "json"]
    assert cmd[cmd.index("--resume") + 1] == "latest"
    assert captured[1]["kwargs"]["check"] is True
    assert "issue-001" in prompt
    assert "S_SYMBOL_TARGET_MISSING" in prompt
    assert "Gemini agent integration" in prompt
    assert "Review goal_behavior symbols with Gemini Flash." in prompt
    assert "advisory only" in prompt
    assert suggestions == [
        AgentSuggestion(
            issue_id="issue-001",
            checklist_item_id="RV-18",
            suggestion="Check run_review exists before accepting this plan.",
            confidence="medium",
            advisory=True,
        )
    ]


def test_warm_up_is_called_by_cli_agent_review(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    class FakeAgent:
        def warm_up(self) -> None:
            calls.append("warm_up")

        def review_beyond_scope(self, issues: list[ValidationIssue]) -> list[AgentSuggestion]:
            calls.append("review")
            return [
                AgentSuggestion(
                    issue_id=issues[0].issue_instance_id,
                    checklist_item_id="RV-18",
                    suggestion="Inspect this manually.",
                )
            ]

    report = ValidationReport(valid=False, warnings=[_issue()])
    monkeypatch.setattr(cli, "create_agent", lambda checklist_path, **kwargs: FakeAgent())

    suggestions = cli._review_beyond_scope_with_agent(
        plan=_plan(),
        report=report,
        project_root=tmp_path,
        plan_path=tmp_path / "plan.yaml",
        no_agent=False,
    )

    assert calls == ["warm_up", "review"]
    assert suggestions[0].issue_id == "issue-001"


def test_no_agent_skips_agent_and_keeps_static_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "validate_with_project",
        lambda plan, project_root: ValidationReport(valid=False, warnings=[_issue()]),
    )
    monkeypatch.setattr(cli, "_auto_detect_group", lambda project_root: "")

    def fail_create_agent(checklist_path: Path, **kwargs: object) -> RalphAgent:
        raise AssertionError("--no-agent must not create RalphAgent")

    monkeypatch.setattr(cli, "create_agent", fail_create_agent)

    exit_code = cli._cmd_validate(_plan(), _args(tmp_path, no_agent=True, fmt="json"))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert "agent_suggestions" not in payload
    assert payload["warnings"][0]["code"] == "S_SYMBOL_TARGET_MISSING"


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("gemini"),
        OSError("permission denied"),
        subprocess.CalledProcessError(2, ["gemini"], stderr="api rejected"),
        subprocess.TimeoutExpired(["gemini"], 60),
    ],
)
def test_gemini_subprocess_failures_are_exposed(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def raise_failure(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise failure

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", raise_failure)
    agent = RalphAgent(
        workflow_id="wf-missing-gemini",
        checklist_path=_checklist_path(),
        config=AgentConfig(provider=GEMINI_PROVIDER),
    )

    with pytest.raises(type(failure)):
        agent.review_beyond_scope([_issue()])


def test_gemini_parse_failure_is_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_json(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="")

    monkeypatch.setattr("cccc.ralph.agent.subprocess.run", invalid_json)
    agent = RalphAgent(
        workflow_id="wf-invalid-gemini",
        checklist_path=_checklist_path(),
        config=AgentConfig(provider=GEMINI_PROVIDER),
    )

    with pytest.raises(GeminiResponseError, match="Gemini response was not valid JSON"):
        agent.review_beyond_scope([_issue()])


def test_agent_suggestions_are_marked_advisory_in_text_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    class FakeAgent:
        def warm_up(self) -> None:
            return None

        def review_beyond_scope(self, issues: list[ValidationIssue]) -> list[AgentSuggestion]:
            assert issues == [_issue()]
            return [
                AgentSuggestion(
                    issue_id="issue-001",
                    checklist_item_id="RV-18",
                    suggestion="Inspect this manually; advisory only.",
                    confidence="high",
                    advisory=True,
                )
            ]

    monkeypatch.setattr(
        cli,
        "validate_with_project",
        lambda plan, project_root: ValidationReport(valid=False, warnings=[_issue()]),
    )
    monkeypatch.setattr(cli, "_auto_detect_group", lambda project_root: "")
    monkeypatch.setattr(cli, "create_agent", lambda checklist_path, **kwargs: FakeAgent())

    exit_code = cli._cmd_validate(_plan(), _args(tmp_path, no_agent=False, fmt="text"))

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Agent Suggestions (advisory only, for reference)" in output
    assert "[agent] RV-18: Inspect this manually; advisory only." in output
