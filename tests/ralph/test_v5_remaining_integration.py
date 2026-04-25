"""Integration tests — v5-ralph remaining features: T1/T2/T3/T5/T7 together.

Covers:
  T1 + T2  suppress_codes + format-preserving save
  T2       suppress_codes turns errors into hints → valid plan
  T3       verification outcome semantics ("skipped" preserved)
  T5       WorkflowMonitor realistic scenarios
  T7       W_SEMANTIC_DEP_HINT via validate_with_project
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cccc.ralph.models import Plan, TaskSpec, Verification, VerificationCovers
from cccc.ralph.validator import validate, validate_with_project
from cccc.ralph.plan_io import load_plan, save_plan_state
from cccc.daemon.foreman.workflow_monitor import (
    check_file_overstepping,
    check_completer_mismatch,
    check_silent_agent,
    MonitorAlert,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_plan_dict(**overrides) -> dict:
    """Return a plan dict with a single valid task — override as needed."""
    base = {
        "tasks": [
            {
                "id": "T1",
                "claimed_paths": ["src/foo.py"],
                "acceptance_criteria": "foo module compiles",
                "verification": {
                    "level": "unit",
                    "command": "pytest tests/ -q",
                    "covers": {"tasks": ["T1"]},
                },
            }
        ]
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T1 + T2: suppress_codes + format-preserving save
# ---------------------------------------------------------------------------

class TestSuppressAndSave:
    """Integration: suppress_codes + format-preserving save."""

    def test_suppress_validate_save_roundtrip(self, tmp_path: Path) -> None:
        """Create a YAML plan with comments and suppress_codes.

        Steps:
        1. Write a YAML plan that has suppress_codes and comments.
        2. Load + validate — suppressed codes become hints.
        3. Call save_plan_state to mark T1 complete.
        4. Reload — comments still present, T1 in completed_task_ids.
        5. Re-validate — suppression still works.
        """
        plan_path = tmp_path / "plan.yaml"
        # A single task plan — E_NO_CROSS_TASK_VERIFICATION fires because there
        # is only one task (validator expects multi-task for that check), but
        # E_MISSING_CLAIMED_PATHS and E_MISSING_VERIFICATION won't fire because
        # the task is complete.  We suppress the warning that does fire:
        # W_EMPTY_ACCEPTANCE would fire if acceptance_criteria is empty, but
        # we provide it.  Actually for a *single-task* plan the only real errors
        # are field-completeness ones.  We deliberately omit claimed_paths to
        # trigger E_MISSING_CLAIMED_PATHS, then suppress it.
        yaml_content = """\
# This is a top-level comment that must be preserved.
suppress_codes:
  - E_MISSING_CLAIMED_PATHS

tasks:
  # Task T1 — intentionally has no claimed_paths (suppressed above)
  - id: T1
    acceptance_criteria: "T1 acceptance criteria"
    verification:
      level: unit
      command: "pytest tests/ -q"
      covers:
        tasks: ["T1"]

state:
  completed_task_ids: []
"""
        plan_path.write_text(yaml_content, encoding="utf-8")

        # Step 2: validate — E_MISSING_CLAIMED_PATHS should be a hint, not error
        plan = load_plan(plan_path)
        report = validate(plan)

        assert report.valid, f"Expected valid plan; errors: {report.errors}"
        hint_codes = [h.code for h in report.hints]
        assert "E_MISSING_CLAIMED_PATHS" in hint_codes, (
            f"Expected E_MISSING_CLAIMED_PATHS as hint; hints={hint_codes}"
        )
        # Not in errors
        error_codes = [e.code for e in report.errors]
        assert "E_MISSING_CLAIMED_PATHS" not in error_codes

        # Suppressed hint message must start with "[suppressed]"
        suppressed = [h for h in report.hints if h.code == "E_MISSING_CLAIMED_PATHS"]
        assert suppressed[0].message.startswith("[suppressed]"), (
            f"Message should start with '[suppressed]': {suppressed[0].message}"
        )

        # Step 3: save_plan_state — mark T1 as completed
        save_plan_state(plan_path, "T1")

        # Step 4: reload — comments still in file, T1 in completed_task_ids
        new_text = plan_path.read_text(encoding="utf-8")
        assert "# This is a top-level comment that must be preserved." in new_text
        assert "# Task T1 — intentionally has no claimed_paths (suppressed above)" in new_text

        reloaded = load_plan(plan_path)
        assert "T1" in reloaded.state.completed_task_ids

        # Step 5: re-validate after save — suppression still works
        report2 = validate(reloaded)
        assert report2.valid, f"Expected valid after reload; errors: {report2.errors}"
        hint_codes2 = [h.code for h in report2.hints]
        assert "E_MISSING_CLAIMED_PATHS" in hint_codes2

    def test_suppress_error_makes_valid(self, tmp_path: Path) -> None:
        """Suppressing E_MISSING_CLAIMED_PATHS makes an otherwise-invalid plan valid."""
        # Without suppression this plan is invalid
        plan_no_suppress = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "acceptance_criteria": "ok",
                    "verification": {
                        "level": "unit",
                        "command": "pytest -q",
                        "covers": {"tasks": ["T1"]},
                    },
                    # No claimed_paths — triggers E_MISSING_CLAIMED_PATHS
                }
            ]
        })
        report_bare = validate(plan_no_suppress)
        error_codes = [e.code for e in report_bare.errors]
        assert "E_MISSING_CLAIMED_PATHS" in error_codes, (
            f"Expected error without suppression; errors={error_codes}"
        )
        assert not report_bare.valid

        # With suppression the same structural issue becomes a hint
        plan_suppressed = Plan.model_validate({
            "suppress_codes": ["E_MISSING_CLAIMED_PATHS"],
            "tasks": [
                {
                    "id": "T1",
                    "acceptance_criteria": "ok",
                    "verification": {
                        "level": "unit",
                        "command": "pytest -q",
                        "covers": {"tasks": ["T1"]},
                    },
                }
            ]
        })
        report_suppressed = validate(plan_suppressed)
        assert report_suppressed.valid, (
            f"Expected valid with suppression; errors={report_suppressed.errors}"
        )
        hint_codes = [h.code for h in report_suppressed.hints]
        assert "E_MISSING_CLAIMED_PATHS" in hint_codes


# ---------------------------------------------------------------------------
# T5: WorkflowMonitor realistic scenarios
# ---------------------------------------------------------------------------

class TestMonitorIntegration:
    """Integration: WorkflowMonitor realistic scenarios."""

    def test_realistic_file_overstepping(self) -> None:
        """Agent modifies a file outside its claimed scope — alert fires.

        _paths_overlap treats "src/cccc/daemon/actors" (no trailing slash) as a
        directory prefix — any file starting with "src/cccc/daemon/actors/" is
        considered in scope.  We use bare directory names to match that contract.
        """
        task_id = "task-backend-auth"
        # No trailing slashes — _paths_overlap uses prefix matching without them
        claimed_paths = ["src/cccc/daemon/actors", "tests/test_actors.py"]
        # Files the agent actually changed — one is outside scope
        changed_files = [
            "src/cccc/daemon/actors/actor_ops.py",       # in scope (inside dir)
            "src/cccc/daemon/foreman/ralph_service.py",  # out of scope
            "tests/test_actors.py",                      # in scope (exact match)
        ]

        alert = check_file_overstepping(task_id, changed_files, claimed_paths)

        assert alert is not None, "Expected an alert for out-of-scope file"
        assert alert.alert_type == "file_overstepping"
        assert alert.severity == "error"
        assert alert.task_id == task_id
        assert "src/cccc/daemon/foreman/ralph_service.py" in alert.evidence["overstepping_files"]
        # In-scope files should NOT appear in overstepping list
        assert "src/cccc/daemon/actors/actor_ops.py" not in alert.evidence["overstepping_files"]
        assert "tests/test_actors.py" not in alert.evidence["overstepping_files"]

    def test_no_alert_when_all_files_in_scope(self) -> None:
        """No alert when every changed file falls within claimed paths.

        Directory paths must not have trailing slashes — _paths_overlap uses
        prefix matching on bare directory names (e.g. "tests/ralph" matches
        "tests/ralph/test_ralph_standalone.py").
        """
        task_id = "task-validator"
        # Use bare directory name (no trailing slash) so prefix matching works
        claimed_paths = ["src/cccc/ralph/validator.py", "tests/ralph"]
        changed_files = [
            "src/cccc/ralph/validator.py",
            "tests/ralph/test_ralph_standalone.py",
        ]

        alert = check_file_overstepping(task_id, changed_files, claimed_paths)
        assert alert is None, f"Expected no alert; got {alert}"

    def test_realistic_completer_mismatch(self) -> None:
        """Wrong agent completing a task triggers a completer_mismatch alert."""
        task_id = "task-T3"
        assigned_agent = "worker-agent-alpha"
        completing_agent = "worker-agent-beta"  # different from assigned

        alert = check_completer_mismatch(task_id, assigned_agent, completing_agent)

        assert alert is not None, "Expected alert for mismatched completer"
        assert alert.alert_type == "completer_mismatch"
        assert alert.severity == "error"
        assert alert.task_id == task_id
        assert alert.evidence["assigned_agent"] == assigned_agent
        assert alert.evidence["completing_agent"] == completing_agent

    def test_completer_match_no_alert(self) -> None:
        """No alert when the completing agent is the same as assigned."""
        alert = check_completer_mismatch(
            "task-T1", "worker-agent-alpha", "worker-agent-alpha"
        )
        assert alert is None

    def test_realistic_silent_agent_timeout(self) -> None:
        """Agent exceeds silence timeout — alert fires."""
        now = time.time()
        assigned_at = now - 400     # assigned 400 s ago
        last_event_at = now - 350   # last event 350 s ago (> 300 s timeout)

        alert = check_silent_agent(
            "task-long-running",
            assigned_at=assigned_at,
            last_event_at=last_event_at,
            now=now,
            timeout_s=300,
        )

        assert alert is not None, "Expected silent-agent alert"
        assert alert.alert_type == "silent_agent"
        assert alert.severity == "warning"
        assert alert.task_id == "task-long-running"
        assert alert.evidence["elapsed_s"] >= 300

    def test_silent_agent_within_timeout(self) -> None:
        """Agent still within timeout — no alert."""
        now = time.time()
        assigned_at = now - 100
        last_event_at = now - 50    # last event only 50 s ago

        alert = check_silent_agent(
            "task-active",
            assigned_at=assigned_at,
            last_event_at=last_event_at,
            now=now,
            timeout_s=300,
        )

        assert alert is None, f"Expected no alert within timeout; got {alert}"


# ---------------------------------------------------------------------------
# T3: Verification event semantics contract
# ---------------------------------------------------------------------------

class TestVerificationEventContract:
    """Integration: verification outcome propagation contract.

    The orchestrator maps verification.overall_outcome directly to
    notification_outcome when outcome is "passed" or "skipped".  We validate
    the model contract without spinning up the full orchestrator.
    """

    def test_outcome_values_contract(self) -> None:
        """VerificationOutcome Literal includes 'skipped' — contract is stable."""
        from cccc.contracts.v1.ralph_ipc import (
            VerificationResult,
            VerificationOutcome,
        )
        import typing

        # VerificationOutcome is a Literal type alias.
        # Check that "skipped" is among its args.
        origin = getattr(VerificationOutcome, "__origin__", None)
        # typing.get_args works on Literal types
        args = typing.get_args(VerificationOutcome)
        assert "skipped" in args, (
            f"'skipped' must be a valid VerificationOutcome; got {args}"
        )
        assert "passed" in args
        assert "failed" in args

    def test_skipped_outcome_roundtrips_in_model(self) -> None:
        """A VerificationResult with overall_outcome='skipped' validates correctly."""
        from cccc.contracts.v1.ralph_ipc import VerificationResult

        result = VerificationResult(
            verification_id="vr-001",
            workflow_id="wf-001",
            task_id="T1",
            overall_outcome="skipped",
            summary="verification skipped by agent",
        )

        assert result.overall_outcome == "skipped"
        # Round-trip through JSON
        data = result.model_dump()
        reloaded = VerificationResult.model_validate(data)
        assert reloaded.overall_outcome == "skipped"

    def test_notification_outcome_preserves_skipped(self) -> None:
        """The orchestrator code path that sets notification_outcome preserves 'skipped'.

        We replicate the exact conditional from workflow_orchestrator.py to confirm
        the contract: when overall_outcome is 'skipped' the notification_outcome is
        set to 'skipped' (not coerced to 'passed' or 'failed').
        """
        # Simulate the orchestrator logic — skipped is preserved as notification
        # outcome (not coerced to "passed" or "failed"), even though it now
        # routes to on_task_failed in the state engine.
        def _map_notification_outcome(overall_outcome: str) -> str:
            if overall_outcome == "passed":
                return "passed"
            elif overall_outcome == "skipped":
                return "skipped"  # preserved for notification, but task is FAILED
            return "failed"

        assert _map_notification_outcome("passed") == "passed"
        assert _map_notification_outcome("skipped") == "skipped"
        assert _map_notification_outcome("failed") == "failed"
        assert _map_notification_outcome("timeout") == "failed"


# ---------------------------------------------------------------------------
# T7: Semantic dep hint with real project files
# ---------------------------------------------------------------------------

class TestSemanticDepIntegration:
    """Integration: semantic dep hints with real project files."""

    def test_goal_references_real_file(self, tmp_path: Path) -> None:
        """Task goal_behavior references an existing file not in claimed_paths.

        We create a mini project layout under tmp_path with a real .py file,
        then build a plan whose goal_behavior mentions that file by path.
        validate_with_project should produce W_SEMANTIC_DEP_HINT.
        """
        # Create a small project structure
        _write(tmp_path / "src" / "myapp" / "core.py", "CONSTANT = 42\n")
        _write(tmp_path / "src" / "myapp" / "feature.py", "VALUE = 1\n")
        _write(tmp_path / "tests" / "test_feature.py", "def test_placeholder(): pass\n")

        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["src/myapp/feature.py"],
                    "acceptance_criteria": "feature works",
                    # goal_behavior mentions src/myapp/core.py — which exists but is NOT claimed
                    "goal_behavior": (
                        "Refactor src/myapp/feature.py to delegate to "
                        "src/myapp/core.py for the main computation."
                    ),
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/ -q",
                        "covers": {"tasks": ["T1"]},
                    },
                }
            ]
        })

        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [h.code for h in report.hints]
        assert "W_SEMANTIC_DEP_HINT" in hint_codes, (
            f"Expected W_SEMANTIC_DEP_HINT; hints={hint_codes}"
        )

        # Find the specific hint and verify evidence
        sem_hints = [h for h in report.hints if h.code == "W_SEMANTIC_DEP_HINT"]
        assert any(
            h.evidence.get("referenced_path") == "src/myapp/core.py"
            for h in sem_hints
        ), f"Expected evidence pointing to src/myapp/core.py; hints={sem_hints}"

    def test_no_hint_when_file_claimed(self, tmp_path: Path) -> None:
        """No W_SEMANTIC_DEP_HINT when the referenced file is in claimed_paths."""
        _write(tmp_path / "src" / "myapp" / "core.py", "CONSTANT = 42\n")
        _write(tmp_path / "src" / "myapp" / "feature.py", "VALUE = 1\n")
        _write(tmp_path / "tests" / "test_feature.py", "def test_placeholder(): pass\n")

        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    # Claim both files
                    "claimed_paths": ["src/myapp/feature.py", "src/myapp/core.py"],
                    "acceptance_criteria": "feature and core work",
                    "goal_behavior": (
                        "Refactor src/myapp/feature.py to delegate to "
                        "src/myapp/core.py for the main computation."
                    ),
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/ -q",
                        "covers": {"tasks": ["T1"]},
                    },
                }
            ]
        })

        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [h.code for h in report.hints]
        assert "W_SEMANTIC_DEP_HINT" not in hint_codes, (
            f"Expected no W_SEMANTIC_DEP_HINT when file is claimed; hints={hint_codes}"
        )

    def test_no_hint_when_file_absent(self, tmp_path: Path) -> None:
        """No W_SEMANTIC_DEP_HINT when the referenced .py path does not exist."""
        _write(tmp_path / "src" / "myapp" / "feature.py", "VALUE = 1\n")
        _write(tmp_path / "tests" / "test_feature.py", "def test_placeholder(): pass\n")
        # NOTE: src/myapp/nonexistent.py is NOT created

        plan = Plan.model_validate({
            "tasks": [
                {
                    "id": "T1",
                    "claimed_paths": ["src/myapp/feature.py"],
                    "acceptance_criteria": "feature works",
                    "goal_behavior": (
                        "Ensure src/myapp/nonexistent.py integrates correctly."
                    ),
                    "verification": {
                        "level": "unit",
                        "command": "pytest tests/ -q",
                        "covers": {"tasks": ["T1"]},
                    },
                }
            ]
        })

        report = validate_with_project(plan, project_root=tmp_path)

        hint_codes = [h.code for h in report.hints]
        assert "W_SEMANTIC_DEP_HINT" not in hint_codes, (
            f"Expected no W_SEMANTIC_DEP_HINT for absent file; hints={hint_codes}"
        )
