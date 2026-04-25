"""T-int: Full integration test across all 13 RO/RA improvements.

Exercises every improvement (T1 through T13) in a cohesive, fast test suite.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from cccc.contracts.v1.ralph_ipc import (
    ReadyBatchSuggestion,
    TaskRef,
    VerificationResult,
    VerificationSpec,
)
from cccc.ralph.models import (
    BatchResult,
    Plan,
    TaskSpec,
    Verification,
    VerificationCovers,
    CheckSpec,
    ValidationIssue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_ref(
    task_id: str = "T1",
    title: str = "Test task",
    claimed_paths: Optional[List[str]] = None,
    verification_mode: str = "ralph",
) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=title,
        type="backend",
        goal_behavior="Do the thing",
        acceptance_criteria="Thing is done",
        claimed_paths=claimed_paths or ["src/foo.py"],
        verification=VerificationSpec(level="unit", command="true"),
        verification_mode=verification_mode,
    )


@pytest.fixture()
def temp_home():
    old_home = os.environ.get("CCCC_HOME")
    with tempfile.TemporaryDirectory() as td:
        os.environ["CCCC_HOME"] = td
        yield Path(td)
    if old_home is None:
        os.environ.pop("CCCC_HOME", None)
    else:
        os.environ["CCCC_HOME"] = old_home


@pytest.fixture()
def group(temp_home):
    from cccc.kernel.group import create_group
    from cccc.kernel.registry import load_registry

    reg = load_registry()
    return create_group(reg, title="v5-int-test", topic="")


# ===========================================================================
# T1 -- RO-29: BatchResult defaults
# ===========================================================================


class TestT1BatchResultDefaults:
    """RO-29: BatchResult().batch_boundary is True, batch_sequence == 0."""

    def test_batch_boundary_default_true(self) -> None:
        br = BatchResult()
        assert br.batch_boundary is True

    def test_batch_sequence_default_zero(self) -> None:
        br = BatchResult()
        assert br.batch_sequence == 0


# ===========================================================================
# T2 -- RO-28: Path overlap unified
# ===========================================================================


class TestT2PathOverlapUnified:
    """RO-28: detect_write_set_conflicts handles parent-child and empty=global."""

    def test_parent_child_overlap(self) -> None:
        from cccc.kernel.claimed_paths import detect_write_set_conflicts

        conflicts = detect_write_set_conflicts([
            {"task_id": "a", "paths": ["src"]},
            {"task_id": "b", "paths": ["src/a.py"]},
        ])
        assert len(conflicts) >= 1
        assert conflicts[0]["task_a"] == "a"
        assert conflicts[0]["task_b"] == "b"

    def test_empty_paths_global_conflict(self) -> None:
        from cccc.kernel.claimed_paths import detect_write_set_conflicts

        conflicts = detect_write_set_conflicts([
            {"task_id": "a", "paths": []},
            {"task_id": "b", "paths": ["src"]},
        ])
        assert len(conflicts) >= 1, "empty paths should be treated as global and conflict with everything"


# ===========================================================================
# T3 -- RO-21: Auto-detect group
# ===========================================================================


class TestT3AutoDetectGroup:
    """RO-21: _auto_detect_group function exists and is callable."""

    def test_function_exists(self) -> None:
        from cccc.ralph.cli import _auto_detect_group

        assert callable(_auto_detect_group)

    def test_returns_none_without_groups(self, temp_home: Path) -> None:
        from cccc.ralph.cli import _auto_detect_group

        result = _auto_detect_group(temp_home)
        assert result is None


# ===========================================================================
# T4 -- RO-25: Verification skipped = FAILED
# ===========================================================================


class TestT4VerificationSkippedFailed:
    """RO-25: record_verification_result with outcome=skipped -> FAILED."""

    def test_skipped_becomes_failed(self, group) -> None:
        from cccc.kernel.workflow_state_engine import WorkflowEngine
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        engine = WorkflowEngine(group)
        task = _make_task_ref("T-skip", claimed_paths=["src/skip.py"])
        workflow_id = "wf-skip-test"

        engine.register_task(task, workflow_id)
        engine.register_batch("batch-skip", ["T-skip"])
        engine.approve_batch("batch-skip", [
            {"task_id": "T-skip", "agent_id": "agent-1", "claimed_paths": ["src/skip.py"]},
        ])
        engine.report_worker_started("T-skip", "agent-1")
        engine.report_worker_completion("T-skip", {"result": "done"})

        # Now task is in VERIFYING
        state = engine.get_task("T-skip")
        assert state is not None
        assert state.status == WorkflowTaskStatus.VERIFYING

        # Record verification as skipped
        vr = VerificationResult(
            verification_id="ver-skip-1",
            workflow_id=workflow_id,
            task_id="T-skip",
            overall_outcome="skipped",
            checks=[],
            warnings=[],
            summary="verification skipped",
        )
        engine.record_verification_result("T-skip", vr)

        state = engine.get_task("T-skip")
        assert state is not None
        assert state.status == WorkflowTaskStatus.FAILED, (
            f"Expected FAILED after skipped verification, got {state.status.value}"
        )


# ===========================================================================
# T5 -- RO-27: Fallback errors
# ===========================================================================


class TestT5FallbackErrors:
    """RO-27: _try_process_batch empty args -> error; fallback_allowed default."""

    def test_try_process_batch_empty_args_returns_error_or_skipped(self) -> None:
        from cccc.daemon.ralph_ipc_handler import _try_process_batch

        suggestion = ReadyBatchSuggestion(
            suggestion_id="test-fallback",
            workflow_id="wf-fallback",
            tasks=[],
        )
        result = _try_process_batch(suggestion, {})
        assert result is not None
        assert result["status"] in ("error", "skipped"), (
            f"Expected error or skipped, got {result['status']}"
        )

    def test_ready_batch_suggestion_fallback_allowed_default(self) -> None:
        rbs = ReadyBatchSuggestion(
            suggestion_id="test-default",
            workflow_id="wf-default",
        )
        assert rbs.fallback_allowed is False


# ===========================================================================
# T6 -- RO-24: Cross-scope detection
# ===========================================================================


class TestT6CrossScopeDetection:
    """RO-24: verification command referencing another task's path -> W_VERIFICATION_CROSS_SCOPE."""

    def test_cross_scope_warning_emitted(self) -> None:
        from cccc.ralph.validation_rules.coverage import _check_verification_cross_scope

        plan = Plan(
            tasks=[
                TaskSpec(
                    id="T1",
                    title="Frontend",
                    claimed_paths=["frontend/"],
                    verification=Verification(
                        level="unit",
                        command="pytest backend/tests/",
                    ),
                ),
                TaskSpec(
                    id="T2",
                    title="Backend",
                    claimed_paths=["backend/"],
                    verification=Verification(
                        level="unit",
                        command="pytest backend/tests/test_api.py",
                    ),
                ),
            ],
        )

        issues = _check_verification_cross_scope(plan)
        cross_scope_issues = [i for i in issues if i.code == "W_VERIFICATION_CROSS_SCOPE"]
        assert len(cross_scope_issues) >= 1, (
            f"Expected at least one W_VERIFICATION_CROSS_SCOPE, got {[i.code for i in issues]}"
        )
        # The offending task should be T1 (its verification references backend/)
        assert "T1" in cross_scope_issues[0].task_ids


# ===========================================================================
# T7 -- RO-30: Stubs removed
# ===========================================================================


class TestT7StubsRemoved:
    """RO-30: RalphService has no merge_worktree/analyze_import_graph/detect_test_impact."""

    def test_no_merge_worktree(self) -> None:
        from cccc.daemon.foreman.ralph_service import RalphService

        assert not hasattr(RalphService, "merge_worktree"), (
            "RO-30 violation: RalphService still has merge_worktree"
        )

    def test_no_analyze_import_graph(self) -> None:
        from cccc.daemon.foreman.ralph_service import RalphService

        assert not hasattr(RalphService, "analyze_import_graph"), (
            "RO-30 violation: RalphService still has analyze_import_graph"
        )

    def test_no_detect_test_impact(self) -> None:
        from cccc.daemon.foreman.ralph_service import RalphService

        assert not hasattr(RalphService, "detect_test_impact"), (
            "RO-30 violation: RalphService still has detect_test_impact"
        )


# ===========================================================================
# T8 -- RA-2: Beyond-scope checklist
# ===========================================================================


class TestT8BeyondScopeChecklist:
    """RA-2: Checklist file exists and loads; beyond_scope field on ValidationIssue."""

    def test_checklist_file_exists(self) -> None:
        checklist_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"
        )
        assert checklist_path.exists(), f"Checklist not found at {checklist_path}"

    def test_checklist_loads_with_items(self) -> None:
        import yaml

        checklist_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"
        )
        with checklist_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        items = data.get("items", [])
        assert len(items) > 0, "Checklist has no items"
        # Verify each item has required fields
        for item in items:
            assert "id" in item, f"Checklist item missing 'id': {item}"
            assert "description" in item, f"Checklist item missing 'description': {item}"

    def test_beyond_scope_field_on_validation_issue(self) -> None:
        issue = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
            beyond_scope=True,
        )
        assert issue.beyond_scope is True

        issue_default = ValidationIssue(
            code="E_TEST",
            severity="error",
            message="test",
        )
        assert issue_default.beyond_scope is False


# ===========================================================================
# T9 -- RA-3: Verification mode routing
# ===========================================================================


class TestT9VerificationModeRouting:
    """RA-3: VerificationResult accepts 'agent_pending' outcome."""

    def test_agent_pending_outcome(self) -> None:
        vr = VerificationResult(
            verification_id="ver-agent-1",
            workflow_id="wf-agent",
            task_id="T1",
            overall_outcome="agent_pending",
            checks=[],
            warnings=[],
            summary="Agent verification requested",
        )
        assert vr.overall_outcome == "agent_pending"

    def test_agent_pending_keeps_verifying_status(self, group) -> None:
        from cccc.kernel.workflow_state_engine import WorkflowEngine
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        engine = WorkflowEngine(group)
        task = _make_task_ref("T-agent", claimed_paths=["src/agent.py"], verification_mode="agent")
        workflow_id = "wf-agent-test"

        engine.register_task(task, workflow_id)
        engine.register_batch("batch-agent", ["T-agent"])
        engine.approve_batch("batch-agent", [
            {"task_id": "T-agent", "agent_id": "agent-1", "claimed_paths": ["src/agent.py"]},
        ])
        engine.report_worker_started("T-agent", "agent-1")
        engine.report_worker_completion("T-agent", {"result": "done"})

        # Record agent_pending verification
        vr = VerificationResult(
            verification_id="ver-agent-2",
            workflow_id=workflow_id,
            task_id="T-agent",
            overall_outcome="agent_pending",
            checks=[],
            warnings=[],
            summary="Agent verification pending",
        )
        engine.record_verification_result("T-agent", vr)

        # Task should stay in VERIFYING (not transition to COMPLETED or FAILED)
        state = engine.get_task("T-agent")
        assert state is not None
        assert state.status == WorkflowTaskStatus.VERIFYING, (
            f"Expected VERIFYING after agent_pending, got {state.status.value}"
        )


# ===========================================================================
# T10 -- RO-26: State consolidation
# ===========================================================================


class TestT10StateConsolidation:
    """RO-26: RalphService has no _task_statuses; _RALPH_STATE TTL cleanup exists."""

    def test_no_task_statuses_attribute(self, tmp_path: Path) -> None:
        from cccc.daemon.foreman.ralph_service import RalphService

        service = RalphService(project_root=tmp_path, group_id="test-group")
        assert not hasattr(service, "_task_statuses"), (
            "RO-26 violation: _task_statuses still exists on RalphService"
        )

    def test_cleanup_stale_ralph_state_exists(self) -> None:
        from cccc.daemon.ralph_ipc_handler import _cleanup_stale_ralph_state

        assert callable(_cleanup_stale_ralph_state)

    def test_cleanup_removes_stale_entries(self) -> None:
        from cccc.daemon.ralph_ipc_handler import (
            _RALPH_STATE,
            _cleanup_stale_ralph_state,
        )

        original = {k: dict(v) for k, v in _RALPH_STATE.items()}
        try:
            _RALPH_STATE["pending_suggestions"]["stale-int"] = {
                "_created_at": time.time() - 600,
                "workflow_id": "wf-stale",
            }
            _RALPH_STATE["pending_suggestions"]["fresh-int"] = {
                "_created_at": time.time(),
                "workflow_id": "wf-fresh",
            }

            removed = _cleanup_stale_ralph_state(ttl_seconds=300)
            assert removed >= 1
            assert "stale-int" not in _RALPH_STATE["pending_suggestions"]
            assert "fresh-int" in _RALPH_STATE["pending_suggestions"]
        finally:
            for k in _RALPH_STATE:
                _RALPH_STATE[k] = original.get(k, {})


# ===========================================================================
# T11 -- RO-31: Module split
# ===========================================================================


class TestT11ModuleSplit:
    """RO-31: validation_rules, prompt_builder, admission modules importable."""

    def test_validation_rules_get_all_rules(self) -> None:
        from cccc.ralph.validation_rules import get_all_rules

        rules = get_all_rules()
        assert len(rules) > 0, "get_all_rules() returned empty list"
        for rule in rules:
            assert callable(rule), f"Rule {rule} is not callable"

    def test_prompt_builder_prompt_budget(self) -> None:
        from cccc.daemon.foreman.prompt_builder import PromptBudget

        pb = PromptBudget(budget=1000)
        assert pb.budget == 1000

    def test_admission_split_single_writer_tasks(self) -> None:
        from cccc.daemon.foreman.admission import split_single_writer_tasks

        assert callable(split_single_writer_tasks)


# ===========================================================================
# T12 -- RA-4: Two-phase split (BatchResult.task_summaries)
# ===========================================================================


class TestT12TwoPhaseSplit:
    """RA-4: BatchResult has task_summaries field."""

    def test_task_summaries_field_exists(self) -> None:
        br = BatchResult()
        assert hasattr(br, "task_summaries")
        assert br.task_summaries == {}

    def test_task_summaries_populated(self) -> None:
        br = BatchResult(
            ready=["T1", "T2"],
            task_summaries={"T1": "Implement auth", "T2": "Add tests"},
        )
        assert br.task_summaries["T1"] == "Implement auth"
        assert br.task_summaries["T2"] == "Add tests"


# ===========================================================================
# T13 -- RA-1: Ralph Agent
# ===========================================================================


class TestT13RalphAgent:
    """RA-1: RalphAgent, AgentSuggestion, create_agent importable and functional."""

    def test_imports(self) -> None:
        from cccc.ralph.agent import RalphAgent, AgentSuggestion, create_agent

        assert callable(create_agent)
        assert RalphAgent is not None
        assert AgentSuggestion is not None

    def test_agent_suggestion_advisory_default(self) -> None:
        from cccc.ralph.agent import AgentSuggestion

        suggestion = AgentSuggestion(
            issue_id="test-1",
            checklist_item_id="RV-15",
            suggestion="Review this",
        )
        assert suggestion.advisory is True

    def test_create_agent_with_checklist(self) -> None:
        from cccc.ralph.agent import create_agent

        checklist_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"
        )
        agent = create_agent(checklist_path)
        assert agent.available is True

    def test_agent_reviews_beyond_scope_issues(self) -> None:
        from cccc.ralph.agent import create_agent

        checklist_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "cccc" / "ralph" / "beyond_scope_checklist.yaml"
        )
        agent = create_agent(checklist_path)

        issues = [
            ValidationIssue(
                code="W_VERIFICATION_CROSS_SCOPE",
                severity="warning",
                message="cross-scope check",
                beyond_scope=True,
                issue_instance_id="inst-1",
            ),
            ValidationIssue(
                code="E_DUPLICATE_TASK_ID",
                severity="error",
                message="duplicate id",
                beyond_scope=False,
            ),
        ]

        suggestions = agent.review_beyond_scope(issues)
        # Only the beyond_scope issue should produce a suggestion
        assert len(suggestions) == 1
        assert suggestions[0].advisory is True
        assert suggestions[0].issue_id == "inst-1"
