"""Tests for RA-3 verification_mode routing in ralph_service + validator."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationResult, VerificationSpec
from cccc.daemon.foreman.ralph_service import RalphService
from cccc.ralph.models import (
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    ValidationIssue,
)
from cccc.ralph.validator import validate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task_ref(task_id: str, *, verification_mode: str = "ralph", with_verification: bool = True) -> TaskRef:
    verification = None
    if with_verification:
        verification = VerificationSpec(
            level="unit",
            command="true",
            checks=[{"name": "build", "command": "true", "required": True, "expected_exit_code": 0}],
            covers_tasks=[task_id],
        )
    return TaskRef(
        id=task_id,
        title=f"Task {task_id}",
        claimed_paths=[f"src/{task_id.lower()}.py"],
        verification=verification,
        verification_mode=verification_mode,
    )


def _task_spec(task_id: str, *, verification_mode: str = "ralph") -> TaskSpec:
    return TaskSpec(
        id=task_id,
        claimed_paths=[f"src/{task_id.lower()}.py"],
        verification=Verification(
            level="unit",
            command="true",
            covers=VerificationCovers(tasks=[task_id]),
        ),
        verification_mode=verification_mode,
    )


def _make_ralph_service(tmp_path: Path) -> RalphService:
    return RalphService(project_root=tmp_path, group_id="test-group")


def _agent_completed(passed: bool = True) -> subprocess.CompletedProcess[str]:
    payload = {
        "passed": passed,
        "summary": "agent simulation result",
        "checks": [{"name": "foreman_case", "outcome": "passed" if passed else "failed"}],
    }
    return subprocess.CompletedProcess(
        args=["gemini"],
        returncode=0,
        stdout=json.dumps({"response": json.dumps(payload)}),
        stderr="",
    )


# ---------------------------------------------------------------------------
# ralph_service.verify_completion routing tests
# ---------------------------------------------------------------------------

class TestVerifyCompletionRouting:
    """Tests that verify_completion routes based on verification_mode."""

    def test_ralph_mode_uses_existing_path(self, tmp_path: Path) -> None:
        svc = _make_ralph_service(tmp_path)
        task = _task_ref("T1", verification_mode="ralph")
        result = svc.verify_completion(
            "T1", [], workflow_id="wf-1", task_ref=task,
        )
        assert isinstance(result, VerificationResult)
        # ralph mode should actually run checks (or skip if no command runs)
        assert result.overall_outcome != "agent_pending"

    def test_agent_mode_runs_agent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "cccc.ralph.agent.subprocess.run",
            lambda command, **kwargs: _agent_completed(True),
        )
        svc = _make_ralph_service(tmp_path)
        task = _task_ref("T1", verification_mode="agent")
        result = svc.verify_completion(
            "T1", [], workflow_id="wf-1", task_ref=task,
        )
        assert isinstance(result, VerificationResult)
        assert result.overall_outcome == "passed"
        assert result.summary == "agent simulation result"
        assert result.task_id == "T1"
        assert result.workflow_id == "wf-1"

    def test_default_mode_is_ralph(self, tmp_path: Path) -> None:
        """TaskRef without explicit verification_mode defaults to ralph."""
        task = TaskRef(id="T1", claimed_paths=["src/t1.py"])
        assert task.verification_mode == "ralph"

        svc = _make_ralph_service(tmp_path)
        result = svc.verify_completion(
            "T1", [], workflow_id="wf-1", task_ref=task,
        )
        assert result.overall_outcome != "agent_pending"

    def test_agent_mode_does_not_run_checks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent mode must not call _execute_verification_checks."""
        monkeypatch.setattr(
            "cccc.ralph.agent.subprocess.run",
            lambda command, **kwargs: _agent_completed(True),
        )
        svc = _make_ralph_service(tmp_path)
        task = _task_ref("T1", verification_mode="agent")

        with patch.object(svc, "_execute_verification_checks") as mock_exec:
            result = svc.verify_completion(
                "T1", [], workflow_id="wf-1", task_ref=task,
            )
        mock_exec.assert_not_called()
        assert result.overall_outcome == "passed"

    def test_agent_mode_keeps_scope_warnings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent mode still reports worker changes outside claimed_paths."""
        monkeypatch.setattr(
            "cccc.ralph.agent.subprocess.run",
            lambda command, **kwargs: _agent_completed(True),
        )
        svc = _make_ralph_service(tmp_path)
        task = _task_ref("T1", verification_mode="agent")

        result = svc.verify_completion(
            "T1", ["some/file.py"], workflow_id="wf-1", task_ref=task,
        )

        assert result.overall_outcome == "passed"
        assert result.warnings


# ---------------------------------------------------------------------------
# Validator: W_UNKNOWN_VERIFICATION_MODE
# ---------------------------------------------------------------------------

class TestUnknownVerificationModeValidator:

    def test_valid_modes_no_warning(self) -> None:
        """Both 'ralph' and 'agent' are valid — no W_UNKNOWN_VERIFICATION_MODE."""
        plan = Plan(tasks=[
            _task_spec("T1", verification_mode="ralph"),
            _task_spec("T2", verification_mode="agent"),
        ])
        report = validate(plan)
        codes = [i.code for i in report.warnings]
        assert "W_UNKNOWN_VERIFICATION_MODE" not in codes

    def test_unknown_mode_triggers_warning(self) -> None:
        """An invalid verification_mode should produce W_UNKNOWN_VERIFICATION_MODE."""
        # TaskSpec has Literal["ralph", "agent"] so pydantic will reject invalid
        # values at model creation. To test the validator, we need to bypass that.
        task = _task_spec("T1", verification_mode="ralph")
        # Force the field to an invalid value after construction
        object.__setattr__(task, "verification_mode", "invalid_mode")

        plan = Plan(tasks=[task])
        report = validate(plan)
        matching = [i for i in report.warnings if i.code == "W_UNKNOWN_VERIFICATION_MODE"]
        assert len(matching) == 1
        issue = matching[0]
        assert "T1" in issue.message
        assert issue.evidence["task_id"] == "T1"
        assert issue.evidence["verification_mode"] == "invalid_mode"


# ---------------------------------------------------------------------------
# VerificationOutcome type includes agent_pending
# ---------------------------------------------------------------------------

def test_verification_result_accepts_agent_pending() -> None:
    """VerificationResult should accept 'agent_pending' as overall_outcome."""
    result = VerificationResult(
        verification_id="ver-test",
        workflow_id="wf-1",
        task_id="T1",
        overall_outcome="agent_pending",
        checks=[],
        summary="agent pending",
    )
    assert result.overall_outcome == "agent_pending"
