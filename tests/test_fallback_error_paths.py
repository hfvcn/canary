"""
Tests for explicit error returns on missing params and fallback guard.

RO-27: Missing-params and pool-rejection must return explicit errors,
not silently succeed or auto-approve.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskRef
from cccc.daemon.foreman.agent_pool import TaskAssignment
from cccc.daemon.foreman.workflow import BatchEvaluationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_suggestion(**overrides) -> ReadyBatchSuggestion:
    defaults = dict(
        suggestion_id="s-1",
        workflow_id="wf-1",
        tasks=[TaskRef(id="t1", title="Task 1", type="backend")],
        rationale="test",
        estimated_parallelism=1,
    )
    defaults.update(overrides)
    return ReadyBatchSuggestion(**defaults)


def _make_orchestrator(tmp_path: Path):
    """Build a minimal WorkflowOrchestrator for testing."""
    from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

    old_home = os.environ.get("CCCC_HOME")
    os.environ["CCCC_HOME"] = str(tmp_path)
    try:
        orch = WorkflowOrchestrator(
            project_root=tmp_path,
            group_id="test-fallback-group",
        )
    finally:
        if old_home is None:
            os.environ.pop("CCCC_HOME", None)
        else:
            os.environ["CCCC_HOME"] = old_home
    return orch


# ---------------------------------------------------------------------------
# 1) _try_process_batch returns status="error" for missing params
# ---------------------------------------------------------------------------

class TestMissingParamsReturnsError:
    """_try_process_batch must return status='error' (not 'skipped') when
    required parameters are absent."""

    def test_missing_params_returns_error(self):
        from cccc.daemon.ralph_ipc_handler import _try_process_batch

        suggestion = _make_suggestion()
        result = _try_process_batch(suggestion, {})
        assert result is not None
        assert result["status"] == "error"
        assert "missing" in result["reason"].lower()

    def test_missing_group_returns_error(self):
        from cccc.daemon.ralph_ipc_handler import _try_process_batch

        suggestion = _make_suggestion()
        result = _try_process_batch(suggestion, {"group_id": "", "project_root": "/tmp"})
        assert result is not None
        assert result["status"] == "error"
        assert "missing" in result["reason"].lower()

    def test_orchestrator_not_available_returns_error(self):
        from cccc.daemon.ralph_ipc_handler import _try_process_batch

        suggestion = _make_suggestion()
        with patch(
            "cccc.daemon.ralph_ipc_handler._resolve_group_project_root",
            return_value="/tmp/fake",
        ), patch(
            "cccc.daemon.foreman.workflow_orchestrator.get_orchestrator",
            return_value=None,
        ):
            result = _try_process_batch(
                suggestion,
                {"group_id": "g1", "project_root": "/tmp/fake"},
            )
        assert result is not None
        assert result["status"] == "error"
        assert "orchestrator" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 2) Outer handler surfaces the error instead of wrapping in "ok"
# ---------------------------------------------------------------------------

class TestOuterHandlerSurfacesError:
    """handle_ralph_batch_suggest must propagate errors from
    _try_process_batch instead of wrapping them in ok=True."""

    def test_batch_suggest_surfaces_processing_error(self):
        from cccc.daemon.ralph_ipc_handler import handle_ralph_batch_suggest

        args = {
            "workflow_id": "wf-1",
            "tasks": [{"id": "t1", "title": "T1", "type": "backend"}],
            "auto_process": True,
            # missing group_id / project_root  -> triggers error path
        }
        resp = handle_ralph_batch_suggest(args)
        assert resp.ok is False, f"Expected error response, got ok=True: {resp}"
        assert resp.error is not None
        assert "missing" in resp.error.message.lower()


# ---------------------------------------------------------------------------
# 3) Fallback guard — no silent auto-approve
# ---------------------------------------------------------------------------

class TestFallbackGuard:
    """_fallback_to_group_actors must only run when explicitly authorized."""

    def test_no_silent_fallback(self, tmp_path):
        """When pool rejects and fallback_allowed is NOT set, rejection stands."""
        orch = _make_orchestrator(tmp_path)

        suggestion = _make_suggestion()
        # Ensure fallback_allowed is not set (default)
        assert not getattr(suggestion, "fallback_allowed", False)

        # Create a rejection result
        rejection = BatchEvaluationResult(
            suggestion=suggestion,
            decision="rejected",
            reason="no agents available",
            approved_tasks=[],
            rejected_tasks=list(suggestion.tasks),
        )

        # Patch foreman to return a rejection and provide peer actors
        with patch.object(orch.foreman, "process_batch_suggestion", return_value=rejection), \
             patch.object(orch, "_load_enabled_peer_actors", return_value=[
                 {"id": "actor-1", "title": "A1", "enabled": True, "runtime": "claude"},
             ]), \
             patch.object(orch, "_notify_foreman_task_update"):
            orch._ensure_active_workflow("wf-1")
            result = orch.process_batch_suggestion(suggestion)

        # Rejection must stand — fallback was NOT authorized
        assert result.decision == "rejected"

    def test_explicit_fallback_allowed(self, tmp_path):
        """When fallback_allowed=True and pool rejects, group actors are used."""
        orch = _make_orchestrator(tmp_path)

        suggestion = _make_suggestion()
        # Explicitly authorize fallback (bypass Pydantic extra="forbid")
        object.__setattr__(suggestion, "fallback_allowed", True)

        rejection = BatchEvaluationResult(
            suggestion=suggestion,
            decision="rejected",
            reason="no agents available",
            approved_tasks=[],
            rejected_tasks=list(suggestion.tasks),
        )

        with patch.object(orch.foreman, "process_batch_suggestion", return_value=rejection), \
             patch.object(orch, "_load_enabled_peer_actors", return_value=[
                 {"id": "actor-1", "title": "A1", "enabled": True, "runtime": "claude"},
             ]), \
             patch.object(orch, "_notify_foreman_task_update"):
            orch._ensure_active_workflow("wf-1")
            result = orch.process_batch_suggestion(suggestion)

        # Fallback was authorized — should be approved via group actors
        assert result.decision == "approved"
        assert len(result.approved_tasks) == len(suggestion.tasks)
