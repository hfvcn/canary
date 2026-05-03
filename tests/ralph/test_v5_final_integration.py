from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.filesystem_validator import (
    _build_indirect_gap_issues,
    validate_filesystem,
)
from cccc.ralph.models import Plan
from cccc.ralph.workspace_index import WorkspaceIndex


VERIFY_COMMAND = 'python -c "print(\'ok\')"'
FOLD_THRESHOLD_COUNT = 12


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
        id="T-int",
        title="V5 final integration",
        goal_behavior="Verify v5 final fixes interact correctly.",
        acceptance_criteria="agent receives full evidence and validators stay precise.",
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
            covers_tasks=["T-int"],
        ),
    )


def _shell_plan(command: str) -> Plan:
    return Plan.model_validate({
        "tasks": [{
            "id": "T-int",
            "verification": {
                "level": "unit",
                "command": command,
                "covers": {"tasks": ["T-int"]},
            },
        }],
    })


def test_evidence_injection_challenge_mode_passes_all_agent_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    _write(tmp_path / "src" / "app.py", "VALUE = 2\n")
    service = RalphService(project_root=tmp_path, group_id="test-group")
    captured: dict[str, Any] = {}

    def _unexpected_precheck(task_ref: TaskRef) -> dict[str, Any]:
        raise AssertionError("challenge mode should reuse worker verification output")

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
        "T-int",
        ["src/app.py"],
        workflow_id="wf-1",
        task_ref=_task_ref("challenge"),
    )

    assert result.overall_outcome == "passed"
    assert result.challenge_outcome == "passed"
    assert [check.name for check in result.checks] == ["worker-check", "agent-check"]
    assert "VALUE = 2" in captured["source_context"]["src/app.py"]
    assert "VALUE = 1" in captured["git_diff"]
    assert "VALUE = 2" in captured["git_diff"]
    assert captured["verification_output"]["status"] == "passed"
    assert captured["verification_output"]["checks"][0]["command"] == VERIFY_COMMAND
    assert captured["verification_output"]["checks"][0]["outcome"] == "passed"


def test_shell_split_checks_each_subcommand_without_complex_skip(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "tests" / "test_a.py", "def test_a():\n    assert True\n")
    workspace = WorkspaceIndex(tmp_path)

    issues = validate_filesystem(
        _shell_plan("pytest tests/test_a.py && pytest tests/test_b.py"),
        project_root=tmp_path,
        workspace=workspace,
    )

    issue_codes = [issue.code for issue in issues]
    assert "W_VERIFICATION_COMPLEX_SHELL_SKIPPED" not in issue_codes
    assert "W_VERIFICATION_TARGET_MISSING" in issue_codes
    assert any(issue.evidence.get("target") == "tests/test_b.py" for issue in issues)


def test_indirect_gap_issues_fold_to_one_summary() -> None:
    issues = _build_indirect_gap_issues({
        ("T-int", f"src/foo_{index}.py"): [f"tests/test_group_{index}.py"]
        for index in range(FOLD_THRESHOLD_COUNT)
    })

    assert len(issues) == 1
    assert issues[0].code == "W_INDIRECT_TEST_IMPORT"
    assert issues[0].severity == "hint"
    assert issues[0].evidence["total_hints"] == FOLD_THRESHOLD_COUNT
    assert len(issues[0].evidence["samples"]) == 5
    assert "12 indirect test import hint(s)" in issues[0].message
