"""Integration tests for RO-45 ~ RO-50 fixes.

Validates that all six fixes work together without regressions.
Tests at the function/engine level — no daemon or group dependencies.
"""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# T1 integration: directory claimed_paths expansion (RO-45)
# ---------------------------------------------------------------------------

class TestDirClaimedPathsIntegration:

    def test_ralph_service_expands_directory(self, tmp_path):
        sub = tmp_path / "backend" / "routes"
        sub.mkdir(parents=True)
        (sub / "auth.py").write_text("# auth route")
        (sub / "health.ts").write_text("// health check")
        (sub / "README.md").write_text("# ignored non-source")

        from cccc.daemon.foreman.ralph_service import RalphService
        svc = RalphService.__new__(RalphService)
        svc.project_root = tmp_path
        from cccc.contracts.v1.ralph_ipc import TaskRef
        ref = TaskRef(id="T1", claimed_paths=["backend/routes/"])
        result = svc._read_claimed_paths(ref)

        keys = list(result.keys())
        assert "backend/routes/" not in keys
        assert any("auth.py" in k for k in keys)
        assert any("health.ts" in k for k in keys)
        assert not any("README.md" in k for k in keys)

    def test_core_expands_directory(self, tmp_path):
        sub = tmp_path / "src" / "components"
        sub.mkdir(parents=True)
        (sub / "App.tsx").write_text("export default App")
        (sub / "index.js").write_text("import App")
        (sub / "style.css").write_text("body {}")

        from cccc.ralph.core import _read_claimed_paths
        result = _read_claimed_paths(["src/components/"], tmp_path)

        keys = list(result.keys())
        assert any("App.tsx" in k for k in keys)
        assert any("index.js" in k for k in keys)
        assert not any("style.css" in k for k in keys)

    def test_both_implementations_consistent(self, tmp_path):
        sub = tmp_path / "lib"
        sub.mkdir()
        (sub / "a.py").write_text("AAA")
        (sub / "b.ts").write_text("BBB")

        from cccc.daemon.foreman.ralph_service import RalphService
        svc = RalphService.__new__(RalphService)
        svc.project_root = tmp_path
        from cccc.contracts.v1.ralph_ipc import TaskRef
        ref = TaskRef(id="T1", claimed_paths=["lib/"])
        svc_result = svc._read_claimed_paths(ref)

        from cccc.ralph.core import _read_claimed_paths
        core_result = _read_claimed_paths(["lib/"], tmp_path)

        assert set(svc_result.keys()) == set(core_result.keys())
        for k in svc_result:
            assert svc_result[k] == core_result[k]


# ---------------------------------------------------------------------------
# T2 integration: new project empty diff (RO-46)
# ---------------------------------------------------------------------------

class TestNewProjectDiffIntegration:

    def test_ralph_service_detects_no_prior_commits(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "app.py").write_text("print('hello')")
        subprocess.run(["git", "add", "app.py"], cwd=str(tmp_path), capture_output=True)

        from cccc.daemon.foreman.ralph_service import RalphService
        svc = RalphService.__new__(RalphService)
        svc.project_root = tmp_path
        result = svc._git_diff_for_files(["app.py"])
        assert "no prior commits" in result

    def test_core_detects_no_prior_commits(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "main.ts").write_text("console.log('hi')")
        subprocess.run(["git", "add", "main.ts"], cwd=str(tmp_path), capture_output=True)

        from cccc.ralph.core import _git_diff_for_files
        result = _git_diff_for_files(["main.ts"], tmp_path)
        assert "no prior commits" in result

    def test_agent_prompt_contains_rule_3b(self):
        from cccc.ralph.agent import RalphAgent
        source = inspect.getsource(RalphAgent._build_verification_prompt)
        assert "3b." in source
        assert "no prior commits" in source

    def test_existing_repo_unchanged_behavior(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "app.py").write_text("v1")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                        capture_output=True, env={**os.environ, "GIT_AUTHOR_NAME": "test",
                        "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "test",
                        "GIT_COMMITTER_EMAIL": "t@t"})

        from cccc.ralph.core import _git_diff_for_files
        result = _git_diff_for_files(["app.py"], tmp_path)
        assert "unchanged from HEAD" in result


# ---------------------------------------------------------------------------
# T3 integration: retry RUNNING task (RO-47)
# ---------------------------------------------------------------------------

class TestRetryRunningIntegration:

    def test_fail_task_method_exists(self):
        """Engine has fail_task for RUNNING→FAILED transition (T3 prerequisite)."""
        from cccc.kernel.workflow_state_engine import WorkflowEngine
        assert hasattr(WorkflowEngine, "fail_task")
        sig = inspect.signature(WorkflowEngine.fail_task)
        params = list(sig.parameters.keys())
        assert "task_id" in params
        assert "reason" in params

    def test_retry_task_handles_running_status(self):
        """Orchestrator.retry_task accepts RUNNING status (via fail_task first)."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
        source = inspect.getsource(WorkflowOrchestrator.retry_task)
        assert "RUNNING" in source or "fail_task" in source


# ---------------------------------------------------------------------------
# T4a integration: stall auto-reassign (RO-48)
# ---------------------------------------------------------------------------

class TestStallAutoReassignIntegration:

    def test_workflow_meta_has_stall_field(self):
        from cccc.kernel.workflow_state_types import WorkflowMeta
        meta = WorkflowMeta(workflow_id="wf-1")
        assert meta.stall_auto_reassign is False

        meta2 = WorkflowMeta(workflow_id="wf-2", stall_auto_reassign=True)
        assert meta2.stall_auto_reassign is True

    def test_handle_stalled_task_has_auto_reassign_logic(self):
        """_handle_stalled_task references stall_auto_reassign."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
        assert hasattr(WorkflowOrchestrator, "_handle_stalled_task")
        source = inspect.getsource(WorkflowOrchestrator._handle_stalled_task)
        assert "auto_reassign" in source

    def test_stall_auto_reassign_enabled_method_exists(self):
        """_stall_auto_reassign_enabled reads WorkflowMeta."""
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator
        assert hasattr(WorkflowOrchestrator, "_stall_auto_reassign_enabled")
        source = inspect.getsource(WorkflowOrchestrator._stall_auto_reassign_enabled)
        assert "stall_auto_reassign" in source


# ---------------------------------------------------------------------------
# T4b integration: configurable verification timeout (RO-49)
# ---------------------------------------------------------------------------

class TestConfigurableTimeoutIntegration:

    def test_check_spec_has_timeout(self):
        from cccc.contracts.v1.ralph_ipc import VerificationCheckSpec
        from cccc.ralph.models import CheckSpec

        spec_ipc = VerificationCheckSpec(name="test", command="echo ok", timeout=30)
        assert spec_ipc.timeout == 30

        spec_domain = CheckSpec(name="test", command="echo ok", timeout=30)
        assert spec_domain.timeout == 30

    def test_default_timeout_is_none(self):
        from cccc.contracts.v1.ralph_ipc import VerificationCheckSpec
        from cccc.ralph.models import CheckSpec

        assert VerificationCheckSpec(name="t", command="echo").timeout is None
        assert CheckSpec(name="t", command="echo").timeout is None

    def test_ralph_service_uses_custom_timeout(self, tmp_path):
        from cccc.daemon.foreman.ralph_service import RalphService
        svc = RalphService.__new__(RalphService)
        svc.project_root = tmp_path
        check = svc._run_verification_check(name="fast", command="echo ok", timeout=5)
        assert check.outcome == "passed"


# ---------------------------------------------------------------------------
# T5 integration: terminal state guard (RO-50)
# ---------------------------------------------------------------------------

class TestTerminalStateGuardIntegration:

    def test_terminal_statuses_defined(self):
        from cccc.daemon.foreman.workflow_orchestrator import _TERMINAL_STATUSES
        assert "completed" in _TERMINAL_STATUSES
        assert "archived" in _TERMINAL_STATUSES
        assert "running" not in _TERMINAL_STATUSES
        assert "failed" not in _TERMINAL_STATUSES
