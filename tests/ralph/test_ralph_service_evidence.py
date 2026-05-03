from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService


VERIFY_COMMAND = 'python -c "print(\'ok\')"'


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_git(tmp_path: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> None:
    _run_git(tmp_path, "init")
    _run_git(tmp_path, "config", "user.name", "Test User")
    _run_git(tmp_path, "config", "user.email", "test@example.com")
    _write(tmp_path / "src" / "app.py", "VALUE = 1\n")
    _run_git(tmp_path, "add", "src/app.py")
    _run_git(tmp_path, "commit", "-m", "init")


def _task_ref(mode: str) -> TaskRef:
    return TaskRef(
        id="T1",
        title="Inject evidence",
        goal_behavior="Ensure daemon verification passes evidence to agent.",
        acceptance_criteria="agent receives source context, diff, and verification output.",
        claimed_paths=["src/app.py"],
        verification_mode=mode,
        verification=VerificationSpec(
            level="integration",
            command=VERIFY_COMMAND,
            checks=[
                {
                    "name": "worker-check",
                    "command": VERIFY_COMMAND,
                    "required": True,
                    "expected_exit_code": 0,
                }
            ],
            covers_tasks=["T1"],
        ),
    )


def test_agent_mode_injects_source_context_diff_and_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / "src" / "app.py", "VALUE = 2\n")
    captured: dict[str, Any] = {}

    def _fake_verify(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "outcome": "passed",
            "reason": "agent ok",
            "checks": [{"name": "agent-check", "outcome": "passed", "message": "ok"}],
        }

    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _fake_verify,
    )

    result = RalphService(project_root=tmp_path, group_id="test-group").verify_completion(
        "T1",
        ["src/app.py"],
        workflow_id="wf-1",
        task_ref=_task_ref("agent"),
    )

    assert result.overall_outcome == "passed"
    assert "VALUE = 2" in captured["source_context"]["src/app.py"]
    assert "VALUE = 1" in captured["git_diff"]
    assert "VALUE = 2" in captured["git_diff"]
    assert captured["verification_output"]["status"] == "passed"
    assert captured["verification_output"]["checks"][0]["command"] == VERIFY_COMMAND


def test_challenge_mode_reuses_worker_verification_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / "src" / "app.py", "VALUE = 3\n")
    service = RalphService(project_root=tmp_path, group_id="test-group")
    captured: dict[str, Any] = {}

    def _unexpected_precheck(task_ref: TaskRef) -> dict[str, Any]:
        raise AssertionError("challenge path should reuse worker verification output")

    def _fake_verify(self: Any, task: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "outcome": "passed",
            "reason": "agent ok",
            "checks": [{"name": "agent-check", "outcome": "passed", "message": "ok"}],
        }

    monkeypatch.setattr(service, "_run_verification_pre_check", _unexpected_precheck)
    monkeypatch.setattr(
        "cccc.daemon.foreman.ralph_service.RalphAgent.verify_task_completion",
        _fake_verify,
    )

    result = service.verify_completion(
        "T1",
        ["src/app.py"],
        workflow_id="wf-1",
        task_ref=_task_ref("challenge"),
    )

    assert result.overall_outcome == "passed"
    assert result.challenge_outcome == "passed"
    assert [check.name for check in result.checks] == ["worker-check", "agent-check"]
    assert captured["verification_output"]["status"] == "passed"
    assert captured["verification_output"]["checks"][0]["command"] == VERIFY_COMMAND
    assert captured["verification_output"]["checks"][0]["outcome"] == "passed"
