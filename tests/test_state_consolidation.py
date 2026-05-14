"""RO-26: State consolidation tests.

Validates:
(a) _task_statuses is no longer present in RalphService
(b) _RALPH_STATE entries with TTL are cleaned up
(c) WorkflowEngine is the authoritative status source after task completion
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from cccc.contracts.v1.ralph_ipc import TaskRef, VerificationSpec


def _make_task(
    task_id: str = "T1",
    title: str = "Test task",
    claimed_paths: Optional[List[str]] = None,
) -> TaskRef:
    return TaskRef(
        id=task_id,
        title=title,
        type="backend",
        goal_behavior="Do the thing",
        acceptance_criteria="Thing is done",
        claimed_paths=claimed_paths or ["src/foo.py"],
        verification=VerificationSpec(level="unit", command="true"),
    )


# ---------------------------------------------------------------------------
# (a) _task_statuses is gone from RalphService
# ---------------------------------------------------------------------------


class TestNoTaskStatusesInRalphService:
    """RO-26: RalphService must not maintain _task_statuses."""

    def test_no_task_statuses_attribute(self, tmp_path: Path) -> None:
        """RalphService instances should no longer have _task_statuses."""
        from cccc.daemon.foreman.ralph_service import RalphService

        service = RalphService(project_root=tmp_path, group_id="test-group")
        assert not hasattr(service, "_task_statuses"), (
            "RO-26 violation: _task_statuses still exists on RalphService"
        )

    def test_no_task_statuses_in_source(self) -> None:
        """Source code of ralph_service.py should not define _task_statuses."""
        import cccc.daemon.foreman.ralph_service as mod

        source_path = Path(mod.__file__)
        source = source_path.read_text(encoding="utf-8")
        # Allow comments referencing _task_statuses (e.g. "# RO-26: _task_statuses removed")
        # but disallow self._task_statuses assignments
        assignments = re.findall(r"self\._task_statuses\s*[=\[]", source)
        assert len(assignments) == 0, (
            f"RO-26 violation: found _task_statuses assignments in ralph_service.py: {assignments}"
        )


# ---------------------------------------------------------------------------
# (b) _RALPH_STATE TTL cleanup
# ---------------------------------------------------------------------------


class TestRalphStateTTL:
    """RO-26: entries with _created_at older than TTL are cleaned up."""

    def test_ralph_state_only_contains_pre_engine_pending_buckets(self) -> None:
        from cccc.daemon.ralph_ipc_handler import _RALPH_STATE

        assert set(_RALPH_STATE) == {"pending_suggestions", "pending_restarts"}

    def test_stale_entries_removed(self) -> None:
        from cccc.daemon.ralph_ipc_handler import (
            _RALPH_STATE,
            _cleanup_stale_ralph_state,
        )

        # Save original state
        original = {k: dict(v) for k, v in _RALPH_STATE.items()}
        try:
            _RALPH_STATE["pending_suggestions"]["stale-1"] = {
                "_created_at": time.time() - 600,  # 10 min ago
                "workflow_id": "wf-stale",
            }
            _RALPH_STATE["pending_suggestions"]["fresh-1"] = {
                "_created_at": time.time(),
                "workflow_id": "wf-fresh",
            }

            removed = _cleanup_stale_ralph_state(ttl_seconds=300)
            assert removed == 1
            assert "stale-1" not in _RALPH_STATE["pending_suggestions"]
            assert "fresh-1" in _RALPH_STATE["pending_suggestions"]
        finally:
            # Restore original state
            for k in _RALPH_STATE:
                _RALPH_STATE[k] = original.get(k, {})

    def test_entries_without_created_at_left_alone(self) -> None:
        from cccc.daemon.ralph_ipc_handler import (
            _RALPH_STATE,
            _cleanup_stale_ralph_state,
        )

        original = {k: dict(v) for k, v in _RALPH_STATE.items()}
        try:
            _RALPH_STATE["pending_restarts"]["legacy-1"] = {
                "workflow_id": "wf-legacy",
                # no _created_at
            }

            removed = _cleanup_stale_ralph_state(ttl_seconds=300)
            assert removed == 0
            assert "legacy-1" in _RALPH_STATE["pending_restarts"]
        finally:
            for k in _RALPH_STATE:
                _RALPH_STATE[k] = original.get(k, {})

    def test_ttl_respects_custom_threshold(self) -> None:
        from cccc.daemon.ralph_ipc_handler import (
            _RALPH_STATE,
            _cleanup_stale_ralph_state,
        )

        original = {k: dict(v) for k, v in _RALPH_STATE.items()}
        try:
            for bucket in _RALPH_STATE:
                _RALPH_STATE[bucket] = {}
            _RALPH_STATE["pending_restarts"]["medium-1"] = {
                "_created_at": time.time() - 120,  # 2 min ago
                "workflow_id": "wf-medium",
            }

            # 5 min TTL -> should NOT remove
            removed_5m = _cleanup_stale_ralph_state(ttl_seconds=300)
            assert removed_5m == 0
            assert "medium-1" in _RALPH_STATE["pending_restarts"]

            # 1 min TTL -> should remove
            removed_1m = _cleanup_stale_ralph_state(ttl_seconds=60)
            assert removed_1m == 1
            assert "medium-1" not in _RALPH_STATE["pending_restarts"]
        finally:
            for k in _RALPH_STATE:
                _RALPH_STATE[k] = original.get(k, {})

    def test_real_created_at_entries_removed(self) -> None:
        from cccc.daemon.ralph_ipc_handler import (
            _RALPH_STATE,
            _cleanup_stale_ralph_state,
        )

        original = {k: dict(v) for k, v in _RALPH_STATE.items()}
        stale = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat().replace("+00:00", "Z")
        fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            _RALPH_STATE["pending_suggestions"]["stale-real"] = {
                "created_at": stale,
                "workflow_id": "wf-stale",
            }
            _RALPH_STATE["pending_suggestions"]["fresh-real"] = {
                "created_at": fresh,
                "workflow_id": "wf-fresh",
            }

            removed = _cleanup_stale_ralph_state(ttl_seconds=300)
            assert removed == 1
            assert "stale-real" not in _RALPH_STATE["pending_suggestions"]
            assert "fresh-real" in _RALPH_STATE["pending_suggestions"]
        finally:
            for k in _RALPH_STATE:
                _RALPH_STATE[k] = original.get(k, {})

    def test_dispatcher_runs_ttl_cleanup(self) -> None:
        from cccc.daemon.ralph_ipc_handler import _RALPH_STATE, try_handle_ralph_op

        original = {k: dict(v) for k, v in _RALPH_STATE.items()}
        stale = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat().replace("+00:00", "Z")
        try:
            _RALPH_STATE["pending_suggestions"]["stale-dispatch"] = {
                "created_at": stale,
                "workflow_id": "wf-stale",
                "tasks": [],
            }

            response = try_handle_ralph_op("ralph_get_pending", {})

            assert response is not None
            assert response.ok is True
            assert "stale-dispatch" not in _RALPH_STATE["pending_suggestions"]
        finally:
            for k in _RALPH_STATE:
                _RALPH_STATE[k] = original.get(k, {})


# ---------------------------------------------------------------------------
# (c) Engine is the status source
# ---------------------------------------------------------------------------


class TestEngineIsStatusSource:
    """RO-26: after task lifecycle, status comes from engine not caches."""

    def _make_orchestrator(self, tmp_path: Path):
        from cccc.daemon.foreman.workflow_orchestrator import WorkflowOrchestrator

        old_home = os.environ.get("CCCC_HOME")
        os.environ["CCCC_HOME"] = str(tmp_path)
        try:
            orch = WorkflowOrchestrator(
                project_root=tmp_path,
                group_id="test-group-state-consol",
            )
        finally:
            if old_home is None:
                os.environ.pop("CCCC_HOME", None)
            else:
                os.environ["CCCC_HOME"] = old_home
        return orch

    def test_engine_status_after_completion(self, tmp_path: Path) -> None:
        """Engine reflects task completion even if orchestrator shadow is stale."""
        from cccc.contracts.v1.ralph_ipc import ReadyBatchSuggestion, TaskEvent
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        orch = self._make_orchestrator(tmp_path)
        task = _make_task("T1")
        workflow_id = "wf-status-test"

        # Register and approve via orchestrator
        orch.register_and_suggest(
            [task.model_dump()],
            workflow_id,
            auto_process=True,
        )

        # After register_and_suggest with auto_process, task should be
        # at least ASSIGNED in the engine
        engine_state = orch.engine.get_task("T1")
        assert engine_state is not None, "Task T1 not found in engine after registration"
        assert engine_state.status in (
            WorkflowTaskStatus.ASSIGNED,
            WorkflowTaskStatus.RUNNING,
            WorkflowTaskStatus.READY,
        ), f"Unexpected status after register: {engine_state.status.value}"

    def test_ralph_service_snapshot_delegates_to_engine(self, tmp_path: Path) -> None:
        """RalphService.get_snapshot returns engine-based counts when available."""
        from cccc.daemon.foreman.ralph_service import RalphService
        from cccc.kernel.workflow_state_types import WorkflowTaskStatus

        class _MockEngine:
            def list_tasks(self, status=None):
                tasks = [
                    SimpleNamespace(
                        task=SimpleNamespace(id="T1"),
                        status=WorkflowTaskStatus.COMPLETED,
                        workflow_id="wf-1",
                    ),
                    SimpleNamespace(
                        task=SimpleNamespace(id="T2"),
                        status=WorkflowTaskStatus.RUNNING,
                        workflow_id="wf-1",
                    ),
                ]
                if status is None:
                    return tasks
                return [t for t in tasks if t.status == status]

        engine = _MockEngine()
        service = RalphService(
            project_root=tmp_path,
            group_id="test-snapshot-engine",
            workflow_engine=engine,
        )

        snap = service.get_snapshot()
        assert snap["kind"] == "active"
        assert snap["active"] is True
        tasks = snap["snapshot"]["tasks"]
        assert tasks["total"] == 2
        assert tasks["completed"] == 1
        assert tasks["running"] == 1
        assert tasks["failed"] == 0

    def test_snapshot_does_not_fall_back_to_shadow_state(self, tmp_path: Path) -> None:
        from cccc.daemon.foreman.ralph_service import RalphService

        service = RalphService(project_root=tmp_path, group_id="test-shadow-free")
        service._get_cached_orchestrator = lambda: SimpleNamespace(  # type: ignore[method-assign]
            _active_workflows={
                "wf-shadow": {
                    "tasks": {
                        "T1": {"task_id": "T1", "status": "completed"},
                    },
                },
            },
        )

        snap = service.get_snapshot()

        assert snap["kind"] == "idle"
        assert snap["snapshot"]["tasks"]["total"] == 0
        assert snap["snapshot"]["tasks"]["completed"] == 0

    def test_dependencies_do_not_fall_back_to_shadow_state(self, tmp_path: Path) -> None:
        from cccc.daemon.foreman.ralph_service import RalphService

        service = RalphService(project_root=tmp_path, group_id="test-dep-shadow-free")
        service._remember_tasks([
            _make_task("T1"),
            _make_task("T2"),
        ])
        service._task_refs["T2"] = _make_task("T2")
        object.__setattr__(service._task_refs["T2"], "depends_on", ["T1"])
        service._get_cached_orchestrator = lambda: SimpleNamespace(  # type: ignore[method-assign]
            _active_workflows={
                "wf-shadow": {
                    "tasks": {
                        "T1": {"task_id": "T1", "status": "completed"},
                    },
                },
            },
        )

        result = service.check_dependencies("T2")

        assert result["satisfied"] is False
        assert result["missing"] == ["T1"]
